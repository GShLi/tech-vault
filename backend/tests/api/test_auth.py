from datetime import datetime, timedelta, timezone

import pytest

import backend.app.api.v1.auth as auth_module
from backend.app.core.ids import new_ulid
from backend.app.core.tokens import create_access_token
from backend.tests.api.conftest import (
    admin_headers_for,
    create_team_as_admin,
    create_user_as_admin,
)


def _login(client, email="member@example.com", password="password-123"):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def _provision_member(client, email="member@example.com", display_name="Member"):
    admin = admin_headers_for(client)
    team = create_team_as_admin(client, admin)
    created = create_user_as_admin(
        client,
        admin,
        team["id"],
        email,
        display_name=display_name,
    )
    return admin, team, created


def test_admin_created_user_can_login_and_read_me(api_client):
    _, _, created = _provision_member(api_client)

    assert created["user"]["email"] == "member@example.com"
    assert created["user"]["status"] == "active"
    assert "is_active" not in created["user"]
    assert "password_hash" not in created["user"]

    logged_in = _login(api_client)
    assert logged_in.status_code == 200
    token = logged_in.json()["data"]["access_token"]

    me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )
    assert me.status_code == 200
    assert me.json()["data"]["user"]["display_name"] == "Member"
    assert me.json()["data"]["user"]["status"] == "active"
    assert "is_active" not in me.json()["data"]["user"]


def test_duplicate_email_and_wrong_password_use_error_envelopes(api_client):
    admin, team, _ = _provision_member(api_client)

    duplicate = api_client.post(
        "/api/v1/admin/users/create",
        json={
            "email": "member@example.com",
            "display_name": "Member",
            "password": "password-123",
            "team_id": team["id"],
            "role": "member",
        },
        headers=admin,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_RESOURCE"

    wrong = _login(api_client, password="wrong-password")
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "UNAUTHENTICATED"


def test_login_uses_dummy_password_verification_for_unknown_and_inactive_users(
    api_client, monkeypatch
):
    admin, _, created = _provision_member(api_client)
    disabled = api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": created["user"]["id"], "status": "disabled"},
        headers=admin,
    )
    assert disabled.status_code == 200, disabled.text

    verification_calls = []

    def record_verification(password, password_hash):
        verification_calls.append((password, password_hash))
        return False

    monkeypatch.setattr(auth_module, "verify_password", record_verification)

    unknown = _login(api_client, email="missing@example.com")
    assert unknown.status_code == 401
    inactive = _login(api_client)
    assert inactive.status_code == 401

    assert verification_calls == [
        ("password-123", auth_module._DUMMY_PASSWORD_HASH),
        ("password-123", auth_module._DUMMY_PASSWORD_HASH),
    ]


def test_me_requires_a_valid_token(api_client):
    missing = api_client.get("/api/v1/auth/me")
    invalid = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_validation_errors_redact_password_input(api_client):
    admin = admin_headers_for(api_client)
    team = create_team_as_admin(api_client, admin)
    response = api_client.post(
        "/api/v1/admin/users/create",
        json={
            "email": "member@example.com",
            "display_name": "Member",
            "password": "short",
            "team_id": team["id"],
            "role": "member",
        },
        headers=admin,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert "short" not in response.text
    assert all(
        "input" not in validation_error
        for validation_error in response.json()["error"]["details"]["errors"]
    )


def test_admin_user_create_rejects_whitespace_only_display_name(api_client):
    admin = admin_headers_for(api_client)
    team = create_team_as_admin(api_client, admin)
    response = api_client.post(
        "/api/v1/admin/users/create",
        json={
            "email": "member@example.com",
            "password": "password-123",
            "display_name": "   ",
            "team_id": team["id"],
            "role": "member",
        },
        headers=admin,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_admin_user_create_and_login_normalize_email(api_client):
    admin = admin_headers_for(api_client)
    team = create_team_as_admin(api_client, admin)
    created = api_client.post(
        "/api/v1/admin/users/create",
        json={
            "email": "  Member@Example.COM ",
            "password": "password-123",
            "display_name": "  Member  ",
            "team_id": team["id"],
            "role": "member",
        },
        headers=admin,
    )
    assert created.status_code == 201
    assert created.json()["data"]["user"]["email"] == "member@example.com"
    assert created.json()["data"]["user"]["display_name"] == "Member"

    logged_in = _login(api_client, email="  Member@Example.COM ")
    assert logged_in.status_code == 200


@pytest.mark.parametrize("email", ["@b.com", "a@b"])
def test_admin_user_create_rejects_invalid_email_addresses(api_client, email):
    admin = admin_headers_for(api_client)
    team = create_team_as_admin(api_client, admin)
    response = api_client.post(
        "/api/v1/admin/users/create",
        json={
            "email": email,
            "display_name": "Member",
            "password": "password-123",
            "team_id": team["id"],
            "role": "member",
        },
        headers=admin,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_me_rejects_expired_token(api_app, api_client):
    _, _, created = _provision_member(api_client)
    settings = api_app.state.settings
    expired_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.access_token_ttl_seconds + 1
    )
    token = create_access_token(
        created["user"]["id"],
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
    admin, _, created = _provision_member(api_client)
    logged_in = _login(api_client)
    assert logged_in.status_code == 200
    token = logged_in.json()["data"]["access_token"]
    disabled = api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": created["user"]["id"], "status": "disabled"},
        headers=admin,
    )
    assert disabled.status_code == 200, disabled.text

    response = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_refresh_rotates_session_and_logout_revokes_all_session_tokens(api_client):
    _provision_member(api_client)
    login_response = _login(api_client)
    logged_in = login_response.json()["data"]
    assert "refresh_token" not in logged_in
    set_cookie = login_response.headers["set-cookie"].lower()
    assert "techvault_refresh=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    original_refresh = api_client.cookies.get("techvault_refresh")
    assert original_refresh

    refreshed = api_client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    rotated = refreshed.json()["data"]
    assert rotated["access_token"] != logged_in["access_token"]
    assert "refresh_token" not in rotated
    rotated_refresh = api_client.cookies.get("techvault_refresh")
    assert rotated_refresh and rotated_refresh != original_refresh

    reused = api_client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": "techvault_refresh=" + original_refresh},
    )
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "UNAUTHENTICATED"

    current_access = rotated["access_token"]
    assert (
        api_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer " + current_access},
        ).status_code
        == 200
    )

    logout = api_client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"Authorization": "Bearer " + current_access},
    )
    assert logout.status_code == 204
    assert (
        api_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer " + current_access},
        ).status_code
        == 401
    )
    assert api_client.post("/api/v1/auth/refresh").status_code == 401
    assert api_client.cookies.get("techvault_refresh") is None


def test_secure_refresh_cookie_is_enabled_outside_development(strict_api_client):
    login = strict_api_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@techvault.local", "password": "ChangeMe-123!"},
    )

    assert login.status_code == 200
    set_cookie = login.headers["set-cookie"].lower()
    assert "techvault_refresh=" in set_cookie
    assert "secure" in set_cookie


def test_user_can_update_own_display_name(api_client):
    _provision_member(api_client)
    token = _login(api_client).json()["data"]["access_token"]

    updated = api_client.post(
        "/api/v1/users/update",
        json={"display_name": "  Updated Member  "},
        headers={"Authorization": "Bearer " + token},
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["display_name"] == "Updated Member"
    me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )
    assert me.json()["data"]["user"]["display_name"] == "Updated Member"
