from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from backend.app.api.storage import ObjectStorageUnavailable
from backend.app.db.models import Document, utc_now
from backend.app.modules.documents.lifecycle import purge_expired_documents_record
from backend.app.workers.tasks import celery_app, purge_expired_documents
from backend.tests.api.conftest import admin_headers_for


def _deleted_document(api_client, api_app, tmp_path, monkeypatch):
    api_app.state.settings = replace(
        api_app.state.settings,
        upload_dir=str(tmp_path / "uploads"),
        document_retention_days=7,
        object_storage_enabled=False,
    )
    headers = admin_headers_for(api_client)
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Purge Team"},
        headers=headers,
    ).json()["data"]
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Purge KB"},
        headers=headers,
    ).json()["data"]
    upload = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={"file": ("purge.md", b"# Purge\n\nOriginal content.")},
        headers=headers,
    ).json()["data"]["document"]
    cache_file = tmp_path / "uploads" / "cache" / (upload["id"] + ".download")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b"cached")
    with api_app.state.session_factory() as session:
        document = session.get(Document, upload["id"])
        document.doc_status = "deleted"
        document.deleted_at = utc_now() - timedelta(days=8)
        document.object_uri = "s3://techvault/documents/purge.md"
        session.commit()
        source_uri = document.source_uri
    return headers, team, upload, source_uri, cache_file


def test_purge_expired_document_removes_indexed_and_local_resources(
    api_client, api_app, tmp_path, monkeypatch
):
    _, _, document, source_uri, cache_file = _deleted_document(
        api_client,
        api_app,
        tmp_path,
        monkeypatch,
    )
    deleted_objects = []
    monkeypatch.setattr(
        "backend.app.modules.documents.lifecycle.delete_s3_object",
        lambda uri, settings: deleted_objects.append(uri),
    )

    with api_app.state.session_factory() as session:
        result = purge_expired_documents_record(session, api_app.state.settings)

    assert result == {"scanned": 1, "purged": [document["id"]], "failed": []}
    assert deleted_objects == ["s3://techvault/documents/purge.md"]
    assert not Path(source_uri).exists()
    assert not cache_file.exists()
    with api_app.state.session_factory() as session:
        stored = session.get(Document, document["id"])
        assert stored.purged_at is not None


def test_purge_storage_failure_keeps_document_retryable(
    api_client, api_app, tmp_path, monkeypatch
):
    _, _, document, _, cache_file = _deleted_document(
        api_client,
        api_app,
        tmp_path,
        monkeypatch,
    )

    def failed_delete(uri, settings):
        raise ObjectStorageUnavailable("unavailable")

    monkeypatch.setattr(
        "backend.app.modules.documents.lifecycle.delete_s3_object",
        failed_delete,
    )

    with api_app.state.session_factory() as session:
        result = purge_expired_documents_record(session, api_app.state.settings)

    assert result["scanned"] == 1
    assert result["purged"] == []
    assert result["failed"][0]["document_id"] == document["id"]
    assert cache_file.exists()
    with api_app.state.session_factory() as session:
        assert session.get(Document, document["id"]).purged_at is None


def test_celery_beat_schedules_periodic_document_purge():
    schedule = celery_app.conf.beat_schedule

    assert schedule["purge-expired-documents"]["task"] == purge_expired_documents.name
    assert schedule["purge-expired-documents"]["schedule"] <= 3600
