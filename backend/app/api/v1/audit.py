from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import page_envelope, envelope
from backend.app.api.v1.teams import _membership_or_error
from backend.app.db.models import User

router = APIRouter(tags=["audit"])

@router.get("/audit")
def list_audit(request: Request, team_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    return page_envelope([], request.state.request_id)

@router.get("/generations")
def list_generations(request: Request, team_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    return page_envelope([], request.state.request_id)

@router.post("/generations/activate")
def activate_generation(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, body.get("team_id", ""), user.id)
    return envelope({"activated": body.get("generation_id", "")}, request.state.request_id)
