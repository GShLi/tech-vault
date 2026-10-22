from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from backend.app.db.models import ChunkRecord, Document
from backend.tests.api.conftest import (
    create_team_as_admin,
    create_user_as_admin,
    login_headers,
)


def _me(client, headers):
    return client.get("/api/v1/auth/me", headers=headers).json()["data"]["user"]


def _setup_team(api_client, admin_headers):
    team = create_team_as_admin(api_client, admin_headers, "Security Team")
    created_headers = {}
    for email, role, display_name in (
        ("member-security@example.com", "member", "Member"),
        ("grantee-security@example.com", "member", "Grantee"),
        ("viewer-security@example.com", "viewer", "Viewer"),
    ):
        create_user_as_admin(
            api_client,
            admin_headers,
            team["id"],
            email,
            role=role,
            display_name=display_name,
        )
        created_headers[email] = login_headers(api_client, email)
    member_headers = created_headers["member-security@example.com"]
    grantee_headers = created_headers["grantee-security@example.com"]
    viewer_headers = created_headers["viewer-security@example.com"]
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Security KB"},
        headers=admin_headers,
    ).json()["data"]
    user_ids = [
        _me(api_client, headers)["id"]
        for headers in (
            admin_headers,
            member_headers,
            grantee_headers,
            viewer_headers,
        )
    ]
    member_update = api_client.post(
        "/api/v1/kbs/members/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "user_ids": user_ids,
        },
        headers=admin_headers,
    )
    assert member_update.status_code == 200, member_update.text
    return team, kb, member_headers, grantee_headers, viewer_headers


def _upload(api_client, headers, team_id, kb_id, file_name, body, visibility):
    response = api_client.post(
        "/api/v1/docs/upload",
        data={
            "team_id": team_id,
            "kb_id": kb_id,
            "visibility": visibility,
        },
        files={"file": (file_name, body)},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()["data"]


def _chunk_id(api_app, document_id):
    with api_app.state.session_factory() as session:
        return session.scalar(
            select(ChunkRecord.id).where(
                ChunkRecord.document_id == document_id,
                ChunkRecord.chunk_level == "child",
            )
        )


def _private_read_paths(team_id, document_id, version_id, chunk_id):
    return [
        ("/api/v1/docs/detail", {"team_id": team_id, "document_id": document_id}),
        ("/api/v1/docs/download", {"team_id": team_id, "document_id": document_id}),
        ("/api/v1/docs/versions", {"team_id": team_id, "document_id": document_id}),
        (
            "/api/v1/docs/version",
            {
                "team_id": team_id,
                "document_id": document_id,
                "version_id": version_id,
            },
        ),
        ("/api/v1/docs/tasks", {"team_id": team_id, "document_id": document_id}),
        ("/api/v1/docs/chunks", {"team_id": team_id, "document_id": document_id}),
        ("/api/v1/chunks", {"team_id": team_id, "document_id": document_id}),
        ("/api/v1/chunks/detail", {"team_id": team_id, "chunk_id": chunk_id}),
        ("/api/v1/chunks/history", {"team_id": team_id, "chunk_id": chunk_id}),
    ]


def test_private_document_requires_owner_or_grant_for_every_read_surface(
    api_client, api_app, admin_headers
):
    team, kb, owner_headers, grantee_headers, _ = _setup_team(
        api_client, admin_headers
    )
    upload = _upload(
        api_client,
        owner_headers,
        team["id"],
        kb["id"],
        "private.md",
        b"# Private\n\nOnly the owner and grantee may read this body.",
        "private",
    )
    document = upload["document"]
    chunk_id = _chunk_id(api_app, document["id"])

    for path, params in _private_read_paths(
        team["id"], document["id"], upload["document_version_id"], chunk_id
    ):
        leader_response = api_client.get(path, params=params, headers=admin_headers)
        grantee_response = api_client.get(path, params=params, headers=grantee_headers)
        assert leader_response.status_code == 404, (path, leader_response.text)
        assert grantee_response.status_code == 404, (path, grantee_response.text)

    leader_list = api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=admin_headers,
    )
    grantee_list = api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=grantee_headers,
    )
    assert leader_list.json()["data"] == []
    assert grantee_list.json()["data"] == []

    denied_url = api_client.get(
        "/api/v1/docs/download-url",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=grantee_headers,
    )
    assert denied_url.status_code == 404
    leader_denied_url = api_client.get(
        "/api/v1/docs/download-url",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=admin_headers,
    )
    assert leader_denied_url.status_code == 404

    granted = api_client.post(
        "/api/v1/docs/grants/create",
        json={
            "team_id": team["id"],
            "document_id": document["id"],
            "user_id": _me(api_client, grantee_headers)["id"],
        },
        headers=owner_headers,
    )
    assert granted.status_code == 201, granted.text

    for path, params in _private_read_paths(
        team["id"], document["id"], upload["document_version_id"], chunk_id
    ):
        response = api_client.get(path, params=params, headers=grantee_headers)
        assert response.status_code == 200, (path, response.text)

    local_url = api_client.get(
        "/api/v1/docs/download-url",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=grantee_headers,
    )
    assert local_url.status_code == 503
    assert local_url.json()["error"]["code"] == "STORAGE_PRESIGN_UNAVAILABLE"

    grantee_docs = api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=grantee_headers,
    )
    assert [row["id"] for row in grantee_docs.json()["data"]] == [document["id"]]
    grantee_grants = api_client.get(
        "/api/v1/docs/grants",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=grantee_headers,
    )
    assert grantee_grants.status_code == 403


