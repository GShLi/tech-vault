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


def test_knowledge_base_membership_scopes_lists_documents_and_retrieval(
    strict_api_client,
):
    admin = _login(strict_api_client, ADMIN_EMAIL, ADMIN_PASSWORD)
    team = strict_api_client.post(
        "/api/v1/teams/create",
        json={"name": "Scoped Knowledge Team"},
        headers=admin,
    ).json()["data"]
    alice = _create_user(
        strict_api_client, admin, team["id"], "alice-scope@example.com"
    )
    bob = _create_user(
        strict_api_client, admin, team["id"], "bob-scope@example.com"
    )
    kb = strict_api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Scoped KB"},
        headers=admin,
    ).json()["data"]

    initial_members = strict_api_client.get(
        "/api/v1/kbs/members",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=admin,
    )
    assert initial_members.status_code == 200
    assert [item["user_id"] for item in initial_members.json()["data"]] == [
        initial_members.json()["data"][0]["user_id"]
    ]

    updated = strict_api_client.post(
        "/api/v1/kbs/members/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "user_ids": [alice["id"]],
        },
        headers=admin,
    )
    assert updated.status_code == 200
    assert {item["user_id"] for item in updated.json()["data"]} == {
        alice["id"]
    }

    admin_list = strict_api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"]},
        headers=admin,
    )
    assert admin_list.json()["data"] == []

    alice_headers = _login(strict_api_client, "alice-scope@example.com")
    bob_headers = _login(strict_api_client, "bob-scope@example.com")
    alice_list = strict_api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"]},
        headers=alice_headers,
    )
    bob_list = strict_api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"]},
        headers=bob_headers,
    )
    assert [item["id"] for item in alice_list.json()["data"]] == [kb["id"]]
    assert bob_list.json()["data"] == []

    alice_members = strict_api_client.get(
        "/api/v1/kbs/members",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=alice_headers,
    )
    assert alice_members.status_code == 200
    assert [item["user_id"] for item in alice_members.json()["data"]] == [
        alice["id"]
    ]
    bob_members = strict_api_client.get(
        "/api/v1/kbs/members",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=bob_headers,
    )
    assert bob_members.status_code == 404
    alice_update = strict_api_client.post(
        "/api/v1/kbs/members/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "user_ids": [bob["id"]],
        },
        headers=alice_headers,
    )
    assert alice_update.status_code == 403

    upload = strict_api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={"file": ("scope.md", b"# Scope\n\nScoped content.")},
        headers=alice_headers,
    )
    assert upload.status_code == 202, upload.text

    alice_docs = strict_api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=alice_headers,
    )
    bob_docs = strict_api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=bob_headers,
    )
    assert len(alice_docs.json()["data"]) == 1
    assert bob_docs.status_code == 404

    bob_policy = strict_api_client.get(
        "/api/v1/kbs/policy",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=bob_headers,
    )
    assert bob_policy.status_code == 404
    assert bob_policy.json()["error"]["code"] == "NOT_FOUND"

    alice_ingestions = strict_api_client.get(
        "/api/v1/ingestions",
        params={"team_id": team["id"]},
        headers=alice_headers,
    )
    bob_ingestions = strict_api_client.get(
        "/api/v1/ingestions",
        params={"team_id": team["id"]},
        headers=bob_headers,
    )
    assert len(alice_ingestions.json()["data"]) == 1
    assert bob_ingestions.status_code == 200
    assert bob_ingestions.json()["data"] == []

    bob_chat = strict_api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "knowledge_base_ids": [kb["id"]]},
        headers=bob_headers,
    ).json()["data"]
    denied_ask = strict_api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": bob_chat["id"],
            "question": "Scoped content?",
            "stream": False,
        },
        headers=bob_headers,
    )
    assert denied_ask.status_code == 404
    assert denied_ask.json()["error"]["code"] == "NOT_FOUND"
