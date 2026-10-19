from backend.tests.api.test_teams import _register_and_login


def _create_team(client, headers):
    return client.post(
        "/api/v1/teams/create",
        json={"name": "Platform"},
        headers=headers,
    ).json()["data"]


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


def test_non_leader_cannot_create_kb(api_client):
    leader_headers = _register_and_login(api_client, email="owner@example.com")
    team = _create_team(api_client, leader_headers)
    member_headers = _register_and_login(api_client, email="member@example.com")

    response = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Forbidden"},
        headers=member_headers,
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
