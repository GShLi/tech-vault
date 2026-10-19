from __future__ import annotations

import base64
import json

import httpx
from sqlalchemy import select

from backend.app.core.secrets import decrypt_secret
from backend.app.db.models import (
    AuditLog,
    ChunkRecord,
    Credential,
    Document,
    IndexGenerationRecord,
    SourceConnection,
    User,
)
from backend.app.modules.sources import github as github_sync
from backend.tests.api.conftest import (
    admin_headers_for,
    create_team_as_admin,
    create_user_as_admin,
    login_headers,
)


def _register_and_login(client, email: str):
    return admin_headers_for(client)


def _create_team_and_kb(client, headers, name: str):
    team = client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    ).json()["data"]
    kb = client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": name + " KB"},
        headers=headers,
    ).json()["data"]
    return team, kb


def _create_source(client, headers, team_id: str, kb_id: str, credential_id: str = ""):
    body = {
        "team_id": team_id,
        "kb_id": kb_id,
        "repo_url": "https://github.com/acme/handbook.git",
        "branch": "main",
        "path_filters": ["docs/"],
    }
    if credential_id:
        body["credentials_id"] = credential_id
    return client.post(
        "/api/v1/sources/github/create",
        json=body,
        headers=headers,
    )


def _seed_active_generation(api_app, team_id: str):
    with api_app.state.session_factory() as session:
        generation = IndexGenerationRecord(
            team_id=team_id,
            status="active",
            chunk_count=0,
        )
        session.add(generation)
        session.commit()
        return generation.id


def _github_transport(
    requests: list[httpx.Request],
    *,
    fail_auth: bool = False,
    commit_sha: str = "commit-sha-1",
    tree_sha: str = "tree-sha-1",
    tree_files=None,
    missing_blobs=None,
):
    files = tree_files
    if files is None:
        files = [
            {"path": "README.md", "type": "blob", "sha": "root-md", "size": 10},
            {"path": "docs/guide.md", "type": "blob", "sha": "guide-md", "size": 24},
            {"path": "docs/runbook.txt", "type": "blob", "sha": "runbook-txt", "size": 20},
            {"path": "docs/example.py", "type": "blob", "sha": "example-py", "size": 20},
        ]
    unavailable_blobs = set(missing_blobs or ())

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if fail_auth:
            return httpx.Response(401, json={"message": "Bad credentials"})
        if request.url.path == "/repos/acme/handbook/branches/main":
            return httpx.Response(
                200,
                json={
                    "commit": {
                        "sha": commit_sha,
                        "commit": {"tree": {"sha": tree_sha}},
                    }
                },
            )
        if request.url.path == "/repos/acme/handbook/git/trees/" + tree_sha:
            return httpx.Response(
                200,
                json={
                    "sha": tree_sha,
                    "truncated": False,
                    "tree": files,
                },
            )
        blobs = {
            "guide-md": b"# Guide\n\nUse the platform.",
            "runbook-txt": b"Run the recovery procedure.",
        }
        if request.url.path.startswith("/repos/acme/handbook/git/blobs/"):
            sha = request.url.path.rsplit("/", 1)[-1]
            if sha in unavailable_blobs:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(
                200,
                json={
                    "sha": sha,
                    "encoding": "base64",
                    "content": base64.b64encode(blobs[sha]).decode("ascii"),
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handler)


def test_github_sync_ingests_supported_files_and_skips_unchanged_files(
    api_client, api_app, monkeypatch
):
    headers = _register_and_login(api_client, "github-leader@example.com")
    team, kb = _create_team_and_kb(api_client, headers, "GitHub Team")
    source_response = _create_source(api_client, headers, team["id"], kb["id"])
    assert source_response.status_code == 201
    source_id = source_response.json()["data"]["id"]

    requests: list[httpx.Request] = []
    monkeypatch.setattr(
        github_sync,
        "build_github_client",
        lambda _source, token=None: github_sync.GitHubClient(
            transport=_github_transport(requests)
        ),
    )

    first = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source_id},
        headers=headers,
    )

    assert first.status_code == 202
    data = first.json()["data"]
    assert data["status"] == "active"
    assert data["cursor"] == "commit-sha-1"
    assert data["files_seen"] == 4
    assert data["documents_created"] == 2
    assert data["documents_updated"] == 0
    assert data["documents_unchanged"] == 0

    listed = api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=headers,
    )
    assert listed.status_code == 200
    assert {item["file_name"] for item in listed.json()["data"]} == {
        "acme/handbook/docs/guide.md",
        "acme/handbook/docs/runbook.txt",
    }

    with api_app.state.session_factory() as session:
        source = session.get(SourceConnection, source_id)
        assert source.status == "active"
        assert source.sync_cursor == "commit-sha-1"
        documents = session.scalars(
            select(Document).where(Document.source_type == "github")
        ).all()
        assert len(documents) == 2
        chunks = session.scalars(select(ChunkRecord)).all()
        assert chunks
        assert all(chunk.team_id == team["id"] for chunk in chunks)

    blob_requests_after_first = [
        request for request in requests if "/git/blobs/" in request.url.path
    ]
    assert len(blob_requests_after_first) == 2

    second = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source_id},
        headers=headers,
    )

    assert second.status_code == 202
    second_data = second.json()["data"]
    assert second_data["documents_created"] == 0
    assert second_data["documents_updated"] == 0
    assert second_data["documents_unchanged"] == 2
    blob_requests_after_second = [
        request for request in requests if "/git/blobs/" in request.url.path
    ]
    assert len(blob_requests_after_second) == 2


