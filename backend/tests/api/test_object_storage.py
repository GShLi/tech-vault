from io import BytesIO

import httpx
import pytest

from backend.app.api.storage import (
    ObjectStorageUnavailable,
    delete_s3_object,
    store_file,
)
from backend.app.core.config import Settings


def _settings(upload_dir, *, enabled=True):
    return Settings(
        environment="development",
        jwt_secret="test-secret-at-least-32-bytes-long",
        upload_dir=str(upload_dir),
        object_storage_enabled=enabled,
        minio_url="http://127.0.0.1:59000",
        minio_public_url="http://127.0.0.1:59000",
        minio_access_key="minioadmin",
        minio_secret_key="minioadmin",
        minio_bucket="techvault",
        s3_region="us-east-1",
    )


def test_store_file_uploads_original_object_and_keeps_local_work_copy(
    monkeypatch, tmp_path
):
    calls = []

    def fake_put(url, *, content, timeout):
        calls.append((url, content, timeout))
        return httpx.Response(200, request=httpx.Request("PUT", url))

    monkeypatch.setattr("backend.app.api.storage.httpx.put", fake_put)

    stored = store_file(
        BytesIO(b"# Stored\n\nOriginal bytes."),
        "guide.md",
        "01OBJECTDOCUMENT0000000000",
        _settings(tmp_path),
    )

    assert stored.path.exists()
    assert stored.path.read_bytes() == b"# Stored\n\nOriginal bytes."
    assert stored.object_uri == (
        "s3://techvault/documents/01OBJECTDOCUMENT0000000000/guide.md"
    )
    assert len(calls) == 1
    assert "/techvault/documents/01OBJECTDOCUMENT0000000000/guide.md" in calls[0][0]
    assert "X-Amz-Signature=" in calls[0][0]


def test_store_file_removes_local_copy_when_object_upload_fails(
    monkeypatch, tmp_path
):
    def failed_put(url, *, content, timeout):
        return httpx.Response(500, request=httpx.Request("PUT", url))

    monkeypatch.setattr("backend.app.api.storage.httpx.put", failed_put)

    with pytest.raises(ObjectStorageUnavailable):
        store_file(
            BytesIO(b"# Failed\n"),
            "failed.md",
            "01OBJECTDOCUMENT0000000001",
            _settings(tmp_path),
        )

    assert list(tmp_path.rglob("*.md")) == []


def test_store_file_keeps_local_only_when_object_storage_is_disabled(tmp_path):
    stored = store_file(
        BytesIO(b"# Local\n"),
        "local.md",
        "01OBJECTDOCUMENT0000000002",
        _settings(tmp_path, enabled=False),
    )

    assert stored.object_uri is None
    assert stored.path.read_bytes() == b"# Local\n"


def test_store_file_uses_configured_upload_directory(tmp_path):
    configured_root = tmp_path / "configured-uploads"

    stored = store_file(
        BytesIO(b"# Root\n"),
        "root.md",
        "01OBJECTDOCUMENT0000000003",
        _settings(configured_root, enabled=False),
    )

    assert stored.path.is_relative_to(configured_root.resolve())
    assert stored.path.exists()


def test_delete_s3_object_accepts_no_content_and_encodes_object_key(
    monkeypatch,
):
    calls = []

    def fake_delete(url, *, timeout):
        calls.append((url, timeout))
        return httpx.Response(204, request=httpx.Request("DELETE", url))

    monkeypatch.setattr("backend.app.api.storage.httpx.delete", fake_delete)

    delete_s3_object(
        "s3://techvault/documents/team%20one/guide%20copy.md",
        _settings("/tmp/object-storage"),
    )

    assert len(calls) == 1
    assert "team%20one/guide%20copy.md" in calls[0][0]
    assert calls[0][1] == 60.0


def test_delete_s3_object_reports_storage_failure(monkeypatch):
    def failed_delete(url, *, timeout):
        return httpx.Response(503, request=httpx.Request("DELETE", url))

    monkeypatch.setattr("backend.app.api.storage.httpx.delete", failed_delete)

    with pytest.raises(ObjectStorageUnavailable):
        delete_s3_object(
            "s3://techvault/documents/failure.md",
            _settings("/tmp/object-storage"),
        )
