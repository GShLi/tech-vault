import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import Credential, KnowledgeBase, SourceConnection, User


router = APIRouter(tags=["sources"])


def _source_or_error(session: Session, team_id: str, source_id: str) -> SourceConnection:
    source = session.get(SourceConnection, source_id)
    if source is None or source.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Source was not found.")
    return source


def _source_view(source: SourceConnection) -> dict:
    return {
        "id": source.id,
        "team_id": source.team_id,
        "kb_id": source.kb_id,
        "source_type": source.source_type,
        "repo_url": source.repo_url,
        "branch": source.branch,
        "path_filters": json.loads(source.path_filters or "[]"),
        "credentials_id": source.credentials_id,
        "status": source.status,
        "sync_cursor": source.sync_cursor,
        "created_at": source.created_at.isoformat(),
        "updated_at": source.updated_at.isoformat(),
    }


@router.get("/sources")
def list_sources(
    request: Request,
    team_id: str,
    kb_id: str = "",
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    query = select(SourceConnection).where(SourceConnection.team_id == team_id)
    if kb_id:
        query = query.where(SourceConnection.kb_id == kb_id)
    sources = session.scalars(query.order_by(SourceConnection.created_at.desc())).all()
    return page_envelope([_source_view(source) for source in sources], request.state.request_id)


@router.post("/sources/github/create", status_code=201)
def create_github_source(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    kb_id = body.get("kb_id", "")
    _leader_or_error(session, team_id, user.id)
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None or kb.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    source = SourceConnection(
        team_id=team_id,
        kb_id=kb_id,
        source_type="github",
        repo_url=body.get("repo_url", ""),
        branch=body.get("branch", "main"),
        path_filters=json.dumps(body.get("path_filters", [])),
        credentials_id=body.get("credentials_id"),
        created_by=user.id,
    )
    session.add(source)
    session.commit()
    return envelope(_source_view(source), request.state.request_id)


@router.get("/sources/detail")
def get_source(
    request: Request,
    team_id: str,
    source_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    source = _source_or_error(session, team_id, source_id)
    return envelope(_source_view(source), request.state.request_id)


@router.post("/sources/update")
def update_source(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    for field in ("repo_url", "branch", "credentials_id"):
        if body.get(field) is not None:
            setattr(source, field, body[field])
    if body.get("path_filters") is not None:
        source.path_filters = json.dumps(body["path_filters"])
    session.commit()
    return envelope(_source_view(source), request.state.request_id)


@router.post("/sources/delete")
def delete_source(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    session.delete(source)
    session.commit()
    return envelope({"deleted": source.id}, request.state.request_id)


@router.post("/sources/sync", status_code=202)
def sync_source(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    source.sync_cursor = body.get("cursor", source.sync_cursor or "queued")
    session.commit()
    return envelope({"source_id": source.id, "status": "queued"}, request.state.request_id)


@router.post("/sources/pause")
def pause_source(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    source.status = "paused"
    session.commit()
    return envelope({"source_id": source.id, "status": source.status}, request.state.request_id)


@router.post("/sources/resume")
def resume_source(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    source.status = "active"
    session.commit()
    return envelope({"source_id": source.id, "status": source.status}, request.state.request_id)


@router.get("/credentials")
def list_credentials(
    request: Request,
    team_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    rows = session.scalars(
        select(Credential).where(Credential.team_id == team_id).order_by(Credential.created_at.desc())
    ).all()
    return page_envelope(
        [{"id": row.id, "name": row.name, "secret_masked": row.secret_masked, "created_at": row.created_at.isoformat()} for row in rows],
        request.state.request_id,
    )


@router.post("/credentials/create", status_code=201)
def create_credential(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    secret = body.get("secret", "")
    if not secret:
        raise ApiError(400, "INVALID_ARGUMENT", "Secret is required.")
    credential = Credential(
        team_id=team_id,
        name=body.get("name", "credential"),
        secret_masked="****" + secret[-4:],
        created_by=user.id,
    )
    session.add(credential)
    session.commit()
    return envelope(
        {"id": credential.id, "name": credential.name, "secret_masked": credential.secret_masked},
        request.state.request_id,
    )


@router.post("/credentials/delete")
def delete_credential(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    credential = session.get(Credential, body.get("credential_id", ""))
    if credential is None or credential.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Credential was not found.")
    session.delete(credential)
    session.commit()
    return envelope({"deleted": credential.id}, request.state.request_id)