def test_github_sync_requires_leader_and_credentials_remain_masked(
    api_client, api_app, monkeypatch
):
    admin_headers = admin_headers_for(api_client)
    team = create_team_as_admin(api_client, admin_headers, "Secure Sources")
    owner = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "source-owner@example.com",
        role="leader",
        display_name="Source Owner",
    )
    owner = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "source-member@example.com",
        role="member",
        display_name="Source Member",
    )
    leader_headers = login_headers(api_client, "source-owner@example.com")
    member_headers = login_headers(api_client, "source-member@example.com")
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Secure Sources KB"},
        headers=leader_headers,
    ).json()["data"]

    credential = api_client.post(
        "/api/v1/credentials/create",
        json={
            "team_id": team["id"],
            "name": "GitHub token",
            "secret": "ghp_super-secret-1234",
        },
        headers=leader_headers,
    )
    assert credential.status_code == 201
    credential_data = credential.json()["data"]
    assert credential_data["secret_masked"] == "****1234"
    assert "secret" not in credential_data

    listed_credentials = api_client.get(
        "/api/v1/credentials",
        params={"team_id": team["id"]},
        headers=leader_headers,
    )
    assert listed_credentials.status_code == 200
    assert listed_credentials.json()["data"][0]["secret_masked"] == "****1234"
    assert "ghp_super-secret-1234" not in listed_credentials.text
    with api_app.state.session_factory() as session:
        stored = session.get(Credential, credential_data["id"])
        assert stored.secret_encrypted
        assert "ghp_super-secret-1234" not in stored.secret_encrypted
        assert decrypt_secret(
            stored.secret_encrypted, api_app.state.settings
        ) == "ghp_super-secret-1234"

    source = _create_source(
        api_client,
        leader_headers,
        team["id"],
        kb["id"],
        credential_data["id"],
    )
    assert source.status_code == 201
    source_id = source.json()["data"]["id"]
    assert "ghp_super-secret-1234" not in source.text

    captured_tokens = []

    def build_client(_source, token=None):
        captured_tokens.append(token)
        return github_sync.GitHubClient(transport=_github_transport([]))

    monkeypatch.setattr(github_sync, "build_github_client", build_client)
    synced = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source_id},
        headers=leader_headers,
    )
    assert synced.status_code == 202
    assert captured_tokens == ["ghp_super-secret-1234"]

    denied = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source_id},
        headers=member_headers,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "PERMISSION_DENIED"

    other_team, _ = _create_team_and_kb(api_client, admin_headers, "Other Sources")
    other_credential = api_client.post(
        "/api/v1/credentials/create",
        json={"team_id": other_team["id"], "name": "Other", "secret": "other-token-9999"},
        headers=admin_headers,
    ).json()["data"]
    cross_team = _create_source(
        api_client,
        leader_headers,
        team["id"],
        kb["id"],
        other_credential["id"],
    )
    assert cross_team.status_code == 404
    assert cross_team.json()["error"]["code"] == "NOT_FOUND"


