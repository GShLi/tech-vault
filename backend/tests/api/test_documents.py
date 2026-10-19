def _register_and_login(client, email="uploader@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password-123", "display_name": "Uploader"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password-123"},
    )
    return {"Authorization": "Bearer " + login.json()["data"]["access_token"]}


def _create_team_and_kb(client, headers):
    team = client.post(
        "/api/v1/teams/create",
        json={"name": "DocTest"},
        headers=headers,
    ).json()["data"]
    kb = client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Test KB"},
        headers=headers,
    ).json()["data"]
    return team, kb


def test_upload_returns_202_and_lists_document(api_client):
    headers = _register_and_login(api_client)
    team, kb = _create_team_and_kb(api_client, headers)

    upload = api_client.post(
        "/api/v1/docs/upload",
        data={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "visibility": "team_shared",
            "data_classification": "internal",
        },
        files={"file": ("README.md", b"# Hello\n\nThis is a test document.")},
        headers=headers,
    )

    assert upload.status_code == 202
    assert upload.json()["data"]["document"]["file_name"] == "README.md"
    assert upload.json()["data"]["document"]["doc_status"] == "active"
    assert upload.json()["data"]["document_version_id"]
    assert upload.json()["data"]["ingestion_run_id"]

    doc_list = api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=headers,
    )
    assert doc_list.status_code == 200
    assert len(doc_list.json()["data"]) == 1

    detail = api_client.get(
        "/api/v1/docs/detail",
        params={"team_id": team["id"], "document_id": upload.json()["data"]["document"]["id"]},
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["file_name"] == "README.md"

    ingestion_list = api_client.get(
        "/api/v1/ingestions",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert ingestion_list.status_code == 200
    assert len(ingestion_list.json()["data"]) == 1

    ingestion_detail = api_client.get(
        "/api/v1/ingestions/detail",
        params={"team_id": team["id"], "run_id": upload.json()["data"]["ingestion_run_id"]},
        headers=headers,
    )
    assert ingestion_detail.status_code == 200
    assert ingestion_detail.json()["data"]["status"] == "completed"
