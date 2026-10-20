import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import paginate_scalars
from backend.app.api.v1.kb_access import (
    knowledge_base_member_ids,
    knowledge_base_or_error,
)
from backend.app.api.v1.teams import (
    _editor_or_error,
    _leader_or_error,
    _membership_or_error,
)
from backend.app.core.secrets import encrypt_secret
from backend.app.db.models import Credential, SourceConnection, User
from backend.app.modules.audit.service import write_audit
from backend.app.modules.sources.github import (
    GitHubSyncError,
    parse_github_repository,
    parse_path_filters,
    remove_source_documents,
)
from backend.app.workers.dispatch import TaskDispatchError, dispatch_source_sync


router = APIRouter(tags=["sources"])


def _source_or_error(session: Session, team_id: str, source_id: str) -> SourceConnection:
    source = session.get(SourceConnection, source_id)
    if source is None or source.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Source was not found.")
    return source


def _source_manager_or_error(
    session: Session,
    team_id: str,
    source: SourceConnection,
    user: User,
) -> None:
    membership = _editor_or_error(session, team_id, user.id)
    if membership.role == "leader" or source.created_by == user.id:
        return
    raise ApiError(
        403,
        "PERMISSION_DENIED",
        "Source edit permission is required.",
    )


def _source_view(source: SourceConnection) -> dict:
    try:
        path_filters = json.loads(source.path_filters or "[]")
    except json.JSONDecodeError:
        path_filters = []
    return {
        "id": source.id,
        "team_id": source.team_id,
        "kb_id": source.kb_id,
        "source_type": source.source_type,
        "repo_url": source.repo_url,
        "branch": source.branch,
        "path_filters": path_filters,
        "credentials_id": source.credentials_id,
        "created_by": source.created_by,
        "status": source.status,
        "sync_cursor": source.sync_cursor,
        "created_at": source.created_at.isoformat(),
        "updated_at": source.updated_at.isoformat(),
    }


def _source_audit_details(source: SourceConnection) -> dict:
    try:
        path_filters = json.loads(source.path_filters or "[]")
    except json.JSONDecodeError:
        path_filters = []
    return {
        "kb_id": source.kb_id,
        "source_type": source.source_type,
        "branch": source.branch,
        "path_filters": path_filters,
        "status": source.status,
    }


def _validated_repository_url(value: str) -> str:
    try:
        parse_github_repository(value)
    except GitHubSyncError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    return value.strip()


def _serialized_path_filters(value) -> str:
    if value is None:
        value = []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ApiError(
            400,
            "INVALID_ARGUMENT",
            "path_filters must be an array of strings.",
        )
    raw = json.dumps([item.strip() for item in value if item.strip()])
    try:
        parse_path_filters(raw)
    except GitHubSyncError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    return raw


def _credential_or_error(
    session: Session,
    team_id: str,
    credential_id: str,
) -> Credential:
    credential = session.get(Credential, credential_id)
    if credential is None or credential.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Credential was not found.")
    return credential


