from backend.tests.api.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def _login(client, email, password):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}


def _admin_headers(client):
    return _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)


def _create_team(client, headers, name="Platform"):
    response = client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _create_user(client, headers, team_id, email, role="member"):
    response = client.post(
        "/api/v1/admin/users/create",
        json={
            "email": email,
            "display_name": "Created User",
            "password": "password-123",
            "team_id": team_id,
            "role": role,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_external_registration_is_disabled(strict_api_client):
    response = strict_api_client.post(
        "/api/v1/auth/register",
        json={
            "email": "external@example.com",
            "password": "password-123",
            "display_name": "External",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "REGISTRATION_DISABLED"


def test_builtin_admin_can_login_and_is_marked_super_admin(strict_api_client):
    headers = _admin_headers(strict_api_client)
    me = strict_api_client.get("/api/v1/auth/me", headers=headers)

    assert me.status_code == 200
    body = me.json()["data"]
    assert body["user"]["is_super_admin"] is True
    assert body["user"]["is_builtin"] is True


def test_only_admin_can_create_teams_and_users(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "member@example.com",
        role="member",
    )

    member = _login(strict_api_client, "member@example.com", "password-123")
    member_me = strict_api_client.get("/api/v1/auth/me", headers=member)
    assert member_me.json()["data"]["memberships"][0]["role"] == "member"

    denied_team = strict_api_client.post(
        "/api/v1/teams/create",
        json={"name": "Forbidden"},
        headers=member,
    )
    assert denied_team.status_code == 403

    denied_user = strict_api_client.post(
        "/api/v1/admin/users/create",
        json={
            "email": "another@example.com",
            "display_name": "Another",
            "password": "password-123",
            "team_id": team["id"],
            "role": "viewer",
        },
        headers=member,
    )
    assert denied_user.status_code == 403
    assert created["user"]["email"] == "member@example.com"


def test_user_can_change_own_password(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    _create_user(strict_api_client, admin, team["id"], "changeme@example.com")
    member = _login(strict_api_client, "changeme@example.com", "password-123")

    changed = strict_api_client.post(
        "/api/v1/auth/password/change",
        json={"old_password": "password-123", "new_password": "new-password-456"},
        headers=member,
    )
    assert changed.status_code == 204

    old_login = strict_api_client.post(
        "/api/v1/auth/login",
        json={"email": "changeme@example.com", "password": "password-123"},
    )
    new_login = strict_api_client.post(
        "/api/v1/auth/login",
        json={"email": "changeme@example.com", "password": "new-password-456"},
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_builtin_admin_cannot_be_removed_or_demoted(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    me = strict_api_client.get("/api/v1/auth/me", headers=admin).json()["data"]
    admin_id = me["user"]["id"]

    remove = strict_api_client.post(
        "/api/v1/members/remove",
        json={"team_id": team["id"], "user_id": admin_id},
        headers=admin,
    )
    assert remove.status_code == 403
    assert remove.json()["error"]["code"] == "PROTECTED_ACCOUNT"

    demote = strict_api_client.post(
        "/api/v1/members/update",
        json={"team_id": team["id"], "user_id": admin_id, "role": "viewer"},
        headers=admin,
    )
    assert demote.status_code == 403
    assert demote.json()["error"]["code"] == "PROTECTED_ACCOUNT"


def test_admin_can_change_own_password(strict_api_client):
    admin = _admin_headers(strict_api_client)
    response = strict_api_client.post(
        "/api/v1/auth/password/change",
        json={"old_password": ADMIN_PASSWORD, "new_password": "admin-new-password"},
        headers=admin,
    )
    assert response.status_code == 204

    old_login = strict_api_client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    new_login = strict_api_client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": "admin-new-password"},
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200
