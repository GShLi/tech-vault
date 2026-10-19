from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.schemas import (
    LoginRequest,
    MembershipView,
    MeView,
    RegisterRequest,
    UserView,
)
from backend.app.core.passwords import hash_password, verify_password
from backend.app.core.tokens import create_access_token
from backend.app.db.models import Team, TeamMember, User


router = APIRouter(tags=["auth"])

_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-login-timing")


def _user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status="active" if user.is_active else "disabled",
        created_at=user.created_at,
    )


@router.post("/auth/register", status_code=201)
def register(
    body: RegisterRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    email = body.email
    if session.scalar(select(User).where(User.email == email)) is not None:
        raise ApiError(409, "DUPLICATE_RESOURCE", "Email is already registered.")

    user = User(
        email=email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ApiError(409, "DUPLICATE_RESOURCE", "Email is already registered.") from error

    return envelope(_user_view(user).model_dump(), request.state.request_id)


@router.post("/auth/login")
def login(
    body: LoginRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    email = body.email
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        verify_password(body.password, _DUMMY_PASSWORD_HASH)
        raise ApiError(401, "UNAUTHENTICATED", "Invalid email or password.")
    if not verify_password(body.password, user.password_hash):
        raise ApiError(401, "UNAUTHENTICATED", "Invalid email or password.")

    token = create_access_token(user.id, request.app.state.settings)
    return envelope(
        {"access_token": token, "token_type": "bearer"},
        request.state.request_id,
    )


@router.get("/auth/me")
def me(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = session.execute(
        select(TeamMember, Team)
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.user_id == user.id)
        .order_by(Team.created_at.desc())
    ).all()
    memberships = [
        MembershipView(
            team_id=team.id,
            team_name=team.name,
            role=membership.role,
            status=membership.status,
        )
        for membership, team in rows
    ]
    return envelope(
        MeView(
            user=_user_view(user),
            memberships=memberships,
        ).model_dump(),
        request.state.request_id,
    )
