from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from backend.app.core.config import Settings


class TokenError(Exception):
    pass


def create_access_token(
    user_id: str,
    settings: Settings,
    now: Optional[datetime] = None,
) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(
            (issued_at + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "iat", "exp"]},
        )
    except jwt.PyJWTError as error:
        raise TokenError("invalid or expired token") from error

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise TokenError("token subject is missing")
    return subject
