from backend.tests.api.conftest import ADMIN_EMAIL, ADMIN_PASSWORD
from backend.app.db.models import TeamMember


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


def _make_non_builtin_user_last_active_leader(client, api_app, team, user_id):
    admin_id = client.get(
        "/api/v1/auth/me",
        headers=_admin_headers(client),
    ).json()["data"]["user"]["id"]
    with api_app.state.session_factory() as session:
        admin_membership = session.get(TeamMember, (team["id"], admin_id))
        assert admin_membership is not None
        admin_membership.role = "viewer"
        session.commit()

    leader_headers = _login(client, "last-leader@example.com", "password-123")
    return leader_headers


def test_external_registration_route_does_not_exist(strict_api_client):
    response = strict_api_client.post(
        "/api/v1/auth/register",
        json={
            "email": "external@example.com",
            "password": "password-123",
            "display_name": "External",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


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


def test_admin_can_list_users_with_memberships_and_cursor(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin, name="Directory Team")
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "directory@example.com",
        role="leader",
    )

    members = []
    cursor = None
    for _ in range(20):
        params = {"limit": 1}
        if cursor:
            params["cursor"] = cursor
        response = strict_api_client.get(
            "/api/v1/admin/users",
            params=params,
            headers=admin,
        )
        assert response.status_code == 200, response.text
        page = response.json()
        members.extend(page["data"])
        cursor = page["meta"]["next_cursor"]
        if not cursor:
            break

    listed = next(item for item in members if item["id"] == created["user"]["id"])
    assert listed["email"] == "directory@example.com"
    assert "password_hash" not in listed
    assert listed["memberships"] == [
        {
            "team_id": team["id"],
            "team_name": "Directory Team",
            "role": "leader",
            "status": "active",
        }
    ]

    member = _login(strict_api_client, "directory@example.com", "password-123")
    denied = strict_api_client.get("/api/v1/admin/users", headers=member)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"


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


def test_admin_user_update_requires_user_id_and_a_mutable_field(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "typed-update@example.com",
    )

    missing_user_id = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"status": "disabled"},
        headers=admin,
    )
    missing_change = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": created["user"]["id"]},
        headers=admin,
    )

    assert missing_user_id.status_code == 422
    assert missing_user_id.json()["error"]["code"] == "VALIDATION_FAILED"
    assert missing_change.status_code == 422
    assert missing_change.json()["error"]["code"] == "VALIDATION_FAILED"


def test_admin_can_change_a_users_team_role(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "promoted@example.com",
        role="member",
    )

    response = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={
            "user_id": created["user"]["id"],
            "team_id": team["id"],
            "role": "leader",
        },
        headers=admin,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["membership"]["role"] == "leader"
    member = _login(strict_api_client, "promoted@example.com", "password-123")
    me = strict_api_client.get("/api/v1/auth/me", headers=member)
    assert me.status_code == 200
    assert me.json()["data"]["memberships"][0]["role"] == "leader"


def test_admin_can_disable_and_reenable_a_user(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "disabled-user@example.com",
    )

    disabled = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": created["user"]["id"], "status": "disabled"},
        headers=admin,
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["data"]["status"] == "disabled"
    disabled_login = strict_api_client.post(
        "/api/v1/auth/login",
        json={"email": "disabled-user@example.com", "password": "password-123"},
    )
    assert disabled_login.status_code == 401

    enabled = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": created["user"]["id"], "status": "active"},
        headers=admin,
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["status"] == "active"
    enabled_login = strict_api_client.post(
        "/api/v1/auth/login",
        json={"email": "disabled-user@example.com", "password": "password-123"},
    )
    assert enabled_login.status_code == 200


def test_non_admin_cannot_update_users(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "not-admin@example.com",
    )
    member = _login(strict_api_client, "not-admin@example.com", "password-123")

    response = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": created["user"]["id"], "status": "disabled"},
        headers=member,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_member_update_rejects_invalid_status(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin, name="Member Status Validation")
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "invalid-status@example.com",
    )

    response = strict_api_client.post(
        "/api/v1/members/update",
        json={
            "team_id": team["id"],
            "user_id": created["user"]["id"],
            "status": "not-a-status",
        },
        headers=admin,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_builtin_admin_cannot_be_role_demoted(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    me = strict_api_client.get("/api/v1/auth/me", headers=admin).json()["data"]

    response = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={
            "user_id": me["user"]["id"],
            "team_id": team["id"],
            "role": "viewer",
        },
        headers=admin,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PROTECTED_ACCOUNT"


def test_member_update_cannot_demote_last_active_leader(
    strict_api_client, strict_api_app
):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin, name="Last Leader Update")
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "last-leader@example.com",
        role="leader",
    )
    leader_headers = _make_non_builtin_user_last_active_leader(
        strict_api_client,
        strict_api_app,
        team,
        created["user"]["id"],
    )

    response = strict_api_client.post(
        "/api/v1/members/update",
        json={
            "team_id": team["id"],
            "user_id": created["user"]["id"],
            "role": "member",
        },
        headers=leader_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"


def test_member_remove_cannot_remove_last_active_leader(
    strict_api_client, strict_api_app
):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin, name="Last Leader Remove")
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "last-leader@example.com",
        role="leader",
    )
    leader_headers = _make_non_builtin_user_last_active_leader(
        strict_api_client,
        strict_api_app,
        team,
        created["user"]["id"],
    )

    response = strict_api_client.post(
        "/api/v1/members/remove",
        json={"team_id": team["id"], "user_id": created["user"]["id"]},
        headers=leader_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"


def test_admin_update_cannot_demote_last_active_leader(
    strict_api_client, strict_api_app
):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin, name="Last Leader Admin Update")
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "last-leader@example.com",
        role="leader",
    )
    _make_non_builtin_user_last_active_leader(
        strict_api_client,
        strict_api_app,
        team,
        created["user"]["id"],
    )

    response = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={
            "user_id": created["user"]["id"],
            "team_id": team["id"],
            "role": "member",
        },
        headers=admin,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"


def test_admin_update_cannot_disable_last_active_leader(
    strict_api_client, strict_api_app
):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin, name="Last Leader Disable")
    created = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "last-leader@example.com",
        role="leader",
    )
    _make_non_builtin_user_last_active_leader(
        strict_api_client,
        strict_api_app,
        team,
        created["user"]["id"],
    )

    response = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": created["user"]["id"], "status": "disabled"},
        headers=admin,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"


def test_disabled_leader_does_not_count_toward_last_active_leader(
    strict_api_client, strict_api_app
):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin, name="Disabled Leader Count")
    leader_one = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "leader-one@example.com",
        role="leader",
    )
    leader_two = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "leader-two@example.com",
        role="leader",
    )
    admin_id = strict_api_client.get(
        "/api/v1/auth/me", headers=admin
    ).json()["data"]["user"]["id"]
    with strict_api_app.state.session_factory() as session:
        membership = session.get(TeamMember, (team["id"], admin_id))
        assert membership is not None
        membership.role = "viewer"
        session.commit()

    disabled = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": leader_two["user"]["id"], "status": "disabled"},
        headers=admin,
    )
    assert disabled.status_code == 200, disabled.text

    last_leader = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": leader_one["user"]["id"], "status": "disabled"},
        headers=admin,
    )
    assert last_leader.status_code == 409
    assert last_leader.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"

    demote = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={
            "user_id": leader_one["user"]["id"],
            "team_id": team["id"],
            "role": "member",
        },
        headers=admin,
    )
    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"
