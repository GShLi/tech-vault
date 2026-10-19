from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend.app.core.ids import new_ulid
from backend.app.core.tokens import create_access_token
from backend.app.db.models import User


def _register(client, email="member@example.com", password="password-123"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "Member"},
    )


def _login(client, email="member@example.com", password="password-123"):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def test_register_login_and_me(api_client):
    registered = _register(api_client)
    assert registered.status_code == 201
    assert registered.json()["data"]["email"] == "member@example.com"
    assert "password_hash" not in registered.json()["data"]

    logged_in = api_client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "password-123"},
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["data"]["access_token"]

    me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )
    assert me.status_code == 200
    assert me.json()["data"]["user"]["display_name"] == "Member"


def test_duplicate_email_and_wrong_password_use_error_envelopes(api_client):
    assert _register(api_client).status_code == 201
    duplicate = _register(api_client)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_RESOURCE"

    wrong = api_client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "wrong-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_requires_a_valid_token(api_client):
    missing = api_client.get("/api/v1/auth/me")
    invalid = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_validation_errors_redact_password_input(api_client):
    response = _register(api_client, password="short")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert "short" not in response.text
    assert all(
        "input" not in validation_error
        for validation_error in response.json()["error"]["details"]["errors"]
    )


def test_register_rejects_whitespace_only_display_name(api_client):
    response = api_client.post(
        "/api/v1/auth/register",
        json={
            "email": "member@example.com",
            "password": "password-123",
            "display_name": "   ",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_register_and_login_normalize_email(api_client):
    registered = api_client.post(
        "/api/v1/auth/register",
        json={
            "email": "  Member@Example.COM ",
            "password": "password-123",
            "display_name": "  Member  ",
        },
    )
    assert registered.status_code == 201
    assert registered.json()["data"]["email"] == "member@example.com"
    assert registered.json()["data"]["display_name"] == "Member"

    logged_in = _login(api_client, email="  Member@Example.COM ")
    assert logged_in.status_code == 200


@pytest.mark.parametrize("email", ["@b.com", "a@b"])
def test_register_rejects_invalid_email_addresses(api_client, email):
    response = _register(api_client, email=email)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_me_rejects_expired_token(api_app, api_client):
    registered = _register(api_client)
    assert registered.status_code == 201
    settings = api_app.state.settings
    expired_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.access_token_ttl_seconds + 1
    )
    token = create_access_token(
        registered.json()["data"]["id"],
        settings,
        now=expired_at,
    )

    response = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_rejects_valid_token_for_unknown_user(api_app, api_client):
    token = create_access_token(new_ulid(), api_app.state.settings)

    response = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_rejects_token_for_inactive_user(api_app, api_client):
    assert _register(api_client).status_code == 201
    logged_in = _login(api_client)
    assert logged_in.status_code == 200
    token = logged_in.json()["data"]["access_token"]

    with api_app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.email == "member@example.com"))
        assert user is not None
        user.is_active = False
        session.commit()

    response = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
