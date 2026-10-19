import json
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import User

router = APIRouter(tags=["sources"])

@router.get("/sources")
def list_sources(request: Request, team_id: str, kb_id: str = "", user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    return page_envelope([], request.state.request_id)

@router.post("/sources/github/create", status_code=201)
def create_github_source(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    return envelope({"id": "placeholder", "repo_url": body.get("repo_url", "")}, request.state.request_id)

@router.post("/sources/sync", status_code=202)
def sync_source(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    return envelope({"synced": body.get("source_id", "")}, request.state.request_id)
