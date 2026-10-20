import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.schemas import InvitationAcceptRequest, InvitationCreateRequest
from backend.app.api.v1.teams import _leader_or_error
from backend.app.db.models import AuditLog, Invitation, Team, TeamMember, User


router = APIRouter(tags=["invitations"])
_INVITATION_TTL = timedelta(days=7)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _invitation_view(invitation: Invitation, team: Team) -> dict:
    return {
        "id": invitation.id,
        "team_id": invitation.team_id,
        "team_name": team.name,
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.status,
        "expires_at": invitation.expires_at.isoformat(),
        "created_at": invitation.created_at.isoformat(),
        "accepted_at": invitation.accepted_at.isoformat()
        if invitation.accepted_at is not None
        else None,
    }


def _invitation_by_token(session: Session, token: str) -> Invitation:
    invitation = session.scalar(
        select(Invitation).where(Invitation.token == _token_hash(token))
    )
    if invitation is None:
        raise ApiError(404, "NOT_FOUND", "Invitation was not found.")
    if invitation.status == "pending" and invitation.expires_at <= datetime.now(
        timezone.utc
    ):
        invitation.status = "expired"
        session.commit()
    return invitation


@router.post("/invitations/create", status_code=201)
def create_invitation(
    body: InvitationCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, body.team_id, user.id)
    team = session.get(Team, body.team_id)
    if team is None:
        raise ApiError(404, "NOT_FOUND", "Team was not found.")

    existing_user = session.scalar(select(User).where(User.email == body.email))
    if existing_user is not None:
        existing_membership = session.get(TeamMember, (body.team_id, existing_user.id))
        if existing_membership is not None and existing_membership.status == "active":
            raise ApiError(409, "DUPLICATE_RESOURCE", "User is already a team member.")

    pending = session.scalar(
        select(Invitation).where(
            Invitation.team_id == body.team_id,
            Invitation.email == body.email,
            Invitation.status == "pending",
        )
    )
    if pending is not None:
        raise ApiError(409, "DUPLICATE_RESOURCE", "A pending invitation already exists.")

    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(
        team_id=body.team_id,
        email=body.email,
        role=body.role,
        token=_token_hash(raw_token),
        status="pending",
        invited_by=user.id,
        expires_at=datetime.now(timezone.utc) + _INVITATION_TTL,
    )
    session.add(invitation)
    session.flush()
    session.add(
        AuditLog(
            team_id=body.team_id,
            actor_id=user.id,
            action="invitation.create",
            resource_type="invitation",
            resource_id=invitation.id,
            details='{"email":"%s","role":"%s"}' % (body.email, body.role),
        )
    )
    session.commit()
    data = _invitation_view(invitation, team)
    data["token"] = raw_token
    data["invitation_url"] = "/invite/" + raw_token
    return envelope(data, request.state.request_id)


@router.get("/invitations/detail")
def get_invitation(
    request: Request,
    token: str,
    session: Session = Depends(get_session),
):
    invitation = _invitation_by_token(session, token)
    team = session.get(Team, invitation.team_id)
    if team is None:
        raise ApiError(404, "NOT_FOUND", "Team was not found.")
    return envelope(_invitation_view(invitation, team), request.state.request_id)


@router.post("/invitations/accept")
def accept_invitation(
    body: InvitationAcceptRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    invitation = _invitation_by_token(session, body.token)
    if invitation.status == "expired":
        raise ApiError(410, "INVITATION_EXPIRED", "Invitation has expired.")
    if invitation.status != "pending":
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Invitation is not pending.")
    if user.email.lower() != invitation.email.lower():
        raise ApiError(
            403,
            "INVITATION_EMAIL_MISMATCH",
            "Invitation belongs to a different email address.",
        )

    membership = session.get(TeamMember, (invitation.team_id, user.id))
    if membership is None:
        membership = TeamMember(
            team_id=invitation.team_id,
            user_id=user.id,
            role=invitation.role,
            status="active",
        )
        session.add(membership)
    else:
        membership.role = invitation.role
        membership.status = "active"
    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(timezone.utc)
    session.add(
        AuditLog(
            team_id=invitation.team_id,
            actor_id=user.id,
            action="invitation.accept",
            resource_type="invitation",
            resource_id=invitation.id,
            details='{"role":"%s"}' % invitation.role,
        )
    )
    session.commit()
    return envelope(
        {
            "team_id": membership.team_id,
            "user_id": membership.user_id,
            "role": membership.role,
            "status": membership.status,
        },
        request.state.request_id,
    )