def test_private_document_management_requires_owner(
    api_client, api_app, admin_headers
):
    team, kb, owner_headers, _, _ = _setup_team(api_client, admin_headers)
    upload = _upload(
        api_client,
        owner_headers,
        team["id"],
        kb["id"],
        "owned.md",
        b"# Owned\n\nOwner-managed document.",
        "private",
    )
    document = upload["document"]

    leader_update = api_client.post(
        "/api/v1/docs/update",
        json={"team_id": team["id"], "document_id": document["id"], "product": "Hijacked"},
        headers={**admin_headers, "If-Match": str(document["version"])},
    )
    assert leader_update.status_code == 404
    leader_delete = api_client.post(
        "/api/v1/docs/delete",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=admin_headers,
    )
    assert leader_delete.status_code == 404

    owner_update = api_client.post(
        "/api/v1/docs/update",
        json={"team_id": team["id"], "document_id": document["id"], "product": "TechVault"},
        headers={**owner_headers, "If-Match": str(document["version"])},
    )
    assert owner_update.status_code == 200, owner_update.text
    updated = owner_update.json()["data"]
    assert updated["product"] == "TechVault"

    owner_delete = api_client.post(
        "/api/v1/docs/delete",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=owner_headers,
    )
    assert owner_delete.status_code == 202, owner_delete.text
    owner_restore = api_client.post(
        "/api/v1/docs/restore",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=owner_headers,
    )
    assert owner_restore.status_code == 202, owner_restore.text
    owner_rebuild = api_client.post(
        "/api/v1/docs/rebuild",
        json={"team_id": team["id"], "document_id": document["id"]},
        headers=owner_headers,
    )
    assert owner_rebuild.status_code == 202, owner_rebuild.text


