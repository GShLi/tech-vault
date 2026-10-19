from backend.tests.api.conftest import ADMIN_EMAIL, ADMIN_PASSWORD


def _login(client, email, password="password-123"):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}


def _create_user(client, admin_headers, team_id, email, role="member"):
    response = client.post(
        "/api/v1/admin/users/create",
        json={
            "email": email,
            "display_name": email.split("@")[0].title(),
            "password": "password-123",
            "team_id": team_id,
            "role": role,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["user"]


def _create_team_and_kb(client, headers, suffix):
    team = client.post(
        "/api/v1/teams/create",
        json={"name": "Archive Scope " + suffix},
        headers=headers,
    ).json()["data"]
    kb = client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Archive Scope KB " + suffix},
        headers=headers,
    ).json()["data"]
    return team, kb


def test_archived_kb_is_not_available_to_document_source_or_chat_paths(
    strict_api_client,
):
    admin = _login(strict_api_client, ADMIN_EMAIL, ADMIN_PASSWORD)
    team_id = strict_api_client.post(
        "/api/v1/teams/create",
        json={"name": "Archive Scope Team"},
        headers=admin,
    ).json()["data"]["id"]
    kb = strict_api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team_id, "name": "Archived KB"},
        headers=admin,
    ).json()["data"]
    source = strict_api_client.post(
        "/api/v1/sources/github/create",
        json={
            "team_id": team_id,
            "kb_id": kb["id"],
            "repo_url": "https://github.com/acme/archive.git",
            "branch": "main",
            "path_filters": ["docs/"],
        },
        headers=admin,
    ).json()["data"]
    chat = strict_api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team_id, "knowledge_base_ids": [kb["id"]]},
        headers=admin,
    ).json()["data"]

    archived = strict_api_client.post(
        "/api/v1/kbs/archive",
        json={"team_id": team_id, "kb_id": kb["id"]},
        headers={**admin, "If-Match": str(kb["version"])},
    )
    assert archived.status_code == 202, archived.text

    checks = [
        strict_api_client.get(
            "/api/v1/kbs/detail",
            params={"team_id": team_id, "kb_id": kb["id"]},
            headers=admin,
        ),
        strict_api_client.get(
            "/api/v1/docs",
            params={"team_id": team_id, "kb_id": kb["id"]},
            headers=admin,
        ),
        strict_api_client.get(
            "/api/v1/sources",
            params={"team_id": team_id, "kb_id": kb["id"]},
            headers=admin,
        ),
        strict_api_client.get(
            "/api/v1/sources/detail",
            params={"team_id": team_id, "source_id": source["id"]},
            headers=admin,
        ),
        strict_api_client.post(
            "/api/v1/sources/sync",
            json={"team_id": team_id, "source_id": source["id"]},
            headers=admin,
        ),
        strict_api_client.post(
            "/api/v1/chats/ask",
            json={
                "team_id": team_id,
                "chat_id": chat["id"],
                "question": "Can archived content be recalled?",
                "stream": False,
            },
            headers=admin,
        ),
    ]
    assert all(response.status_code == 404 for response in checks), [
        response.text for response in checks
    ]


def test_source_access_uses_knowledge_base_member_scope(strict_api_client):
    admin = _login(strict_api_client, ADMIN_EMAIL, ADMIN_PASSWORD)
    team = strict_api_client.post(
        "/api/v1/teams/create",
        json={"name": "Source Scope Team"},
        headers=admin,
    ).json()["data"]
    alice = _create_user(
        strict_api_client,
        admin,
        team["id"],
        "source-alice@example.com",
        role="leader",
    )
    bob = _create_user(
        strict_api_client, admin, team["id"], "source-bob@example.com"
    )
    alice_headers = _login(strict_api_client, alice["email"])
    bob_headers = _login(strict_api_client, bob["email"])
    kb = strict_api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Scoped Source KB"},
        headers=alice_headers,
    ).json()["data"]
    source = strict_api_client.post(
        "/api/v1/sources/github/create",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "repo_url": "https://github.com/acme/scoped.git",
        },
        headers=alice_headers,
    ).json()["data"]

    assert strict_api_client.get(
        "/api/v1/sources",
        params={"team_id": team["id"]},
        headers=bob_headers,
    ).json()["data"] == []
    denied = strict_api_client.get(
        "/api/v1/sources/detail",
        params={"team_id": team["id"], "source_id": source["id"]},
        headers=bob_headers,
    )
    assert denied.status_code == 404
