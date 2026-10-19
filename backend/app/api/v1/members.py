from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import TeamMember, User

router = APIRouter(tags=["members"])


@router.get("/members")
def list_members(request: Request, team_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    rows = session.execute(
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team_id)
        .order_by(TeamMember.joined_at.desc())
    ).all()
    return page_envelope(
        [{"team_id": m.team_id, "user_id": m.user_id, "role": m.role, "status": m.status,
          "email": u.email, "display_name": u.display_name, "joined_at": m.joined_at.isoformat()} for m, u in rows],
        request.state.request_id,
    )


@router.post("/members/update")
def update_member(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _leader_or_error(session, body.get("team_id", ""), user.id)
    target_user_id = body.get("user_id", "")
    target = session.get(User, target_user_id)
    if target is not None and target.is_builtin:
        raise ApiError(
            403,
            "PROTECTED_ACCOUNT",
            "The built-in administrator cannot be modified.",
        )
    member = session.get(TeamMember, (body.get("team_id", ""), target_user_id))
    if member is None:
        raise ApiError(404, "NOT_FOUND", "Member not found.")
    role = body.get("role")
    if role is not None and role not in {"leader", "member", "viewer"}:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid team role.")
    for field in ("role", "status"):
        value = body.get(field)
        if value is not None:
            setattr(member, field, value)
    session.commit()
    return envelope({"team_id": member.team_id, "user_id": member.user_id, "role": member.role, "status": member.status}, request.state.request_id)


@router.post("/members/remove")
def remove_member(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _leader_or_error(session, body.get("team_id", ""), user.id)
    target_user_id = body.get("user_id", "")
    target = session.get(User, target_user_id)
    if target is not None and target.is_builtin:
        raise ApiError(
            403,
            "PROTECTED_ACCOUNT",
            "The built-in administrator cannot be removed.",
        )
    member = session.get(TeamMember, (body.get("team_id", ""), target_user_id))
    if member is None:
        raise ApiError(404, "NOT_FOUND", "Member not found.")
    member.status = "removed"
    session.commit()
    return envelope({"removed": member.user_id}, request.state.request_id)
