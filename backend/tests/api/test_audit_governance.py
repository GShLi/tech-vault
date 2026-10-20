import json

from sqlalchemy import inspect, text
from sqlalchemy import select

from backend.app.db.models import AuditLog
from backend.app.db.session import build_engine, create_schema
from backend.tests.api.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def _login(client, email, password):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def _admin_headers(client):
    response = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}


def _create_team(client, headers, name="Platform"):
    response = client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _create_user(client, headers, team_id, email="member@example.com"):
    response = client.post(
        "/api/v1/admin/users/create",
        json={
            "email": email,
            "display_name": "Governance User",
            "password": "password-123",
            "team_id": team_id,
            "role": "member",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _audit_rows(app):
    with app.state.session_factory() as session:
        return list(
            session.scalars(
                select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            ).all()
        )


def _row_for(rows, action):
    matches = [row for row in rows if row.action == action]
    assert len(matches) == 1, [row.action for row in rows]
    return matches[0]


def _rows_for(rows, action):
    matches = [row for row in rows if row.action == action]
    assert matches, [row.action for row in rows]
    return matches


def test_create_schema_relaxes_legacy_audit_scope_columns():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE audit_logs ("
                "id VARCHAR(26) PRIMARY KEY, "
                "team_id VARCHAR(26) NOT NULL, "
                "actor_id VARCHAR(26) NOT NULL, "
                "action VARCHAR(80) NOT NULL, "
                "resource_type VARCHAR(40) NOT NULL, "
                "resource_id VARCHAR(80), "
                "details TEXT NOT NULL, "
                "created_at DATETIME NOT NULL"
                ")"
            )
        )

    create_schema(engine)

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("audit_logs")
    }
    assert columns["team_id"]["nullable"] is True
    assert columns["actor_id"]["nullable"] is True


def test_login_audits_are_deployment_level_and_redact_credentials(
    strict_api_client, strict_api_app
):
    admin_headers = _admin_headers(strict_api_client)
    _create_team(strict_api_client, admin_headers, name="Earliest Team")

    failed = _login(strict_api_client, ADMIN_EMAIL, "wrong-login-secret")
    unknown = _login(strict_api_client, "missing@example.com", "unknown-login-secret")

    assert failed.status_code == 401
    assert unknown.status_code == 401

    rows = _audit_rows(strict_api_app)
    succeeded = _row_for(rows, "auth.login.succeeded")
    failed_rows = _rows_for(rows, "auth.login.failed")

    assert succeeded.team_id is None
    assert succeeded.actor_id is not None
    assert len(failed_rows) == 2
    assert all(row.team_id is None for row in failed_rows)
    assert all(row.actor_id is None for row in failed_rows)
    all_details = json.dumps([row.details for row in rows])
    assert "wrong-login-secret" not in all_details
    assert "unknown-login-secret" not in all_details
    assert ADMIN_PASSWORD not in all_details


def test_auth_and_user_administration_audits_redact_sensitive_fields(
    strict_api_client, strict_api_app
):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    created = _create_user(strict_api_client, admin, team["id"])
    member_login = _login(strict_api_client, "member@example.com", "password-123")
    assert member_login.status_code == 200
    member_headers = {
        "Authorization": "Bearer " + member_login.json()["data"]["access_token"]
    }

    changed = strict_api_client.post(
        "/api/v1/auth/password/change",
        json={"old_password": "password-123", "new_password": "new-password-456"},
        headers=member_headers,
    )
    assert changed.status_code == 204, changed.text

    rows = _audit_rows(strict_api_app)
    user_created = _row_for(rows, "user.created")
    member_added = _row_for(rows, "team.member.added")
    password_changed = _row_for(rows, "auth.password.changed")

    assert user_created.team_id is None
    assert user_created.resource_id == created["user"]["id"]
    assert member_added.team_id == team["id"]
    assert member_added.resource_id == created["user"]["id"]
    assert password_changed.team_id is None

    serialized_details = json.dumps([row.details for row in rows])
    for secret in (
        "password-123",
        "new-password-456",
        "password_hash",
        "access_token",
        "Bearer",
    ):
        assert secret not in serialized_details


