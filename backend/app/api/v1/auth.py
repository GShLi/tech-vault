from datetime import datetime, timedelta, timezone
from typing import Optional

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
from backend.app.api.pagination import paginate_scalars
from backend.app.api.v1.schemas import (
    AdminUserCreateRequest,
    AdminUserView,
    AdminUserUpdateRequest,
    LoginRequest,
    MembershipView,
    MeView,
    PasswordChangeRequest,
    UserUpdateRequest,
    UserView,
)
from backend.app.api.v1.members import (
    ensure_not_last_active_leader,
    ensure_user_can_be_disabled,
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
from backend.app.modules.audit.service import write_audit


router = APIRouter(tags=["auth"])

_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-login-timing")
_REFRESH_COOKIE = "techvault_refresh"


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


def _admin_user_view(session: Session, user: User) -> AdminUserView:
    rows = session.execute(
        select(TeamMember, Team)
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.user_id == user.id)
        .order_by(Team.name.asc(), Team.id.asc())
    ).all()
    return AdminUserView(
        **_user_view(user).model_dump(),
        memberships=[
            MembershipView(
                team_id=team.id,
                team_name=team.name,
                role=membership.role,
                status=membership.status,
            )
            for membership, team in rows
        ],
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


def _set_refresh_cookie(response: Response, token: str, settings) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE,
        httponly=True,
        samesite="lax",
        path="/api/v1/auth",
    )


@router.post("/auth/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    email = body.email
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        verify_password(body.password, _DUMMY_PASSWORD_HASH)
        write_audit(
            session,
            action="auth.login.failed",
            resource_type="auth",
            resource_id="login",
            details={"email": email, "reason": "invalid_credentials"},
        )
        session.commit()
        raise ApiError(401, "UNAUTHENTICATED", "Invalid email or password.")
    if not verify_password(body.password, user.password_hash):
        write_audit(
            session,
            action="auth.login.failed",
            resource_type="auth",
            resource_id="login",
            details={"email": email, "reason": "invalid_credentials"},
        )
        session.commit()
        raise ApiError(401, "UNAUTHENTICATED", "Invalid email or password.")

    now = datetime.now(timezone.utc)
    auth_session = AuthSession(
        user_id=user.id,
        refresh_jti=new_ulid(),
        expires_at=now
        + timedelta(seconds=request.app.state.settings.refresh_token_ttl_seconds),
    )
    session.add(auth_session)
    write_audit(
        session,
        action="auth.login.succeeded",
        actor_id=user.id,
        resource_type="user",
        resource_id=user.id,
        details={"email": user.email},
    )
    session.commit()
    tokens = _session_tokens(user, auth_session, request.app.state.settings)
    refresh_token = tokens.pop("refresh_token")
    _set_refresh_cookie(response, refresh_token, request.app.state.settings)
    return envelope(tokens, request.state.request_id)


@router.post("/auth/refresh")
def refresh_token(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    refresh_token = request.cookies.get(_REFRESH_COOKIE)
    if not refresh_token:
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token.")
    try:
        claims = decode_token_claims(
            refresh_token,
            request.app.state.settings,
            expected_type="refresh",
        )
    except TokenError as error:
        _clear_refresh_cookie(response)
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
        _clear_refresh_cookie(response)
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token.")
    user = session.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        _clear_refresh_cookie(response)
        raise ApiError(401, "UNAUTHENTICATED", "User is not active.")

    auth_session.refresh_jti = new_ulid()
    auth_session.expires_at = now + timedelta(
        seconds=request.app.state.settings.refresh_token_ttl_seconds
    )
    session.commit()
    tokens = _session_tokens(user, auth_session, request.app.state.settings)
    rotated_refresh = tokens.pop("refresh_token")
    _set_refresh_cookie(response, rotated_refresh, request.app.state.settings)
    return envelope(tokens, request.state.request_id)


@router.post("/auth/logout", status_code=204)
def logout(
    response: Response,
    context=Depends(get_auth_context),
    session: Session = Depends(get_session),
):
    if context.auth_session is not None:
        context.auth_session.revoked_at = datetime.now(timezone.utc)
        session.commit()
    response.status_code = 204
    _clear_refresh_cookie(response)
    return response


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
        write_audit(
            session,
            action="auth.password.change_failed",
            actor_id=user.id,
            resource_type="user",
            resource_id=user.id,
            details={"reason": "invalid_current_password"},
        )
        session.commit()
        raise ApiError(401, "UNAUTHENTICATED", "Current password is incorrect.")
    user.password_hash = hash_password(body.new_password)
    write_audit(
        session,
        action="auth.password.changed",
        actor_id=user.id,
        resource_type="user",
        resource_id=user.id,
    )
    session.commit()
    return Response(status_code=204)


@router.get("/admin/users")
def admin_list_users(
    request: Request,
    limit: int = 20,
    cursor: Optional[str] = None,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    return paginate_scalars(
        session,
        select(User),
        timestamp_column=User.created_at,
        id_column=User.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda user: _admin_user_view(session, user).model_dump(),
    )


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
        write_audit(
            session,
            action="user.created",
            actor_id=admin.id,
            resource_type="user",
            resource_id=user.id,
            details={"email": user.email, "display_name": user.display_name},
        )
        write_audit(
            session,
            action="team.member.added",
            actor_id=admin.id,
            team_id=team.id,
            resource_type="team_member",
            resource_id=user.id,
            details={"role": membership.role, "status": membership.status},
        )
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


@router.post("/admin/users/update")
def admin_update_user(
    body: AdminUserUpdateRequest,
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    user = session.get(User, body.user_id)
    if user is None:
        raise ApiError(404, "NOT_FOUND", "User was not found.")
    if user.is_builtin:
        raise ApiError(
            403,
            "PROTECTED_ACCOUNT",
            "The built-in administrator cannot be modified.",
        )

    if body.status is not None:
        if body.status == "disabled":
            ensure_user_can_be_disabled(session, user.id)
        user.is_active = body.status == "active"
        write_audit(
            session,
            action="user.enabled" if user.is_active else "user.disabled",
            actor_id=admin.id,
            resource_type="user",
            resource_id=user.id,
            details={"status": body.status, "email": user.email},
        )

    membership = None
    team = None
    if body.team_id is not None and body.role is not None:
        membership = session.get(TeamMember, (body.team_id, user.id))
        team = session.get(Team, body.team_id)
        if membership is None or membership.status != "active" or team is None:
            raise ApiError(404, "NOT_FOUND", "Active team membership was not found.")
        ensure_not_last_active_leader(session, membership, next_role=body.role)
        previous_role = membership.role
        membership.role = body.role
        write_audit(
            session,
            action="team.member.updated",
            actor_id=admin.id,
            team_id=team.id,
            resource_type="team_member",
            resource_id=user.id,
            details={
                "before": {"role": previous_role},
                "after": {"role": membership.role},
            },
        )

    session.commit()
    data = _user_view(user).model_dump()
    if membership is not None and team is not None:
        data["membership"] = MembershipView(
            team_id=team.id,
            team_name=team.name,
            role=membership.role,
            status=membership.status,
        ).model_dump()
    return envelope(data, request.state.request_id)


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
