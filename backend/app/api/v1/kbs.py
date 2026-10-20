from typing import Optional

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor, paginate_rows
from backend.app.api.v1.schemas import (
    KnowledgeBaseArchiveRequest,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseUpdateRequest,
)
from backend.app.api.v1.model_policy import policy_mode_ceiling
from backend.app.api.v1.kb_access import (
    knowledge_base_member_ids,
    knowledge_base_or_error,
)
from backend.app.api.v1.documents import _readable_documents_filter
from backend.app.api.v1.teams import (
    _if_match_version,
    _leader_or_error,
    _membership_or_error,
)
from backend.app.db.models import (
    Document,
    KnowledgeBase,
    KnowledgeBaseMember,
    TeamMember,
    User,
)
from backend.app.modules.audit.service import write_audit


router = APIRouter(tags=["kbs"])


def _document_count(session: Session, kb_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.knowledge_base_id == kb_id,
                Document.doc_status != "deleted",
            )
        )
        or 0
    )


def _document_counts(session: Session, kb_ids: list[str]) -> dict[str, int]:
    if not kb_ids:
        return {}
    rows = session.execute(
        select(Document.knowledge_base_id, func.count())
        .where(
            Document.knowledge_base_id.in_(kb_ids),
            Document.doc_status != "deleted",
        )
        .group_by(Document.knowledge_base_id)
    ).all()
    return {kb_id: int(count) for kb_id, count in rows}


def _kb_view(kb: KnowledgeBase, document_count: int):
    return {
        "id": kb.id,
        "team_id": kb.team_id,
        "name": kb.name,
        "description": kb.description,
        "status": kb.status,
        "default_model_policy_mode": kb.model_policy_mode,
        "document_count": document_count,
        "version": kb.version,
        "created_at": kb.created_at.isoformat(),
        "updated_at": kb.updated_at.isoformat(),
    }


def _member_views(session: Session, kb_id: str) -> list:
    rows = session.execute(
        select(KnowledgeBaseMember, User)
        .join(User, User.id == KnowledgeBaseMember.user_id)
        .where(
            KnowledgeBaseMember.kb_id == kb_id,
            KnowledgeBaseMember.status == "active",
            User.is_active.is_(True),
        )
        .order_by(User.display_name.asc(), User.id.asc())
    ).all()
    return [
        {
            "kb_id": membership.kb_id,
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "status": membership.status,
        }
        for membership, user in rows
    ]


def _kb_cas_error(session: Session, team_id: str, kb_id: str) -> None:
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None or kb.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    if kb.status != "active":
        raise ApiError(
            409,
            "RESOURCE_STATE_CONFLICT",
            "Archived knowledge bases are immutable.",
        )
    raise ApiError(409, "VERSION_CONFLICT", "Resource version has changed.")


@router.get("/kbs")
def list_kbs(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    page_limit = max(1, min(limit, 100))
    query = select(KnowledgeBase).where(
        KnowledgeBase.team_id == team_id,
        KnowledgeBase.status == "active",
        KnowledgeBase.id.in_(knowledge_base_member_ids(session, team_id, user.id)),
    )
    if cursor is not None:
        after_created, after_id = decode_cursor(cursor)
        query = query.where(
            or_(
                KnowledgeBase.created_at < after_created,
                and_(
                    KnowledgeBase.created_at == after_created,
                    KnowledgeBase.id < after_id,
                ),
            )
        )

    rows = session.scalars(
        query.order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc()).limit(
            page_limit + 1
        )
    ).all()
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    next_cursor = (
        encode_cursor(page_rows[-1].created_at, page_rows[-1].id)
        if has_more and page_rows
        else None
    )
    document_counts = _document_counts(session, [kb.id for kb in page_rows])
    return page_envelope(
        [_kb_view(kb, document_counts.get(kb.id, 0)) for kb in page_rows],
        request.state.request_id,
        next_cursor,
    )


