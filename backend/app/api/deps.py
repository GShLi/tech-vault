from typing import Iterator, Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError
from backend.app.core.tokens import TokenError, decode_access_token
from backend.app.db.models import User


bearer = HTTPBearer(auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication is required.")
    try:
        user_id = decode_access_token(
            credentials.credentials,
            request.app.state.settings,
        )
    except TokenError as error:
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token.") from error

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "UNAUTHENTICATED", "User is not active.")
    return user


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_super_admin:
        raise ApiError(
            403,
            "PERMISSION_DENIED",
            "Platform administrator permission is required.",
        )
    return user
