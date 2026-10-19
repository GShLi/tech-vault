from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import (
    get_auth_context,
    get_current_user,
    get_session,
    require_super_admin,
)
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.schemas import (
    AdminUserCreateRequest,
    LoginRequest,
    MembershipView,
    MeView,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    UserUpdateRequest,
    UserView,
)
from backend.app.core.ids import new_ulid
from backend.app.core.passwords import hash_password, verify_password
from backend.app.core.tokens import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token_claims,
)
from backend.app.db.models import AuthSession, Team, TeamMember, User


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


def _session_tokens(user: User, auth_session: AuthSession, settings) -> dict:
    return {
        "access_token": create_access_token(
            user.id,
            settings,
            session_id=auth_session.id,
        ),
        "refresh_token": create_refresh_token(
            user.id,
            settings,
            session_id=auth_session.id,
            refresh_jti=auth_session.refresh_jti,
        ),
        "token_type": "bearer",
        "user": _user_view(user).model_dump(),
    }


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

    now = datetime.now(timezone.utc)
    auth_session = AuthSession(
        user_id=user.id,
        refresh_jti=new_ulid(),
        expires_at=now
        + timedelta(seconds=request.app.state.settings.refresh_token_ttl_seconds),
    )
    session.add(auth_session)
    session.commit()
    return envelope(
        _session_tokens(user, auth_session, request.app.state.settings),
        request.state.request_id,
    )


@router.post("/auth/refresh")
def refresh_token(
    body: RefreshRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    try:
        claims = decode_token_claims(
            body.refresh_token,
            request.app.state.settings,
            expected_type="refresh",
        )
    except TokenError as error:
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token.") from error

    auth_session = session.get(AuthSession, claims.get("sid"))
    now = datetime.now(timezone.utc)
    if (
        auth_session is None
        or auth_session.user_id != claims["sub"]
        or auth_session.refresh_jti != claims.get("jti")
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= now
    ):
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token.")
    user = session.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "UNAUTHENTICATED", "User is not active.")

    auth_session.refresh_jti = new_ulid()
    auth_session.expires_at = now + timedelta(
        seconds=request.app.state.settings.refresh_token_ttl_seconds
    )
    session.commit()
    return envelope(
        _session_tokens(user, auth_session, request.app.state.settings),
        request.state.request_id,
    )


@router.post("/auth/logout", status_code=204)
def logout(
    context=Depends(get_auth_context),
    session: Session = Depends(get_session),
):
    if context.auth_session is not None:
        context.auth_session.revoked_at = datetime.now(timezone.utc)
        session.commit()
    return Response(status_code=204)


@router.post("/users/update")
def update_user(
    body: UserUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    user.display_name = body.display_name
    session.commit()
    return envelope(_user_view(user).model_dump(), request.state.request_id)


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