def test_shared_document_management_and_upload_roles(api_client, api_app, admin_headers):
    team, kb, member_headers, _, viewer_headers = _setup_team(
        api_client, admin_headers
    )
    shared = _upload(
        api_client,
        admin_headers,
        team["id"],
        kb["id"],
        "shared.md",
        b"# Shared\n\nLeader-managed team knowledge.",
        "team_shared",
    )
    document = shared["document"]
    chunk_id = _chunk_id(api_app, document["id"])

    member_update = api_client.post(
        "/api/v1/docs/update",
        json={"team_id": team["id"], "document_id": document["id"], "product": "Nope"},
        headers={**member_headers, "If-Match": str(document["version"])},
    )
    assert member_update.status_code == 403
    viewer_update = api_client.post(
        "/api/v1/docs/update",
        json={"team_id": team["id"], "document_id": document["id"], "product": "Nope"},
        headers={**viewer_headers, "If-Match": str(document["version"])},
    )
    assert viewer_update.status_code == 403

    leader_update = api_client.post(
        "/api/v1/docs/update",
        json={"team_id": team["id"], "document_id": document["id"], "product": "Allowed"},
        headers={**admin_headers, "If-Match": str(document["version"])},
    )
    assert leader_update.status_code == 200, leader_update.text

    member_chunk_update = api_client.post(
        "/api/v1/chunks/update",
        json={"team_id": team["id"], "chunk_id": chunk_id, "content": "Nope"},
        headers={**member_headers, "If-Match": "1"},
    )
    viewer_chunk_disable = api_client.post(
        "/api/v1/chunks/disable",
        json={"team_id": team["id"], "chunk_ids": [chunk_id]},
        headers=viewer_headers,
    )
    assert member_chunk_update.status_code == 403
    assert viewer_chunk_disable.status_code == 403

    viewer_upload = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={"file": ("viewer.md", b"# Viewer\n\nDenied.")},
        headers=viewer_headers,
    )
    assert viewer_upload.status_code == 403


def test_chunk_mutations_follow_document_ownership(api_client, api_app, admin_headers):
    team, kb, owner_headers, other_member_headers, _ = _setup_team(
        api_client, admin_headers
    )
    upload = _upload(
        api_client,
        owner_headers,
        team["id"],
        kb["id"],
        "owner-chunks.md",
        b"# Chunk\n\nOwner editable content.",
        "private",
    )
    chunk_id = _chunk_id(api_app, upload["document"]["id"])
    with api_app.state.session_factory() as session:
        chunk_version = session.get(ChunkRecord, chunk_id).version

    hidden_history = api_client.get(
        "/api/v1/chunks/history",
        params={"team_id": team["id"], "chunk_id": chunk_id},
        headers=other_member_headers,
    )
    hidden_disable = api_client.post(
        "/api/v1/chunks/disable",
        json={"team_id": team["id"], "chunk_ids": [chunk_id]},
        headers=other_member_headers,
    )
    assert hidden_history.status_code == 404
    assert hidden_disable.status_code == 404

    updated = api_client.post(
        "/api/v1/chunks/update",
        json={"team_id": team["id"], "chunk_id": chunk_id, "content": "Owner revised content."},
        headers={**owner_headers, "If-Match": str(chunk_version)},
    )
    assert updated.status_code == 200, updated.text
    disabled = api_client.post(
        "/api/v1/chunks/disable",
        json={"team_id": team["id"], "chunk_ids": [chunk_id]},
        headers=owner_headers,
    )
    assert disabled.status_code == 200, disabled.text
    enabled = api_client.post(
        "/api/v1/chunks/enable",
        json={"team_id": team["id"], "chunk_ids": [chunk_id]},
        headers=owner_headers,
    )
    assert enabled.status_code == 200, enabled.text
    regenerated = api_client.post(
        "/api/v1/chunks/regenerate",
        json={"team_id": team["id"], "document_id": upload["document"]["id"]},
        headers=owner_headers,
    )
    assert regenerated.status_code == 202, regenerated.text
    history = api_client.get(
        "/api/v1/chunks/history",
        params={"team_id": team["id"], "chunk_id": chunk_id},
        headers=owner_headers,
    )
    assert history.status_code == 200
    assert history.json()["data"][0]["new_content"] == "Owner revised content."