def test_member_can_create_and_manage_own_source(api_client):
    admin_headers = admin_headers_for(api_client)
    team = create_team_as_admin(api_client, admin_headers, "Member Sources")
    owner = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "member-source-owner@example.com",
        role="member",
        display_name="Member Source Owner",
    )
    peer = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "member-source-peer@example.com",
        role="member",
        display_name="Member Source Peer",
    )
    member_headers = login_headers(api_client, "member-source-owner@example.com")
    peer_headers = login_headers(api_client, "member-source-peer@example.com")
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Member Sources KB"},
        headers=admin_headers,
    ).json()["data"]
    membership_update = api_client.post(
        "/api/v1/kbs/members/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "user_ids": [owner["user"]["id"], peer["user"]["id"]],
        },
        headers=admin_headers,
    )
    assert membership_update.status_code == 200, membership_update.text

    created = _create_source(api_client, member_headers, team["id"], kb["id"])
    assert created.status_code == 201
    source = created.json()["data"]
    assert source["created_by"] == owner["user"]["id"]

    paused = api_client.post(
        "/api/v1/sources/pause",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=member_headers,
    )
    assert paused.status_code == 200

    denied = api_client.post(
        "/api/v1/sources/pause",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=peer_headers,
    )
    assert denied.status_code == 403


def test_github_sync_failure_updates_status_without_advancing_cursor(
    api_client, api_app, monkeypatch
):
    headers = _register_and_login(api_client, "github-failure@example.com")
    team, kb = _create_team_and_kb(api_client, headers, "Failure Team")
    source = _create_source(api_client, headers, team["id"], kb["id"]).json()["data"]
    _seed_active_generation(api_app, team["id"])

    with api_app.state.session_factory() as session:
        record = session.get(SourceConnection, source["id"])
        record.sync_cursor = "previous-cursor"
        session.commit()

    requests: list[httpx.Request] = []
    monkeypatch.setattr(
        github_sync,
        "build_github_client",
        lambda _source, token=None: github_sync.GitHubClient(
            transport=_github_transport(requests, fail_auth=True)
        ),
    )

    response = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=headers,
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "SOURCE_AUTH_FAILED"
    with api_app.state.session_factory() as session:
        record = session.get(SourceConnection, source["id"])
        assert record.status == "error"
        assert record.sync_cursor == "previous-cursor"


