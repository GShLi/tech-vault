from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator, Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError
from backend.app.core.tokens import TokenError, decode_token_claims
from backend.app.db.models import AuthSession, User


bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticationContext:
    user: User
    auth_session: Optional[AuthSession]


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


def get_auth_context(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    session: Session = Depends(get_session),
) -> AuthenticationContext:
    if credentials is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication is required.")
    try:
        claims = decode_token_claims(
            credentials.credentials,
            request.app.state.settings,
            expected_type="access",
        )
    except TokenError as error:
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token.") from error

    auth_session = None
    session_id = claims.get("sid")
    if session_id is not None:
        auth_session = session.get(AuthSession, session_id)
        if (
            auth_session is None
            or auth_session.user_id != claims["sub"]
            or auth_session.revoked_at is not None
            or auth_session.expires_at <= datetime.now(timezone.utc)
        ):
            raise ApiError(401, "UNAUTHENTICATED", "Session is no longer active.")

    user = session.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise ApiError(401, "UNAUTHENTICATED", "User is not active.")
    return AuthenticationContext(user=user, auth_session=auth_session)


def get_current_user(
    context: AuthenticationContext = Depends(get_auth_context),
) -> User:
    return context.user


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_super_admin:
        raise ApiError(
            403,
            "PERMISSION_DENIED",
            "Platform administrator permission is required.",
        )
    return user