@router.post("/kbs/create", status_code=201)
def create_kb(
    body: KnowledgeBaseCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, body.team_id, user.id)
    kb = KnowledgeBase(
        team_id=body.team_id,
        name=body.name.strip(),
        description=body.description,
        created_by=user.id,
    )
    try:
        session.add(kb)
        session.flush()
        session.add(
            KnowledgeBaseMember(
                kb_id=kb.id,
                user_id=user.id,
                status="active",
                added_by=user.id,
            )
        )
        write_audit(
            session,
            team_id=body.team_id,
            actor_id=user.id,
            action="kb.create",
            resource_type="knowledge_base",
            resource_id=kb.id,
            details={"name": kb.name, "status": kb.status, "version": kb.version},
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ApiError(
            409,
            "DUPLICATE_RESOURCE",
            "A knowledge base with this name already exists.",
        ) from error
    return envelope(_kb_view(kb, _document_count(session, kb.id)), request.state.request_id)


@router.get("/kbs/detail")
def get_kb(
    request: Request,
    team_id: str,
    kb_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    kb = knowledge_base_or_error(session, team_id, kb_id, user.id)
    return envelope(_kb_view(kb, _document_count(session, kb.id)), request.state.request_id)


@router.post("/kbs/update")
def update_kb(
    body: KnowledgeBaseUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, body.team_id, user.id)
    expected_version = _if_match_version(request)
    try:
        result = session.execute(
            update(KnowledgeBase)
            .where(
                KnowledgeBase.id == body.kb_id,
                KnowledgeBase.team_id == body.team_id,
                KnowledgeBase.version == expected_version,
                KnowledgeBase.status == "active",
            )
            .values(
                name=body.name,
                description=body.description,
                version=KnowledgeBase.version + 1,
            )
        )
        if result.rowcount == 0:
            session.rollback()
            _kb_cas_error(session, body.team_id, body.kb_id)
        write_audit(
            session,
            team_id=body.team_id,
            actor_id=user.id,
            action="kb.update",
            resource_type="knowledge_base",
            resource_id=body.kb_id,
            details={"name": body.name, "version": expected_version + 1},
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ApiError(
            409,
            "DUPLICATE_RESOURCE",
            "A knowledge base with this name already exists.",
        ) from error

    kb = session.get(KnowledgeBase, body.kb_id)
    if kb is None or kb.team_id != body.team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    session.refresh(kb)
    return envelope(_kb_view(kb, _document_count(session, kb.id)), request.state.request_id)


@router.post("/kbs/archive", status_code=202)
def archive_kb(
    body: KnowledgeBaseArchiveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, body.team_id, user.id)
    expected_version = _if_match_version(request)
    result = session.execute(
        update(KnowledgeBase)
        .where(
            KnowledgeBase.id == body.kb_id,
            KnowledgeBase.team_id == body.team_id,
            KnowledgeBase.version == expected_version,
            KnowledgeBase.status == "active",
        )
        .values(status="archived", version=KnowledgeBase.version + 1)
    )
    if result.rowcount == 0:
        session.rollback()
        _kb_cas_error(session, body.team_id, body.kb_id)
    write_audit(
        session,
        team_id=body.team_id,
        actor_id=user.id,
        action="kb.archive",
        resource_type="knowledge_base",
        resource_id=body.kb_id,
        details={"status": "archived", "version": expected_version + 1},
    )
    session.commit()

    kb = session.get(KnowledgeBase, body.kb_id)
    if kb is None or kb.team_id != body.team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    session.refresh(kb)
    return envelope(_kb_view(kb, _document_count(session, kb.id)), request.state.request_id)


@router.get("/kbs/policy")
def get_kb_policy(
    request: Request,
    team_id: str,
    kb_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    kb = knowledge_base_or_error(session, team_id, kb_id, user.id)
    return envelope(
        {
            "kb_id": kb.id,
            "mode": kb.model_policy_mode,
            "version": kb.version,
        },
        request.state.request_id,
    )


@router.get("/kbs/members")
def list_kb_members(
    request: Request,
    team_id: str,
    kb_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    knowledge_base_or_error(session, team_id, kb_id, user.id)
    query = (
        select(KnowledgeBaseMember, User)
        .join(User, User.id == KnowledgeBaseMember.user_id)
        .where(
            KnowledgeBaseMember.kb_id == kb_id,
            KnowledgeBaseMember.status == "active",
            User.is_active.is_(True),
        )
    )
    return paginate_rows(
        session,
        query,
        timestamp_column=KnowledgeBaseMember.created_at,
        id_column=KnowledgeBaseMember.user_id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda row: {
            "kb_id": row[0].kb_id,
            "user_id": row[1].id,
            "email": row[1].email,
            "display_name": row[1].display_name,
            "status": row[0].status,
        },
    )


@router.post("/kbs/members/update")
def update_kb_members(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    kb_id = body.get("kb_id", "")
    raw_user_ids = body.get("user_ids")
    _leader_or_error(session, team_id, user.id)
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None or kb.team_id != team_id or kb.status != "active":
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    if not isinstance(raw_user_ids, list) or any(
        not isinstance(item, str) or not item for item in raw_user_ids
    ):
        raise ApiError(
            400,
            "INVALID_ARGUMENT",
            "user_ids must be an array of user identifiers.",
        )
    user_ids = list(dict.fromkeys(raw_user_ids))
    if user_ids:
        active_ids = set(
            session.scalars(
                select(TeamMember.user_id).where(
                    TeamMember.team_id == team_id,
                    TeamMember.user_id.in_(tuple(user_ids)),
                    TeamMember.status == "active",
                )
            ).all()
        )
        if active_ids != set(user_ids):
            raise ApiError(
                400,
                "INVALID_ARGUMENT",
                "All knowledge base members must be active team members.",
            )

    session.execute(
        delete(KnowledgeBaseMember).where(KnowledgeBaseMember.kb_id == kb_id)
    )
    session.add_all(
        [
            KnowledgeBaseMember(
                kb_id=kb_id,
                user_id=member_id,
                status="active",
                added_by=user.id,
            )
            for member_id in user_ids
        ]
    )
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="kb.members.update",
        resource_type="knowledge_base",
        resource_id=kb_id,
        details={"user_ids": user_ids},
    )
    session.commit()
    return envelope(_member_views(session, kb_id), request.state.request_id)


@router.post("/kbs/policy/update")
def update_kb_policy(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    kb_id = body.get("kb_id", "")
    mode = body.get("mode", "local_only")
    if mode not in {"local_only", "external_allowed", "external_required"}:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid model policy mode.")
    _leader_or_error(session, team_id, user.id)
    expected_version = _if_match_version(request)
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None or kb.team_id != team_id or kb.status != "active":
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    ceiling = policy_mode_ceiling(session, team_id)
    mode_rank = {"local_only": 0, "external_allowed": 1, "external_required": 2}
    if mode_rank[mode] > mode_rank[ceiling]:
        raise ApiError(
            409,
            "TEAM_POLICY_LIMIT",
            "Knowledge base policy cannot be wider than the team policy.",
        )
    result = session.execute(
        update(KnowledgeBase)
        .where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.team_id == team_id,
            KnowledgeBase.version == expected_version,
            KnowledgeBase.status == "active",
        )
        .values(
            model_policy_mode=mode,
            version=KnowledgeBase.version + 1,
        )
    )
    if result.rowcount == 0:
        session.rollback()
        _kb_cas_error(session, team_id, kb_id)
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="kb.policy.update",
        resource_type="knowledge_base",
        resource_id=kb_id,
        details={"mode": mode, "version": expected_version + 1},
    )
    session.commit()
    session.refresh(kb)
    return envelope(
        {"kb_id": kb.id, "mode": kb.model_policy_mode, "version": kb.version},
        request.state.request_id,
    )


@router.get("/facets")
def list_facets(
    request: Request,
    team_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    rows = session.execute(
        select(Document, KnowledgeBase)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.team_id == team_id,
            Document.doc_status != "deleted",
            KnowledgeBase.id.in_(
                knowledge_base_member_ids(session, team_id, user.id)
            ),
            _readable_documents_filter(session, team_id, user),
        )
    ).all()
    products = sorted({doc.product for doc, _ in rows if doc.product})
    versions = sorted(
        {
            value
            for doc, _ in rows
            for value in json.loads(doc.version_values or "[]")
        }
    )
    sources = sorted({doc.source_type for doc, _ in rows})
    return envelope(
        {
            "products": products,
            "versions": versions,
            "sources": sources,
            "knowledge_base_ids": sorted({kb.id for _, kb in rows}),
        },
        request.state.request_id,
    )
