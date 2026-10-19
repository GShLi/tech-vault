from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import User

router = APIRouter(tags=["policies"])

@router.get("/model-policy")
def get_policy(request: Request, team_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    return envelope({"mode": "local_only", "allowed_provider_ids": [], "max_data_classification": "internal", "allow_chat_history": False, "allow_document_metadata": False, "require_redaction": True}, request.state.request_id)

@router.post("/model-policy/update")
def update_policy(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _leader_or_error(session, body.get("team_id", ""), user.id)
    return envelope({"mode": body.get("mode", "local_only")}, request.state.request_id)

@router.get("/admin/model-policy")
def admin_policy(request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return envelope({"mode": "local_only"}, request.state.request_id)

@router.post("/admin/model-policy/update")
def admin_update_policy(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return envelope({"mode": body.get("mode", "local_only")}, request.state.request_id)
