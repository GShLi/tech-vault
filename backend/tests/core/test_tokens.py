from datetime import datetime, timezone

import jwt
import pytest

from backend.app.core.config import Settings
from backend.app.core.tokens import TokenError, create_access_token, decode_access_token


_JWT_SECRET = "test-secret-0123456789abcdef0123456789abcdef"


def test_access_token_round_trips_subject():
    settings = Settings(
        environment="test",
        jwt_secret=_JWT_SECRET,
        access_token_ttl_seconds=60,
    )
    token = create_access_token("user-1", settings)

    assert decode_access_token(token, settings) == "user-1"


def test_expired_access_token_is_rejected():
    settings = Settings(
        environment="test",
        jwt_secret=_JWT_SECRET,
        access_token_ttl_seconds=60,
    )
    issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = create_access_token("user-1", settings, now=issued_at)

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_wrong_secret_is_rejected():
    issued = Settings(environment="test", jwt_secret=_JWT_SECRET)
    verifier = Settings(environment="test", jwt_secret=_JWT_SECRET + "-different")
    token = create_access_token("user-1", issued)

    with pytest.raises(TokenError):
        decode_access_token(token, verifier)


def test_tampered_access_token_is_rejected():
    settings = Settings(environment="test", jwt_secret=_JWT_SECRET)
    header, payload, signature = create_access_token("user-1", settings).split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered = ".".join((header, payload, replacement + signature[1:]))

    with pytest.raises(TokenError):
        decode_access_token(tampered, settings)


def test_access_token_with_missing_subject_is_rejected():
    settings = Settings(environment="test", jwt_secret=_JWT_SECRET)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + 60,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_access_token_with_missing_expiration_is_rejected():
    settings = Settings(environment="test", jwt_secret=_JWT_SECRET)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "user-1",
            "iat": int(now.timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_access_token_with_missing_issued_at_is_rejected():
    settings = Settings(environment="test", jwt_secret=_JWT_SECRET)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "user-1",
            "exp": int(now.timestamp()) + 60,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(TokenError):
        decode_access_token(token, settings)