def test_ingestion_endpoints_respect_private_document_acl(
    api_client, admin_headers
):
    team, kb, owner_headers, _, _ = _setup_team(api_client, admin_headers)
    upload = _upload(
        api_client,
        owner_headers,
        team["id"],
        kb["id"],
        "private-run.md",
        b"# Private Run\n\nTask data is private too.",
        "private",
    )
    run_id = upload["ingestion_run_id"]

    listing = api_client.get(
        "/api/v1/ingestions",
        params={"team_id": team["id"]},
        headers=admin_headers,
    )
    detail = api_client.get(
        "/api/v1/ingestions/detail",
        params={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )
    events = api_client.get(
        "/api/v1/ingestions/events",
        params={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )
    retry = api_client.post(
        "/api/v1/ingestions/retry",
        json={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )
    cancel = api_client.post(
        "/api/v1/ingestions/cancel",
        json={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )
    assert listing.json()["data"] == []
    assert detail.status_code == 404
    assert events.status_code == 404
    assert retry.status_code == 404
    assert cancel.status_code == 404


def test_document_detail_does_not_expose_server_source_path(
    api_client, api_app, admin_headers, monkeypatch, tmp_path
):
    monkeypatch.setenv("TECHVAULT_UPLOAD_DIR", str(tmp_path / "uploads"))
    team, kb, member_headers, _, _ = _setup_team(api_client, admin_headers)
    upload = _upload(
        api_client,
        member_headers,
        team["id"],
        kb["id"],
        "logical-name.md",
        b"# Logical\n\nSafe metadata.",
        "team_shared",
    )
    document_id = upload["document"]["id"]
    with api_app.state.session_factory() as session:
        stored_uri = session.get(Document, document_id).source_uri
    assert stored_uri and str(tmp_path) in stored_uri

    detail = api_client.get(
        "/api/v1/docs/detail",
        params={"team_id": team["id"], "document_id": document_id},
        headers=member_headers,
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["source_uri"] == "logical-name.md"
    assert str(tmp_path) not in detail.text


def test_download_url_returns_backend_configured_s3_presigned_url(
    api_client, api_app, admin_headers
):
    team, kb, owner_headers, _, _ = _setup_team(api_client, admin_headers)
    upload = _upload(
        api_client,
        owner_headers,
        team["id"],
        kb["id"],
        "signed.md",
        b"# Signed\n\nS3 object content.",
        "team_shared",
    )
    document_id = upload["document"]["id"]
    object_uri = "s3://techvault/docs/signed.md"
    with api_app.state.session_factory() as session:
        session.get(Document, document_id).source_uri = object_uri
        session.commit()
    api_app.state.settings = replace(
        api_app.state.settings,
        minio_url="https://minio.example.test",
        minio_public_url="https://downloads.example.test",
        minio_access_key="test-access",
        minio_secret_key="test-secret",
        minio_bucket="techvault",
        s3_region="eu-west-1",
        download_url_ttl_seconds=137,
    )

    response = api_client.get(
        "/api/v1/docs/download-url",
        params={
            "team_id": team["id"],
            "document_id": document_id,
            "expires_in": 99999,
        },
        headers=owner_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["expires_in"] == 137
    parsed = urlsplit(payload["url"])
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "downloads.example.test"
    assert parsed.path == "/techvault/docs/signed.md"
    assert query["X-Amz-Expires"] == ["137"]
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Credential"][0].startswith("test-access/")
    assert "/eu-west-1/s3/aws4_request" in query["X-Amz-Credential"][0]
    assert query["X-Amz-SignedHeaders"] == ["host"]
    assert len(query["X-Amz-Signature"][0]) == 64
    assert object_uri not in response.text


def test_download_url_rejects_grant_without_kb_membership(
    api_client, api_app, admin_headers
):
    team, kb, owner_headers, _, _ = _setup_team(api_client, admin_headers)
    outside = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "outside-kb@example.com",
        role="member",
        display_name="Outside KB",
    )["user"]
    outside_headers = login_headers(api_client, "outside-kb@example.com")
    upload = _upload(
        api_client,
        owner_headers,
        team["id"],
        kb["id"],
        "kb-scoped.md",
        b"# KB Scoped\n\nOnly KB members may receive a URL.",
        "private",
    )
    document = upload["document"]
    granted = api_client.post(
        "/api/v1/docs/grants/create",
        json={
            "team_id": team["id"],
            "document_id": document["id"],
            "user_id": outside["id"],
        },
        headers=owner_headers,
    )
    assert granted.status_code == 201, granted.text
    with api_app.state.session_factory() as session:
        session.get(Document, document["id"]).source_uri = "s3://techvault/kb-scoped.md"
        session.commit()

    response = api_client.get(
        "/api/v1/docs/download-url",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=outside_headers,
    )

    assert response.status_code == 404
