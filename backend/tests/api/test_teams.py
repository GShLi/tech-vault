from datetime import datetime, timezone

from sqlalchemy import update

from backend.app.db.models import Team


def _register_and_login(client, email="leader@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password-123", "display_name": "Leader"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password-123"},
    )
    token = login.json()["data"]["access_token"]
    return {"Authorization": "Bearer " + token}


def test_team_create_list_and_detail(api_client):
    headers = _register_and_login(api_client)
    created = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Platform", "description": "Platform engineering"},
        headers=headers,
    )
    assert created.status_code == 201
    team = created.json()["data"]
    assert team["name"] == "Platform"
    assert team["description"] == "Platform engineering"
    assert team["role"] == "leader"
    assert team["version"] == 1

    listed = api_client.get("/api/v1/teams", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [team["id"]]
    assert listed.json()["data"][0]["description"] == "Platform engineering"
    assert listed.json()["data"][0]["role"] == "leader"

    detail = api_client.get(
        "/api/v1/teams/detail",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == team["id"]
    assert detail.json()["data"]["description"] == "Platform engineering"
    assert detail.json()["data"]["role"] == "leader"


def test_team_list_paginates_by_created_at_and_id(api_client, api_app):
    headers = _register_and_login(api_client, email="team-pages@example.com")
    team_ids = []
    for name in ("One", "Two", "Three"):
        response = api_client.post(
            "/api/v1/teams/create",
            json={"name": name},
            headers=headers,
        )
        assert response.status_code == 201
        team_ids.append(response.json()["data"]["id"])

    same_created_at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    with api_app.state.session_factory() as session:
        session.execute(
            update(Team)
            .where(Team.id.in_(team_ids))
            .values(created_at=same_created_at)
        )
        session.commit()

    first = api_client.get(
        "/api/v1/teams",
        params={"limit": 1},
        headers=headers,
    ).json()
    assert first["meta"]["has_more"] is True
    assert first["meta"]["next_cursor"] is not None

    second = api_client.get(
        "/api/v1/teams",
        params={"limit": 1, "cursor": first["meta"]["next_cursor"]},
        headers=headers,
    ).json()
    assert second["meta"]["has_more"] is True
    assert second["meta"]["next_cursor"] is not None

    third = api_client.get(
        "/api/v1/teams",
        params={"limit": 1, "cursor": second["meta"]["next_cursor"]},
        headers=headers,
    ).json()
    assert third["meta"]["has_more"] is False
    assert third["meta"]["next_cursor"] is None

    listed_ids = [
        first["data"][0]["id"],
        second["data"][0]["id"],
        third["data"][0]["id"],
    ]
    assert listed_ids == sorted(team_ids, reverse=True)


def test_team_list_rejects_invalid_cursor(api_client):
    headers = _register_and_login(api_client, email="team-cursor@example.com")

    response = api_client.get(
        "/api/v1/teams",
        params={"cursor": "not-a-cursor"},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_team_update_requires_leader_and_if_match(api_client):
    headers = _register_and_login(api_client)
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Platform"},
        headers=headers,
    ).json()["data"]

    missing_match = api_client.post(
        "/api/v1/teams/update",
        json={"team_id": team["id"], "name": "Renamed"},
        headers=headers,
    )
    assert missing_match.status_code == 400

    updated = api_client.post(
        "/api/v1/teams/update",
        json={
            "team_id": team["id"],
            "name": "Renamed",
            "description": "Updated description",
        },
        headers={**headers, "If-Match": "1"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Renamed"
    assert updated.json()["data"]["description"] == "Updated description"
    assert updated.json()["data"]["role"] == "leader"
    assert updated.json()["data"]["version"] == 2

    conflict = api_client.post(
        "/api/v1/teams/update",
        json={"team_id": team["id"], "name": "Again"},
        headers={**headers, "If-Match": "1"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "VERSION_CONFLICT"


def test_team_update_accepts_quoted_if_match(api_client):
    headers = _register_and_login(api_client, email="quoted-if-match@example.com")
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Platform"},
        headers=headers,
    ).json()["data"]

    response = api_client.post(
        "/api/v1/teams/update",
        json={"team_id": team["id"], "name": "Quoted Match"},
        headers={**headers, "If-Match": '"1"'},
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Quoted Match"
    assert response.json()["data"]["version"] == 2


def test_team_create_rejects_whitespace_only_name(api_client):
    headers = _register_and_login(api_client, email="whitespace-create@example.com")

    response = api_client.post(
        "/api/v1/teams/create",
        json={"name": "   "},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_team_update_rejects_whitespace_only_name(api_client):
    headers = _register_and_login(api_client, email="whitespace-update@example.com")
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Platform"},
        headers=headers,
    ).json()["data"]

    response = api_client.post(
        "/api/v1/teams/update",
        json={"team_id": team["id"], "name": "   "},
        headers={**headers, "If-Match": "1"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
