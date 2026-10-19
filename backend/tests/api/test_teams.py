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
        json={"name": "Platform"},
        headers=headers,
    )
    assert created.status_code == 201
    team = created.json()["data"]
    assert team["name"] == "Platform"
    assert team["version"] == 1

    listed = api_client.get("/api/v1/teams", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [team["id"]]

    detail = api_client.get(
        "/api/v1/teams/detail",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == team["id"]


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
        json={"team_id": team["id"], "name": "Renamed"},
        headers={**headers, "If-Match": "1"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Renamed"
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
