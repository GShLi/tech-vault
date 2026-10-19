from sqlalchemy import select

from backend.app.db.models import TeamMember, User
from backend.tests.api.test_teams import _register_and_login


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


def _add_team_member(api_app, team_id, email):
    with api_app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        session.add(
            TeamMember(
                team_id=team_id,
                user_id=user.id,
                role="member",
                status="active",
            )
        )
        session.commit()


def test_leader_can_create_list_and_archive_kb(api_client):
    headers = _register_and_login(api_client, email="kb-leader@example.com")
    team = _create_team(api_client, headers)

    created = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Java", "description": "JDK notes"},
        headers=headers,
    )
    assert created.status_code == 201
    kb = created.json()["data"]
    assert kb["name"] == "Java"

    listed = api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert [item["id"] for item in listed.json()["data"]] == [kb["id"]]

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


def test_team_member_cannot_create_kb(api_client, api_app):
    leader_headers = _register_and_login(api_client, email="owner@example.com")
    team = _create_team(api_client, leader_headers)
    member_headers = _register_and_login(api_client, email="member@example.com")
    _add_team_member(api_app, team["id"], "member@example.com")

    response = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Forbidden"},
        headers=member_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_team_member_cannot_update_kb(api_client, api_app):
    leader_headers = _register_and_login(api_client, email="update-owner@example.com")
    team = _create_team(api_client, leader_headers)
    kb = _create_kb(api_client, leader_headers, team["id"])
    member_headers = _register_and_login(api_client, email="update-member@example.com")
    _add_team_member(api_app, team["id"], "update-member@example.com")

    response = api_client.post(
        "/api/v1/kbs/update",
        json={"team_id": team["id"], "kb_id": kb["id"], "name": "Forbidden"},
        headers={**member_headers, "If-Match": "1"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_kb_update_requires_leader_and_if_match(api_client):
    leader_headers = _register_and_login(api_client, email="kb-update-leader@example.com")
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

    member_headers = _register_and_login(
        api_client, email="kb-update-member@example.com"
    )
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
    headers = _register_and_login(api_client, email="duplicate-create@example.com")
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
    headers = _register_and_login(api_client, email="duplicate-update@example.com")
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
    headers = _register_and_login(api_client, email="kb-whitespace-create@example.com")
    team = _create_team(api_client, headers)

    response = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "   "},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_kb_update_rejects_whitespace_only_name(api_client):
    headers = _register_and_login(api_client, email="kb-whitespace-update@example.com")
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
    headers = _register_and_login(api_client, email="stale-archive@example.com")
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
    headers = _register_and_login(api_client, email="archived-update@example.com")
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
    headers = _register_and_login(api_client, email="rearchive@example.com")
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
