from datetime import datetime, timedelta, timezone

import pytest

from backend.app.core.config import Settings
from backend.app.core.tokens import TokenError, create_access_token, decode_access_token


def test_access_token_round_trips_subject():
    settings = Settings(jwt_secret="test-secret", access_token_ttl_seconds=60)
    token = create_access_token("user-1", settings)

    assert decode_access_token(token, settings) == "user-1"


def test_expired_access_token_is_rejected():
    settings = Settings(jwt_secret="test-secret", access_token_ttl_seconds=60)
    issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = create_access_token("user-1", settings, now=issued_at)

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_wrong_secret_is_rejected():
    issued = Settings(jwt_secret="first-secret")
    verifier = Settings(jwt_secret="second-secret")
    token = create_access_token("user-1", issued)

    with pytest.raises(TokenError):
        decode_access_token(token, verifier)