@router.get("/sources")
def list_sources(
    request: Request,
    team_id: str,
    kb_id: str = "",
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    if kb_id:
        knowledge_base_or_error(session, team_id, kb_id, user.id)
    query = select(SourceConnection).where(
        SourceConnection.team_id == team_id,
        SourceConnection.kb_id.in_(
            knowledge_base_member_ids(session, team_id, user.id)
        ),
    )
    if kb_id:
        query = query.where(SourceConnection.kb_id == kb_id)
    return paginate_scalars(
        session,
        query,
        timestamp_column=SourceConnection.created_at,
        id_column=SourceConnection.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=_source_view,
    )


@router.post("/sources/github/create", status_code=201)
def create_github_source(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    kb_id = body.get("kb_id", "")
    _editor_or_error(session, team_id, user.id)
    knowledge_base_or_error(session, team_id, kb_id, user.id)
    repo_url = _validated_repository_url(body.get("repo_url", ""))
    credentials_id = body.get("credentials_id")
    if credentials_id:
        _credential_or_error(session, team_id, credentials_id)
    source = SourceConnection(
        team_id=team_id,
        kb_id=kb_id,
        source_type="github",
        repo_url=repo_url,
        branch=body.get("branch", "main"),
        path_filters=_serialized_path_filters(body.get("path_filters", [])),
        credentials_id=credentials_id,
        created_by=user.id,
    )
    session.add(source)
    session.flush()
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="source.create",
        resource_type="source_connection",
        resource_id=source.id,
        details=_source_audit_details(source),
    )
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
    knowledge_base_or_error(session, team_id, source.kb_id, user.id)
    return envelope(_source_view(source), request.state.request_id)


@router.post("/sources/update")
def update_source(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    _source_manager_or_error(session, team_id, source, user)
    knowledge_base_or_error(session, team_id, source.kb_id, user.id)
    if body.get("repo_url") is not None:
        source.repo_url = _validated_repository_url(body["repo_url"])
    if body.get("credentials_id"):
        _credential_or_error(session, team_id, body["credentials_id"])
    for field in ("repo_url", "branch", "credentials_id"):
        if field != "repo_url" and body.get(field) is not None:
            setattr(source, field, body[field])
    if body.get("path_filters") is not None:
        source.path_filters = _serialized_path_filters(body["path_filters"])
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="source.update",
        resource_type="source_connection",
        resource_id=source.id,
        details=_source_audit_details(source),
    )
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
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    _source_manager_or_error(session, team_id, source, user)
    knowledge_base_or_error(session, team_id, source.kb_id, user.id)
    try:
        remove_source_documents(source, session, request.app.state.settings)
    except GitHubSyncError as error:
        raise ApiError(error.status_code, error.code, error.message) from error
    session.delete(source)
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="source.delete",
        resource_type="source_connection",
        resource_id=source.id,
        details={"kb_id": source.kb_id, "status": "deleted"},
    )
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
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    _source_manager_or_error(session, team_id, source, user)
    knowledge_base_or_error(session, team_id, source.kb_id, user.id)
    if source.status == "paused":
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Source synchronization is paused.")
    if source.status == "syncing":
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Source synchronization is already running.")
    source.status = "syncing"
    session.commit()
    try:
        result = dispatch_source_sync(
            session,
            source.id,
            request.app.state.settings,
        )
    except TaskDispatchError as error:
        source.status = "error"
        write_audit(
            session,
            team_id=team_id,
            actor_id=user.id,
            action="source.sync.queue_failed",
            resource_type="source_connection",
            resource_id=source.id,
            details={"kb_id": source.kb_id, "status": source.status},
        )
        session.commit()
        raise ApiError(
            503,
            "TASK_QUEUE_UNAVAILABLE",
            "The source synchronization queue is unavailable.",
        ) from error
    except GitHubSyncError as error:
        source = _source_or_error(session, team_id, body.get("source_id", ""))
        source.status = "error"
        session.commit()
        raise ApiError(error.status_code, error.code, error.message) from error
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="source.sync",
        resource_type="source_connection",
        resource_id=source.id,
        details=result,
    )
    session.commit()
    return envelope(result, request.state.request_id)


@router.post("/sources/pause")
def pause_source(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    _source_manager_or_error(session, team_id, source, user)
    knowledge_base_or_error(session, team_id, source.kb_id, user.id)
    source.status = "paused"
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="source.pause",
        resource_type="source_connection",
        resource_id=source.id,
        details={"kb_id": source.kb_id, "status": source.status},
    )
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
    source = _source_or_error(session, team_id, body.get("source_id", ""))
    _source_manager_or_error(session, team_id, source, user)
    knowledge_base_or_error(session, team_id, source.kb_id, user.id)
    source.status = "active"
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="source.resume",
        resource_type="source_connection",
        resource_id=source.id,
        details={"kb_id": source.kb_id, "status": source.status},
    )
    session.commit()
    return envelope({"source_id": source.id, "status": source.status}, request.state.request_id)


@router.get("/credentials")
def list_credentials(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, team_id, user.id)
    query = select(Credential).where(Credential.team_id == team_id)
    return paginate_scalars(
        session,
        query,
        timestamp_column=Credential.created_at,
        id_column=Credential.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda row: {
            "id": row.id,
            "name": row.name,
            "secret_masked": row.secret_masked,
            "created_at": row.created_at.isoformat(),
        },
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
        secret_encrypted=encrypt_secret(secret, request.app.state.settings),
        created_by=user.id,
    )
    session.add(credential)
    session.flush()
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="credential.create",
        resource_type="credential",
        resource_id=credential.id,
        details={"name": credential.name},
    )
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
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="credential.delete",
        resource_type="credential",
        resource_id=credential.id,
        details={"name": credential.name},
    )
    session.delete(credential)
    session.commit()
    return envelope({"deleted": credential.id}, request.state.request_id)