def test_github_sync_removes_and_moves_documents_missing_from_snapshot(
    api_client, api_app, monkeypatch
):
    headers = _register_and_login(api_client, "github-moves@example.com")
    team, kb = _create_team_and_kb(api_client, headers, "Move Team")
    source = _create_source(api_client, headers, team["id"], kb["id"]).json()["data"]
    _seed_active_generation(api_app, team["id"])
    state = {
        "commit_sha": "commit-sha-1",
        "tree_sha": "tree-sha-1",
        "files": [
            {"path": "docs/guide.md", "type": "blob", "sha": "guide-md", "size": 24},
            {"path": "docs/runbook.txt", "type": "blob", "sha": "runbook-txt", "size": 20},
        ],
    }
    deleted_indexes = []

    async def delete_indexed_document(settings, generation_id, document_id):
        deleted_indexes.append((generation_id, document_id))

    monkeypatch.setattr(
        github_sync,
        "delete_document_from_indexes",
        delete_indexed_document,
    )
    monkeypatch.setattr(
        github_sync,
        "build_github_client",
        lambda _source, token=None: github_sync.GitHubClient(
            transport=_github_transport(
                [],
                commit_sha=state["commit_sha"],
                tree_sha=state["tree_sha"],
                tree_files=state["files"],
            )
        ),
    )

    first = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=headers,
    )
    assert first.status_code == 202

    with api_app.state.session_factory() as session:
        runbook = session.scalar(
            select(Document).where(
                Document.file_name == "acme/handbook/docs/runbook.txt"
            )
        )
        runbook_id = runbook.id
        old_chunks = session.scalars(
            select(ChunkRecord).where(ChunkRecord.document_id == runbook_id)
        ).all()
        assert old_chunks

    state["commit_sha"] = "commit-sha-2"
    state["tree_sha"] = "tree-sha-2"
    state["files"] = [
        {"path": "docs/guide.md", "type": "blob", "sha": "guide-md", "size": 24},
        {"path": "docs/moved.txt", "type": "blob", "sha": "runbook-txt", "size": 20},
    ]

    second = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=headers,
    )

    assert second.status_code == 202
    assert second.json()["data"]["documents_deleted"] == 1
    with api_app.state.session_factory() as session:
        runbook = session.get(Document, runbook_id)
        moved = session.scalar(
            select(Document).where(
                Document.file_name == "acme/handbook/docs/moved.txt"
            )
        )
        assert runbook.doc_status == "deleted"
        assert moved is not None and moved.doc_status == "active"
        disabled = session.scalars(
            select(ChunkRecord).where(ChunkRecord.document_id == runbook_id)
        ).all()
        assert disabled and all(
            chunk.status == "disabled" and chunk.chunk_status == "disabled"
            for chunk in disabled
        )
    assert any(document_id == runbook_id for _, document_id in deleted_indexes)


def test_github_sync_failure_keeps_cursor_and_records_persistent_error(
    api_client, api_app, monkeypatch
):
    headers = _register_and_login(api_client, "github-partial@example.com")
    team, kb = _create_team_and_kb(api_client, headers, "Partial Failure Team")
    source = _create_source(api_client, headers, team["id"], kb["id"]).json()["data"]
    with api_app.state.session_factory() as session:
        record = session.get(SourceConnection, source["id"])
        record.sync_cursor = "previous-cursor"
        session.commit()

    monkeypatch.setattr(
        github_sync,
        "build_github_client",
        lambda _source, token=None: github_sync.GitHubClient(
            transport=_github_transport(
                [],
                commit_sha="commit-sha-2",
                tree_sha="tree-sha-2",
                tree_files=[
                    {
                        "path": "docs/guide.md",
                        "type": "blob",
                        "sha": "guide-md",
                        "size": 24,
                    },
                    {
                        "path": "docs/missing.md",
                        "type": "blob",
                        "sha": "missing-md",
                        "size": 20,
                    },
                ],
                missing_blobs={"missing-md"},
            )
        ),
    )

    response = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=headers,
    )

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "error"
    assert response.json()["data"]["cursor"] == "previous-cursor"
    assert response.json()["data"]["documents_failed"] == 1
    with api_app.state.session_factory() as session:
        record = session.get(SourceConnection, source["id"])
        assert record.status == "error"
        assert record.sync_cursor == "previous-cursor"
        failure = session.scalar(
            select(AuditLog).where(
                AuditLog.team_id == team["id"],
                AuditLog.action == "source.sync.failed",
            )
        )
        assert failure is not None
        details = json.loads(failure.details)
        assert details["error_code"] == "SOURCE_SYNC_FAILED"
        assert details["cursor"] == "previous-cursor"


