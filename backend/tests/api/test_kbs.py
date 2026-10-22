from datetime import datetime, timezone

from sqlalchemy import update

from backend.app.db.models import KnowledgeBase
from backend.tests.api.conftest import (
    admin_headers_for,
    create_user_as_admin,
    login_headers,
)


def _create_team(client, headers):
    return client.post(
        "/api/v1/teams/create",
        json={"name": "Platform"},
        headers=headers,
    ).json()["data"]


def _create_kb(client, headers, team_id, name="Java"):
    return client.post(
        "/api/v1/kbs/create",
        json={"team_id": team_id, "name": name},
        headers=headers,
    ).json()["data"]


def test_leader_can_create_list_and_archive_kb(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)

    created = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Java", "description": "JDK notes"},
        headers=headers,
    )
    assert created.status_code == 201
    kb = created.json()["data"]
    assert kb["name"] == "Java"
    assert kb["updated_at"]
    assert kb["default_model_policy_mode"] == "external_allowed"
    assert kb["document_count"] == 0

    listed = api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert [item["id"] for item in listed.json()["data"]] == [kb["id"]]
    assert listed.json()["data"][0]["updated_at"] == kb["updated_at"]
    assert listed.json()["data"][0]["default_model_policy_mode"] == "external_allowed"
    assert listed.json()["data"][0]["document_count"] == 0

    archived = api_client.post(
        "/api/v1/kbs/archive",
        json={"team_id": team["id"], "kb_id": kb["id"]},
        headers={**headers, "If-Match": "1"},
    )
    assert archived.status_code == 202
    assert archived.json()["data"]["status"] == "archived"

    listed_after = api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert listed_after.json()["data"] == []


def test_kb_list_paginates_with_cursor(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)
    kb_ids = [
        _create_kb(api_client, headers, team["id"], name=name)["id"]
        for name in ("Java", "Python", "Rust")
    ]

    first = api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"], "limit": 1},
        headers=headers,
    ).json()
    assert first["meta"]["has_more"] is True
    assert first["meta"]["next_cursor"] is not None

    second = api_client.get(
        "/api/v1/kbs",
        params={
            "team_id": team["id"],
            "limit": 1,
            "cursor": first["meta"]["next_cursor"],
        },
        headers=headers,
    ).json()
    assert second["meta"]["has_more"] is True
    assert second["meta"]["next_cursor"] is not None

    third = api_client.get(
        "/api/v1/kbs",
        params={
            "team_id": team["id"],
            "limit": 1,
            "cursor": second["meta"]["next_cursor"],
        },
        headers=headers,
    ).json()
    assert third["meta"]["has_more"] is False
    assert third["meta"]["next_cursor"] is None

    assert [
        first["data"][0]["id"],
        second["data"][0]["id"],
        third["data"][0]["id"],
    ] == kb_ids[::-1]


def test_kb_list_rejects_invalid_cursor(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)

    response = api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"], "cursor": "not-a-cursor"},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_kb_list_paginates_by_created_at_and_id(api_client, api_app):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)
    kb_ids = [
        _create_kb(api_client, headers, team["id"], name=name)["id"]
        for name in ("Java", "Python", "Rust")
    ]

    same_created_at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    with api_app.state.session_factory() as session:
        session.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id.in_(kb_ids))
            .values(created_at=same_created_at)
        )
        session.commit()

    first = api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"], "limit": 1},
        headers=headers,
    ).json()
    second = api_client.get(
        "/api/v1/kbs",
        params={
            "team_id": team["id"],
            "limit": 1,
            "cursor": first["meta"]["next_cursor"],
        },
        headers=headers,
    ).json()
    third = api_client.get(
        "/api/v1/kbs",
        params={
            "team_id": team["id"],
            "limit": 1,
            "cursor": second["meta"]["next_cursor"],
        },
        headers=headers,
    ).json()

    listed_ids = [
        first["data"][0]["id"],
        second["data"][0]["id"],
        third["data"][0]["id"],
    ]
    assert listed_ids == sorted(kb_ids, reverse=True)
    assert third["meta"]["has_more"] is False
    assert third["meta"]["next_cursor"] is None


