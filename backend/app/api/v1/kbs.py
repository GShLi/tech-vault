from typing import Optional

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.v1.schemas import (
    KnowledgeBaseArchiveRequest,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseUpdateRequest,
)
from backend.app.api.v1.teams import (
    _if_match_version,
    _leader_or_error,
    _membership_or_error,
)
from backend.app.db.models import Document, KnowledgeBase, User


router = APIRouter(tags=["kbs"])


def _kb_view(kb: KnowledgeBase):
    return {
        "id": kb.id,
        "team_id": kb.team_id,
        "name": kb.name,
        "description": kb.description,
        "status": kb.status,
        "default_model_policy_mode": kb.model_policy_mode,
        "document_count": 0,
        "version": kb.version,
        "created_at": kb.created_at.isoformat(),
        "updated_at": kb.updated_at.isoformat(),
    }


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
    return page_envelope(
        [_kb_view(kb) for kb in page_rows],
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
    session.add(kb)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ApiError(
            409,
            "DUPLICATE_RESOURCE",
            "A knowledge base with this name already exists.",
        ) from error
    return envelope(_kb_view(kb), request.state.request_id)


@router.get("/kbs/detail")
def get_kb(
    request: Request,
    team_id: str,
    kb_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None or kb.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    return envelope(_kb_view(kb), request.state.request_id)


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
    return envelope(_kb_view(kb), request.state.request_id)


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
    session.commit()

    kb = session.get(KnowledgeBase, body.kb_id)
    if kb is None or kb.team_id != body.team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    session.refresh(kb)
    return envelope(_kb_view(kb), request.state.request_id)


@router.get("/kbs/policy")
def get_kb_policy(
    request: Request,
    team_id: str,
    kb_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None or kb.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    return envelope(
        {
            "kb_id": kb.id,
            "mode": kb.model_policy_mode,
            "version": kb.version,
        },
        request.state.request_id,
    )


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
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None or kb.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    kb.model_policy_mode = mode
    kb.version += 1
    session.commit()
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
        .where(KnowledgeBase.team_id == team_id, Document.doc_status != "deleted")
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