def test_super_admin_can_disable_user_without_storing_credentials(
    strict_api_client, strict_api_app
):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    created = _create_user(strict_api_client, admin, team["id"])
    response = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": created["user"]["id"], "status": "disabled"},
        headers=admin,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "disabled"
    assert _login(strict_api_client, "member@example.com", "password-123").status_code == 401

    rows = _audit_rows(strict_api_app)
    disabled = _row_for(rows, "user.disabled")
    assert disabled.team_id is None
    assert disabled.actor_id is not None
    assert disabled.resource_id == created["user"]["id"]
    assert "password" not in disabled.details.lower()

    me = strict_api_client.get("/api/v1/auth/me", headers=admin)
    assert me.status_code == 200
    protected = strict_api_client.post(
        "/api/v1/admin/users/update",
        json={"user_id": me.json()["data"]["user"]["id"], "status": "disabled"},
        headers=admin,
    )
    assert protected.status_code == 403
    assert protected.json()["error"]["code"] == "PROTECTED_ACCOUNT"


def test_only_super_admin_can_list_and_read_global_audit(strict_api_client):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    _create_user(strict_api_client, admin, team["id"])
    member_login = _login(strict_api_client, "member@example.com", "password-123")
    member = {"Authorization": "Bearer " + member_login.json()["data"]["access_token"]}

    first = strict_api_client.get(
        "/api/v1/admin/audit",
        params={"limit": 1},
        headers=admin,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["data"]) == 1
    assert first_body["meta"]["has_more"] is True
    assert first_body["meta"]["next_cursor"] is not None
    audit_id = first_body["data"][0]["id"]

    second = strict_api_client.get(
        "/api/v1/admin/audit",
        params={"limit": 100, "cursor": first_body["meta"]["next_cursor"]},
        headers=admin,
    )
    assert second.status_code == 200, second.text
    assert all(
        item["team_id"] is None or isinstance(item["team_id"], str)
        for item in second.json()["data"]
    )

    denied_list = strict_api_client.get("/api/v1/admin/audit", headers=member)
    assert denied_list.status_code == 403

    detail = strict_api_client.get(
        "/api/v1/admin/audit/detail",
        params={"audit_id": audit_id},
        headers=admin,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["id"] == audit_id
    assert isinstance(detail.json()["data"]["details"], dict)

    denied_detail = strict_api_client.get(
        "/api/v1/admin/audit/detail",
        params={"audit_id": audit_id},
        headers=member,
    )
    assert denied_detail.status_code == 403

    missing = strict_api_client.get(
        "/api/v1/admin/audit/detail",
        params={"audit_id": "01J00000000000000000000000"},
        headers=admin,
    )
    assert missing.status_code == 404


def test_team_audit_remains_team_scoped_and_member_mutations_are_audited(
    strict_api_client, strict_api_app
):
    admin = _admin_headers(strict_api_client)
    team = _create_team(strict_api_client, admin)
    created = _create_user(strict_api_client, admin, team["id"])

    updated = strict_api_client.post(
        "/api/v1/members/update",
        json={"team_id": team["id"], "user_id": created["user"]["id"], "role": "viewer"},
        headers=admin,
    )
    assert updated.status_code == 200, updated.text
    removed = strict_api_client.post(
        "/api/v1/members/remove",
        json={"team_id": team["id"], "user_id": created["user"]["id"]},
        headers=admin,
    )
    assert removed.status_code == 200, removed.text

    page = strict_api_client.get(
        "/api/v1/audit",
        params={"team_id": team["id"], "limit": 100},
        headers=admin,
    )
    assert page.status_code == 200, page.text
    actions = [item["action"] for item in page.json()["data"]]
    assert "auth.login.succeeded" not in actions
    assert "team.created" in actions
    assert "team.member.added" in actions
    assert "team.member.updated" in actions
    assert "team.member.removed" in actions
    assert all(item["team_id"] == team["id"] for item in page.json()["data"])

    updated_row = _row_for(_audit_rows(strict_api_app), "team.member.updated")
    details = json.loads(updated_row.details)
    assert details["before"]["role"] == "member"
    assert details["after"]["role"] == "viewer"
    assert "password" not in updated_row.details.lower()


def test_team_audit_detail_rejects_records_from_other_teams(
    strict_api_client, strict_api_app
):
    admin = _admin_headers(strict_api_client)
    first_team = _create_team(strict_api_client, admin, name="First")
    second_team = _create_team(strict_api_client, admin, name="Second")
    first_row = next(
        row
        for row in _audit_rows(strict_api_app)
        if row.action == "team.created" and row.team_id == first_team["id"]
    )

    response = strict_api_client.get(
        "/api/v1/audit/detail",
        params={"team_id": second_team["id"], "audit_id": first_row.id},
        headers=admin,
    )
    assert response.status_code == 404

    own = strict_api_client.get(
        "/api/v1/audit/detail",
        params={"team_id": first_team["id"], "audit_id": first_row.id},
        headers=admin,
    )
    assert own.status_code == 200, own.text
