from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
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
from backend.app.db.models import KnowledgeBase, User


router = APIRouter(tags=["kbs"])


def _kb_view(kb: KnowledgeBase):
    return {
        "id": kb.id,
        "team_id": kb.team_id,
        "name": kb.name,
        "description": kb.description,
        "status": kb.status,
        "version": kb.version,
        "created_at": kb.created_at.isoformat(),
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
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    kbs = session.scalars(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.team_id == team_id,
            KnowledgeBase.status == "active",
        )
        .order_by(KnowledgeBase.created_at.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return page_envelope(
        [_kb_view(kb) for kb in kbs],
        request.state.request_id,
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
