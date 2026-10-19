from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session, require_super_admin
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.schemas import (
    AdminUserCreateRequest,
    LoginRequest,
    MembershipView,
    MeView,
    PasswordChangeRequest,
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
        is_super_admin=bool(user.is_super_admin),
        is_builtin=bool(user.is_builtin),
        created_at=user.created_at,
    )


@router.post("/auth/register", status_code=201)
def register(
    body: RegisterRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    if not request.app.state.settings.allow_registration:
        raise ApiError(
            403,
            "REGISTRATION_DISABLED",
            "Registration is disabled. Contact the platform administrator.",
        )

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
        {
            "access_token": token,
            "token_type": "bearer",
            "user": _user_view(user).model_dump(),
        },
        request.state.request_id,
    )


@router.post("/auth/password/change", status_code=204)
def change_password(
    body: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not verify_password(body.old_password, user.password_hash):
        raise ApiError(401, "UNAUTHENTICATED", "Current password is incorrect.")
    user.password_hash = hash_password(body.new_password)
    session.commit()
    return Response(status_code=204)


@router.post("/admin/users/create", status_code=201)
def admin_create_user(
    body: AdminUserCreateRequest,
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    team = session.get(Team, body.team_id)
    if team is None:
        raise ApiError(404, "NOT_FOUND", "Team was not found.")
    if session.scalar(select(User).where(User.email == body.email)) is not None:
        raise ApiError(409, "DUPLICATE_RESOURCE", "Email is already registered.")

    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    try:
        session.flush()
        membership = TeamMember(
            team_id=team.id,
            user_id=user.id,
            role=body.role,
            status="active",
        )
        session.add(membership)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ApiError(409, "DUPLICATE_RESOURCE", "User already exists.") from error

    return envelope(
        {
            "user": _user_view(user).model_dump(),
            "membership": MembershipView(
                team_id=team.id,
                team_name=team.name,
                role=membership.role,
                status=membership.status,
            ).model_dump(),
        },
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
