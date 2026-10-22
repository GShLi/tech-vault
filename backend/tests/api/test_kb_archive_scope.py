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


def test_archived_kb_is_not_available_to_document_or_chat_paths(
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
        strict_api_client.post(
            "/api/v1/chats/ask",
            json={
                "team_id": team_id,
                "chat_id": chat["id"],
                "question": "Can archived content be recalled?",
                "provider_id": "provider-scope-test",
                "model_id": "model-scope-test",
                "stream": False,
            },
            headers=admin,
        ),
    ]
    assert all(response.status_code == 404 for response in checks), [
        response.text for response in checks
    ]