def test_team_member_cannot_create_kb(api_client):
    leader_headers = admin_headers_for(api_client)
    team = _create_team(api_client, leader_headers)
    create_user_as_admin(
        api_client,
        leader_headers,
        team["id"],
        "member@example.com",
    )
    member_headers = login_headers(api_client, "member@example.com")

    response = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Forbidden"},
        headers=member_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_team_member_cannot_update_kb(api_client):
    leader_headers = admin_headers_for(api_client)
    team = _create_team(api_client, leader_headers)
    kb = _create_kb(api_client, leader_headers, team["id"])
    create_user_as_admin(
        api_client,
        leader_headers,
        team["id"],
        "update-member@example.com",
    )
    member_headers = login_headers(api_client, "update-member@example.com")

    response = api_client.post(
        "/api/v1/kbs/update",
        json={"team_id": team["id"], "kb_id": kb["id"], "name": "Forbidden"},
        headers={**member_headers, "If-Match": "1"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_kb_update_requires_leader_and_if_match(api_client):
    leader_headers = admin_headers_for(api_client)
    team = _create_team(api_client, leader_headers)
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Java"},
        headers=leader_headers,
    ).json()["data"]

    missing_match = api_client.post(
        "/api/v1/kbs/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "name": "Java 21",
        },
        headers=leader_headers,
    )
    assert missing_match.status_code == 400

    updated = api_client.post(
        "/api/v1/kbs/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "name": "Java 21",
        },
        headers={**leader_headers, "If-Match": "1"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Java 21"
    assert updated.json()["data"]["version"] == 2

    conflict = api_client.post(
        "/api/v1/kbs/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "name": "Java 17",
        },
        headers={**leader_headers, "If-Match": "1"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "VERSION_CONFLICT"

    create_user_as_admin(
        api_client,
        leader_headers,
        team["id"],
        "kb-update-member@example.com",
    )
    member_headers = login_headers(api_client, "kb-update-member@example.com")
    forbidden = api_client.post(
        "/api/v1/kbs/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "name": "Forbidden",
        },
        headers=member_headers,
    )
    assert forbidden.status_code == 403


def test_duplicate_kb_name_on_create_returns_duplicate_resource(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)
    _create_kb(api_client, headers, team["id"], name="Java")

    response = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Java"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_RESOURCE"


def test_duplicate_kb_name_on_update_returns_duplicate_resource(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)
    _create_kb(api_client, headers, team["id"], name="Java")
    kb = _create_kb(api_client, headers, team["id"], name="Python")

    response = api_client.post(
        "/api/v1/kbs/update",
        json={"team_id": team["id"], "kb_id": kb["id"], "name": "Java"},
        headers={**headers, "If-Match": "1"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DUPLICATE_RESOURCE"


def test_kb_create_rejects_whitespace_only_name(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)

    response = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "   "},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_kb_update_rejects_whitespace_only_name(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)
    kb = _create_kb(api_client, headers, team["id"])

    response = api_client.post(
        "/api/v1/kbs/update",
        json={"team_id": team["id"], "kb_id": kb["id"], "name": "   "},
        headers={**headers, "If-Match": "1"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_kb_archive_rejects_stale_if_match(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)
    kb = _create_kb(api_client, headers, team["id"])
    updated = api_client.post(
        "/api/v1/kbs/update",
        json={"team_id": team["id"], "kb_id": kb["id"], "name": "Java 21"},
        headers={**headers, "If-Match": "1"},
    )
    assert updated.status_code == 200

    response = api_client.post(
        "/api/v1/kbs/archive",
        json={"team_id": team["id"], "kb_id": kb["id"]},
        headers={**headers, "If-Match": "1"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VERSION_CONFLICT"


def test_archived_kb_cannot_be_updated(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)
    kb = _create_kb(api_client, headers, team["id"])
    archived = api_client.post(
        "/api/v1/kbs/archive",
        json={"team_id": team["id"], "kb_id": kb["id"]},
        headers={**headers, "If-Match": "1"},
    )
    assert archived.status_code == 202

    response = api_client.post(
        "/api/v1/kbs/update",
        json={"team_id": team["id"], "kb_id": kb["id"], "name": "Mutable"},
        headers={**headers, "If-Match": "2"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"


def test_archived_kb_cannot_be_rearchived(api_client):
    headers = admin_headers_for(api_client)
    team = _create_team(api_client, headers)
    kb = _create_kb(api_client, headers, team["id"])
    archived = api_client.post(
        "/api/v1/kbs/archive",
        json={"team_id": team["id"], "kb_id": kb["id"]},
        headers={**headers, "If-Match": "1"},
    )
    assert archived.status_code == 202

    response = api_client.post(
        "/api/v1/kbs/archive",
        json={"team_id": team["id"], "kb_id": kb["id"]},
        headers={**headers, "If-Match": "2"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"