def test_github_sync_cleanup_failure_leaves_removed_document_active(
    api_client, api_app, monkeypatch
):
    headers = _register_and_login(api_client, "github-cleanup-failure@example.com")
    team, kb = _create_team_and_kb(api_client, headers, "Cleanup Failure Team")
    source = _create_source(api_client, headers, team["id"], kb["id"]).json()["data"]
    _seed_active_generation(api_app, team["id"])
    state = {
        "commit_sha": "commit-sha-1",
        "tree_sha": "tree-sha-1",
        "files": [
            {"path": "docs/runbook.txt", "type": "blob", "sha": "runbook-txt", "size": 20}
        ],
    }
    monkeypatch.setattr(
        github_sync,
        "build_github_client",
        lambda _source, token=None: github_sync.GitHubClient(
            transport=_github_transport(
                [],
                commit_sha=state["commit_sha"],
                tree_sha=state["tree_sha"],
                tree_files=state["files"],
            )
        ),
    )
    first = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=headers,
    )
    assert first.status_code == 202

    with api_app.state.session_factory() as session:
        document = session.scalar(
            select(Document).where(
                Document.file_name == "acme/handbook/docs/runbook.txt"
            )
        )
        document_id = document.id

    async def fail_index_cleanup(settings, generation_id, document_id):
        raise RuntimeError("search index unavailable")

    monkeypatch.setattr(
        github_sync,
        "delete_document_from_indexes",
        fail_index_cleanup,
    )
    state["commit_sha"] = "commit-sha-2"
    state["tree_sha"] = "tree-sha-2"
    state["files"] = []

    second = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=headers,
    )

    assert second.status_code == 202
    assert second.json()["data"]["status"] == "error", second.json()
    assert second.json()["data"]["cursor"] == "commit-sha-1"
    with api_app.state.session_factory() as session:
        document = session.get(Document, document_id)
        assert document.doc_status == "active"
        chunks = session.scalars(
            select(ChunkRecord).where(ChunkRecord.document_id == document_id)
        ).all()
        assert chunks and all(chunk.status == "enabled" for chunk in chunks)


def test_delete_source_soft_deletes_documents_and_removes_indexes(
    api_client, api_app, monkeypatch
):
    headers = _register_and_login(api_client, "github-delete-source@example.com")
    team, kb = _create_team_and_kb(api_client, headers, "Delete Source Team")
    source = _create_source(api_client, headers, team["id"], kb["id"]).json()["data"]
    _seed_active_generation(api_app, team["id"])
    deleted_indexes = []

    async def delete_indexed_document(settings, generation_id, document_id):
        deleted_indexes.append((generation_id, document_id))

    monkeypatch.setattr(
        github_sync,
        "delete_document_from_indexes",
        delete_indexed_document,
    )
    monkeypatch.setattr(
        github_sync,
        "build_github_client",
        lambda _source, token=None: github_sync.GitHubClient(
            transport=_github_transport([])
        ),
    )
    synced = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=headers,
    )
    assert synced.status_code == 202

    with api_app.state.session_factory() as session:
        document_ids = [
            row.id
            for row in session.scalars(
                select(Document).where(Document.source_type == "github")
            ).all()
        ]

    response = api_client.post(
        "/api/v1/sources/delete",
        json={"team_id": team["id"], "source_id": source["id"]},
        headers=headers,
    )

    assert response.status_code == 200
    with api_app.state.session_factory() as session:
        assert session.get(SourceConnection, source["id"]) is None
        documents = [session.get(Document, document_id) for document_id in document_ids]
        assert documents and all(document.doc_status == "deleted" for document in documents)
        chunks = session.scalars(select(ChunkRecord)).all()
        assert chunks and all(
            chunk.status == "disabled" and chunk.chunk_status == "disabled"
            for chunk in chunks
        )
    assert {document_id for _, document_id in deleted_indexes} == set(document_ids)
