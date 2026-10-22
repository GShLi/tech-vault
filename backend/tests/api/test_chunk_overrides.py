from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.core.config import Settings
from backend.app.db.models import (
    ChunkOverride,
    ChunkRecord,
    Document,
    DocumentVersion,
    IngestionRun,
)
from backend.app.rag.ingestion.processor import process_document
from backend.tests.api.conftest import admin_headers_for


def _create_team_and_kb(client, headers):
    team = client.post(
        "/api/v1/teams/create",
        json={"name": "Override Team"},
        headers=headers,
    ).json()["data"]
    kb = client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Override KB"},
        headers=headers,
    ).json()["data"]
    return team, kb


def _upload(client, headers, team_id, kb_id, file_name, content):
    response = client.post(
        "/api/v1/docs/upload",
        data={"team_id": team_id, "kb_id": kb_id},
        files={"file": (file_name, content.encode("utf-8"))},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def _process_new_version(session, document, path: Path):
    version = DocumentVersion(
        document_id=document.id,
        content_fingerprint=path.name,
        file_size_bytes=path.stat().st_size,
    )
    session.add(version)
    session.flush()
    document.current_version_id = version.id
    document.source_uri = str(path)
    document.doc_status = "building"
    run = IngestionRun(document_version_id=version.id, status="queued")
    session.add(run)
    session.commit()
    process_document(
        document,
        run,
        session,
        Settings(
            environment="test",
            jwt_secret="test-secret-at-least-32-bytes-long",
            enable_indexing=False,
        ),
    )
    return run


def _non_raising_client(api_app):
    return TestClient(api_app, raise_server_exceptions=False)


@pytest.mark.parametrize("endpoint", ["/chunks", "/docs/chunks"])
def test_semantic_chunk_pages_cover_all_rows_without_duplicates(
    api_client, api_app, endpoint
):
    headers = admin_headers_for(api_client)
    team, kb = _create_team_and_kb(api_client, headers)
    upload = _upload(api_client, headers, team["id"], kb["id"], "pages.md",
                     "# Records\n\nRecords generate accessors.\n\n"
                     "# Threads\n\nVirtual threads must not be pooled.")
    document_id = upload["document"]["id"]
    with api_app.state.session_factory() as session:
        query = select(ChunkRecord).where(ChunkRecord.document_id == document_id)
        if endpoint == "/chunks":
            query = query.where(ChunkRecord.chunk_level == "child")
        rows = session.scalars(query).all()
        expected = {row.id for row in rows}
    assert len(expected) > 1
    assert all(item.startswith(("chd_", "par_")) for item in expected)
    if endpoint == "/docs/chunks":
        assert any(item.startswith("par_") for item in expected)

    seen = []
    cursor = None
    with _non_raising_client(api_app) as client:
        for _ in range(len(expected) + 1):
            params = {"team_id": team["id"], "document_id": document_id, "limit": 1}
            if cursor:
                params["cursor"] = cursor
            response = client.get("/api/v1" + endpoint, params=params, headers=headers)
            assert response.status_code == 200, response.text
            page = response.json()
            seen.extend(item["id"] for item in page["data"])
            cursor = page["meta"]["next_cursor"]
            assert page["meta"]["has_more"] == bool(cursor)
            if cursor is None:
                break
    assert cursor is None
    assert len(seen) == len(set(seen))
    assert set(seen) == expected


def test_bulk_accepts_semantic_child_id_and_preserves_parent_guard(api_client, api_app):
    headers = admin_headers_for(api_client)
    team, kb = _create_team_and_kb(api_client, headers)
    upload = _upload(api_client, headers, team["id"], kb["id"], "bulk.md",
                     "# Records\n\nRecords generate accessors.")
    with api_app.state.session_factory() as session:
        rows = session.scalars(select(ChunkRecord).where(
            ChunkRecord.document_id == upload["document"]["id"]
        )).all()
        child_id = next(row.id for row in rows if row.chunk_level == "child")
        parent_id = next(row.id for row in rows if row.chunk_level == "parent")
    assert child_id.startswith("chd_") and len(child_id) == 68
    for action, status in [("disable", "disabled"), ("enable", "enabled")]:
        response = api_client.post("/api/v1/chunks/bulk", headers=headers, json={
            "team_id": team["id"], "chunk_ids": [child_id], "action": action,
        })
        assert response.status_code == 200, response.text
        with api_app.state.session_factory() as session:
            assert session.get(ChunkRecord, child_id).chunk_status == status
    response = api_client.post("/api/v1/chunks/bulk", headers=headers, json={
        "team_id": team["id"], "chunk_ids": [parent_id], "action": "disable",
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_chunk_update_rejects_non_numeric_if_match_without_server_error(
    api_client, api_app
):
    headers = admin_headers_for(api_client)
    team, kb = _create_team_and_kb(api_client, headers)
    upload = _upload(
        api_client,
        headers,
        team["id"],
        kb["id"],
        "invalid-match.md",
        "# Invalid match\n\nContent.",
    )
    with api_app.state.session_factory() as session:
        chunk_id = session.scalar(
            select(ChunkRecord.id).where(
                ChunkRecord.document_id == upload["document"]["id"]
            )
        )

    with _non_raising_client(api_app) as client:
        response = client.post(
            "/api/v1/chunks/update",
            json={
                "team_id": team["id"],
                "chunk_id": chunk_id,
                "content": "Updated content.",
            },
            headers={**headers, "If-Match": "not-a-version"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_chunk_update_rejects_non_string_content_without_server_error(
    api_client, api_app
):
    headers = admin_headers_for(api_client)
    team, kb = _create_team_and_kb(api_client, headers)
    upload = _upload(
        api_client,
        headers,
        team["id"],
        kb["id"],
        "invalid-content.md",
        "# Invalid content\n\nContent.",
    )
    with api_app.state.session_factory() as session:
        chunk = session.scalar(
            select(ChunkRecord).where(ChunkRecord.chunk_level == "child").where(
                ChunkRecord.document_id == upload["document"]["id"]
            )
        )
        chunk_id = chunk.id
        chunk_version = chunk.version

    with _non_raising_client(api_app) as client:
        response = client.post(
            "/api/v1/chunks/update",
            json={
                "team_id": team["id"],
                "chunk_id": chunk_id,
                "content": 123,
            },
            headers={**headers, "If-Match": str(chunk_version)},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_chunk_bulk_rejects_non_string_action_without_server_error(
    api_client, api_app
):
    headers = admin_headers_for(api_client)
    team, kb = _create_team_and_kb(api_client, headers)
    upload = _upload(
        api_client,
        headers,
        team["id"],
        kb["id"],
        "invalid-bulk.md",
        "# Invalid bulk\n\nContent.",
    )
    with api_app.state.session_factory() as session:
        chunk_id = session.scalar(
            select(ChunkRecord.id).where(
                ChunkRecord.document_id == upload["document"]["id"]
            )
        )

    with _non_raising_client(api_app) as client:
        response = client.post(
            "/api/v1/chunks/bulk",
            json={
                "team_id": team["id"],
                "chunk_ids": [chunk_id],
                "action": ["enable"],
            },
            headers=headers,
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_manual_edit_is_inherited_by_logical_key_and_auto_content_is_separate(
    api_client, api_app, tmp_path
):
    headers = admin_headers_for(api_client)
    team, kb = _create_team_and_kb(api_client, headers)
    upload = _upload(
        api_client,
        headers,
        team["id"],
        kb["id"],
        "guide.md",
        "# Guide\n\nOriginal automatic content.",
    )
    with api_app.state.session_factory() as session:
        chunk = session.scalar(
            select(ChunkRecord).where(ChunkRecord.chunk_level == "child").where(
                ChunkRecord.document_id == upload["document"]["id"]
            )
        )
        chunk_id = chunk.id
        logical_chunk_key = chunk.logical_chunk_key
        original_auto_content = chunk.content
        chunk_version = chunk.version

    updated = api_client.post(
        "/api/v1/chunks/update",
        json={
            "team_id": team["id"],
            "chunk_id": chunk_id,
            "content": "Operator maintained migration notes.",
        },
        headers={**headers, "If-Match": str(chunk_version)},
    )
    assert updated.status_code == 200, updated.text

    new_path = tmp_path / "guide-v2.md"
    new_path.write_text(
        "# Guide\n\nNew upstream automatic content.",
        encoding="utf-8",
    )
    with api_app.state.session_factory() as session:
        document = session.get(Document, upload["document"]["id"])
        run = _process_new_version(session, document, new_path)
        assert run.status == "completed"

        old_chunk = session.get(ChunkRecord, chunk_id)
        inherited = session.scalar(
            select(ChunkRecord).where(ChunkRecord.chunk_level == "child").where(
                ChunkRecord.document_id == document.id,
                ChunkRecord.logical_chunk_key == logical_chunk_key,
                ChunkRecord.status == "enabled",
            )
        )
        override = session.scalar(
            select(ChunkOverride).where(
                ChunkOverride.document_id == document.id,
                ChunkOverride.logical_chunk_key == logical_chunk_key,
            )
        )

        assert old_chunk.status == "disabled"
        assert inherited is not None
        assert inherited.id != chunk_id
        assert inherited.content == "Operator maintained migration notes."
        assert inherited.auto_content == "New upstream automatic content."
        assert inherited.auto_content != original_auto_content
        assert override.status == "active"
        assert override.content == "Operator maintained migration notes."
        assert override.applied_chunk_id == inherited.id
        assert override.pending_reason is None


def test_unmatched_override_is_kept_pending_instead_of_deleted(
    api_client, api_app, tmp_path
):
    headers = admin_headers_for(api_client)
    team, kb = _create_team_and_kb(api_client, headers)
    upload = _upload(
        api_client,
        headers,
        team["id"],
        kb["id"],
        "pending.md",
        "# Removed Section\n\nContent that needs an operator note.",
    )
    with api_app.state.session_factory() as session:
        chunk = session.scalar(
            select(ChunkRecord).where(ChunkRecord.chunk_level == "child").where(
                ChunkRecord.document_id == upload["document"]["id"]
            )
        )
        chunk_id = chunk.id
        logical_chunk_key = chunk.logical_chunk_key
        chunk_version = chunk.version

    updated = api_client.post(
        "/api/v1/chunks/update",
        json={
            "team_id": team["id"],
            "chunk_id": chunk_id,
            "content": "This note must survive until reviewed.",
        },
        headers={**headers, "If-Match": str(chunk_version)},
    )
    assert updated.status_code == 200

    new_path = tmp_path / "pending-v2.md"
    new_path.write_text("# Replacement Section\n\nDifferent structure.", encoding="utf-8")
    with api_app.state.session_factory() as session:
        document = session.get(Document, upload["document"]["id"])
        _process_new_version(session, document, new_path)
        override = session.scalar(
            select(ChunkOverride).where(
                ChunkOverride.document_id == document.id,
                ChunkOverride.logical_chunk_key == logical_chunk_key,
            )
        )
        assert override is not None
        assert override.status == "pending"
        assert override.content == "This note must survive until reviewed."
        assert override.applied_chunk_id is None
        assert "logical_chunk_key" in override.pending_reason


def test_manual_disable_is_inherited_by_new_version(api_client, api_app, tmp_path):
    headers = admin_headers_for(api_client)
    team, kb = _create_team_and_kb(api_client, headers)
    upload = _upload(
        api_client,
        headers,
        team["id"],
        kb["id"],
        "disable.md",
        "# Disabled Section\n\nDo not index this section.",
    )
    with api_app.state.session_factory() as session:
        chunk = session.scalar(
            select(ChunkRecord).where(ChunkRecord.chunk_level == "child").where(
                ChunkRecord.document_id == upload["document"]["id"]
            )
        )
        chunk_id = chunk.id
        logical_chunk_key = chunk.logical_chunk_key

    disabled = api_client.post(
        "/api/v1/chunks/disable",
        json={"team_id": team["id"], "chunk_ids": [chunk_id]},
        headers=headers,
    )
    assert disabled.status_code == 200

    new_path = tmp_path / "disable-v2.md"
    new_path.write_text(
        "# Disabled Section\n\nUpstream changed the paragraph.",
        encoding="utf-8",
    )
    with api_app.state.session_factory() as session:
        document = session.get(Document, upload["document"]["id"])
        _process_new_version(session, document, new_path)
        inherited = session.scalar(
            select(ChunkRecord).where(ChunkRecord.chunk_level == "child").where(
                ChunkRecord.document_id == document.id,
                ChunkRecord.logical_chunk_key == logical_chunk_key,
                ChunkRecord.doc_status == "active",
            )
        )
        override = session.scalar(
            select(ChunkOverride).where(
                ChunkOverride.document_id == document.id,
                ChunkOverride.logical_chunk_key == logical_chunk_key,
            )
        )
        assert inherited is not None
        assert inherited.id != chunk_id
        assert inherited.status == "disabled"
        assert inherited.chunk_status == "disabled"
        assert inherited.auto_content == "Upstream changed the paragraph."
        assert override.manual_status == "disabled"
        assert override.status == "active"
