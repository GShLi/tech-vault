from dataclasses import replace
from datetime import timedelta

from sqlalchemy import select

from backend.app.db.models import ChunkRecord, Document, utc_now
from backend.tests.api.conftest import admin_headers_for


def _upload(client, headers):
    team = client.post(
        "/api/v1/teams/create", json={"name": "Lifecycle Team"}, headers=headers
    ).json()["data"]
    kb = client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Lifecycle KB"},
        headers=headers,
    ).json()["data"]
    upload = client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={"file": ("lifecycle.md", b"# Lifecycle\n\nOriginal content.")},
        headers=headers,
    )
    return team, kb, upload.json()["data"]["document"]


def test_document_delete_disables_chunks_and_restore_rebuilds(api_client, api_app):
    headers = admin_headers_for(api_client)
    team, kb, document = _upload(api_client, headers)

    deleted = api_client.post(
        "/api/v1/docs/delete",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )

    assert deleted.status_code == 202
    assert deleted.json()["data"]["doc_status"] == "deleted"
    listed = api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=headers,
    )
    assert listed.json()["data"] == []
    with api_app.state.session_factory() as session:
        chunks = session.scalars(select(ChunkRecord)).all()
        assert chunks
        assert all(chunk.status == "disabled" for chunk in chunks)
        assert all(chunk.doc_status == "deleted" for chunk in chunks)

    restored = api_client.post(
        "/api/v1/docs/restore",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )

    assert restored.status_code == 202
    assert restored.json()["data"]["doc_status"] == "active"
    with api_app.state.session_factory() as session:
        chunks = session.scalars(select(ChunkRecord)).all()
        assert all(chunk.status == "enabled" for chunk in chunks)
        assert all(chunk.doc_status == "active" for chunk in chunks)


def test_download_url_fails_closed_for_local_storage(api_client):
    headers = admin_headers_for(api_client)
    team, _, document = _upload(api_client, headers)

    response = api_client.get(
        "/api/v1/docs/download-url",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STORAGE_PRESIGN_UNAVAILABLE"
    assert "url" not in response.json().get("data", {})


def test_download_url_rejects_soft_deleted_document(api_client):
    headers = admin_headers_for(api_client)
    team, _, document = _upload(api_client, headers)
    deleted = api_client.post(
        "/api/v1/docs/delete",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )
    assert deleted.status_code == 202

    response = api_client.get(
        "/api/v1/docs/download-url",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )

    assert response.status_code == 404


def test_download_rejects_soft_deleted_document(api_client, api_app, tmp_path):
    api_app.state.settings = replace(
        api_app.state.settings,
        upload_dir=str(tmp_path / "uploads"),
        object_storage_enabled=False,
    )
    headers = admin_headers_for(api_client)
    team, _, document = _upload(api_client, headers)
    deleted = api_client.post(
        "/api/v1/docs/delete",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )
    assert deleted.status_code == 202

    response = api_client.get(
        "/api/v1/docs/download",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )

    assert response.status_code == 404


def test_delete_keeps_source_until_retention_expires_and_restore_clears_it(
    api_client, api_app, tmp_path
):
    api_app.state.settings = replace(
        api_app.state.settings,
        upload_dir=str(tmp_path / "uploads"),
        document_retention_days=7,
        object_storage_enabled=False,
    )
    headers = admin_headers_for(api_client)
    team, _, document = _upload(api_client, headers)

    with api_app.state.session_factory() as session:
        source_uri = session.get(Document, document["id"]).source_uri
    assert source_uri and source_uri.startswith(str(tmp_path))

    deleted = api_client.post(
        "/api/v1/docs/delete",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )

    assert deleted.status_code == 202
    with api_app.state.session_factory() as session:
        stored = session.get(Document, document["id"])
        assert stored.deleted_at is not None
        assert stored.purged_at is None
    assert (tmp_path / "uploads").exists()
    assert any((tmp_path / "uploads").rglob("lifecycle.md"))

    restored = api_client.post(
        "/api/v1/docs/restore",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )

    assert restored.status_code == 202
    with api_app.state.session_factory() as session:
        stored = session.get(Document, document["id"])
        assert stored.deleted_at is None
        assert stored.purged_at is None


def test_restore_after_retention_window_is_rejected_and_purges_source(
    api_client, api_app, tmp_path, monkeypatch
):
    api_app.state.settings = replace(
        api_app.state.settings,
        upload_dir=str(tmp_path / "uploads"),
        document_retention_days=7,
        object_storage_enabled=False,
    )
    headers = admin_headers_for(api_client)
    team, _, document = _upload(api_client, headers)
    cache_file = tmp_path / "uploads" / "cache" / (document["id"] + ".download")
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"cached")
    with api_app.state.session_factory() as session:
        stored = session.get(Document, document["id"])
        source_uri = stored.source_uri
        stored.doc_status = "deleted"
        stored.deleted_at = utc_now() - timedelta(days=8)
        session.commit()

    response = api_client.post(
        "/api/v1/docs/restore",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RETENTION_EXPIRED"
    assert not cache_file.exists()
    with api_app.state.session_factory() as session:
        stored = session.get(Document, document["id"])
        assert stored.purged_at is not None
    assert source_uri
