from io import BytesIO

import pytest

from backend.app.api.storage import (
    FileSizeLimitExceeded,
    normalize_file_name,
    store_file,
)
from backend.tests.api.conftest import admin_headers_for


def _team_and_kb(client, headers):
    team = client.post(
        "/api/v1/teams/create",
        json={"name": "Upload Security"},
        headers=headers,
    ).json()["data"]
    kb = client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Upload Security KB"},
        headers=headers,
    ).json()["data"]
    return team, kb


@pytest.mark.parametrize(
    "file_name",
    [
        "../escape.md",
        "../../escape.md",
        "/tmp/escape.md",
        "..\\escape.md",
        "..",
    ],
)
def test_upload_rejects_unsafe_file_names(
    api_client, monkeypatch, tmp_path, file_name
):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("TECHVAULT_UPLOAD_DIR", str(upload_dir))
    headers = admin_headers_for(api_client)
    team, kb = _team_and_kb(api_client, headers)

    response = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={"file": (file_name, b"# Unsafe\n\nMust not be stored.")},
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert not (tmp_path / "escape.md").exists()


def test_storage_rejects_path_traversal_directly(monkeypatch, tmp_path):
    monkeypatch.setenv("TECHVAULT_UPLOAD_DIR", str(tmp_path / "uploads"))
    with pytest.raises(ValueError):
        store_file(BytesIO(b"content"), "../../escape.md", "01JTEST")
    assert not (tmp_path / "escape.md").exists()


def test_store_file_stops_streaming_when_max_bytes_is_exceeded(
    monkeypatch, tmp_path
):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setenv("TECHVAULT_UPLOAD_DIR", str(upload_dir))

    class ChunkedStream:
        def __init__(self):
            self.chunks = iter((b"123456", b"789012"))

        def read(self, _size=-1):
            return next(self.chunks, b"")

    with pytest.raises(FileSizeLimitExceeded):
        store_file(
            ChunkedStream(),
            "limited.md",
            "01LIMITSTREAM",
            max_bytes=10,
        )

    assert [path for path in upload_dir.rglob("*") if path.is_file()] == []


@pytest.mark.parametrize("file_name", ["C:\\temp\\escape.md", ""])
def test_filename_normalization_rejects_windows_paths_and_empty_names(file_name):
    with pytest.raises(ValueError):
        normalize_file_name(file_name)


def test_upload_stays_inside_configured_directory(api_client, monkeypatch, tmp_path):
    upload_dir = (tmp_path / "uploads").resolve()
    monkeypatch.setenv("TECHVAULT_UPLOAD_DIR", str(upload_dir))
    headers = admin_headers_for(api_client)
    team, kb = _team_and_kb(api_client, headers)

    response = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={"file": ("安全文档.md", b"# Safe\n\nContained content.")},
        headers=headers,
    )

    assert response.status_code == 202, response.text
    stored_files = [path for path in upload_dir.rglob("*") if path.is_file()]
    assert len(stored_files) == 1
    assert stored_files[0].resolve().is_relative_to(upload_dir)
