from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from backend.app.core.config import Settings
from backend.app.core.ids import new_ulid


class TokenError(Exception):
    pass


def _encode_token(payload, settings: Settings) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    user_id: str,
    settings: Settings,
    now: Optional[datetime] = None,
    session_id: Optional[str] = None,
    token_version: int = 0,
) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "jti": new_ulid(),
        "typ": "access",
        "ver": token_version,
        "iat": int(issued_at.timestamp()),
        "exp": int(
            (issued_at + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()
        ),
    }
    if session_id is not None:
        payload["sid"] = session_id
    return _encode_token(payload, settings)


def create_refresh_token(
    user_id: str,
    settings: Settings,
    session_id: str,
    refresh_jti: str,
    token_version: int = 0,
    now: Optional[datetime] = None,
) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "sid": session_id,
        "jti": refresh_jti,
        "typ": "refresh",
        "ver": token_version,
        "iat": int(issued_at.timestamp()),
        "exp": int(
            (issued_at + timedelta(seconds=settings.refresh_token_ttl_seconds)).timestamp()
        ),
    }
    return _encode_token(payload, settings)


def decode_token_claims(
    token: str,
    settings: Settings,
    expected_type: Optional[str] = None,
) -> dict:
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
    token_type = payload.get("typ", "access")
    if expected_type is not None and token_type != expected_type:
        raise TokenError("unexpected token type")
    return payload


def decode_access_token(token: str, settings: Settings) -> str:
    payload = decode_token_claims(token, settings, expected_type="access")
    return payload["sub"]
