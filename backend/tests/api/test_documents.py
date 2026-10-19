from sqlalchemy import select

from backend.app.db.models import ChunkRecord


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


def test_uploaded_chunks_keep_team_and_knowledge_base_scope(api_client, api_app):
    headers = _register_and_login(api_client, email="scope@example.com")
    team, kb = _create_team_and_kb(api_client, headers)

    upload = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={"file": ("scope.md", b"# Scope\n\nScoped content.")},
        headers=headers,
    )
    assert upload.status_code == 202

    with api_app.state.session_factory() as session:
        chunks = session.scalars(select(ChunkRecord)).all()
        assert chunks
        assert all(chunk.team_id == team["id"] for chunk in chunks)
        assert all(chunk.knowledge_base_id == kb["id"] for chunk in chunks)


def test_document_endpoints_reject_another_team_scope(api_client):
    owner_headers = _register_and_login(api_client, email="owner-scope@example.com")
    other_headers = _register_and_login(api_client, email="other-scope@example.com")

    owner_team, owner_kb = _create_team_and_kb(api_client, owner_headers)
    other_team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "OtherTeam"},
        headers=other_headers,
    ).json()["data"]

    upload = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": owner_team["id"], "kb_id": owner_kb["id"]},
        files={"file": ("private.md", b"# Private\n\nOwner content.")},
        headers=owner_headers,
    )
    assert upload.status_code == 202
    document_id = upload.json()["data"]["document"]["id"]

    cross_team = api_client.get(
        "/api/v1/docs/detail",
        params={"team_id": other_team["id"], "document_id": document_id},
        headers=other_headers,
    )
    assert cross_team.status_code == 404

    bad_upload = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": other_team["id"], "kb_id": owner_kb["id"]},
        files={"file": ("bad.md", b"# Bad\n\nWrong scope.")},
        headers=other_headers,
    )
    assert bad_upload.status_code == 404
