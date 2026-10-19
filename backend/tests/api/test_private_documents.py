import json

from backend.tests.api.conftest import (
    admin_headers_for,
    create_team_as_admin,
    create_user_as_admin,
    login_headers,
)

def test_private_document_requires_owner_or_explicit_grant(api_client):
    admin_headers = admin_headers_for(api_client)
    team = create_team_as_admin(api_client, admin_headers, "Private Team")
    owner = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "private-owner@example.com",
        role="leader",
        display_name="Owner",
    )["user"]
    member = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "private-member@example.com",
        role="member",
        display_name="Member",
    )["user"]
    owner_headers = login_headers(api_client, "private-owner@example.com")
    member_headers = login_headers(api_client, "private-member@example.com")
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Private KB"},
        headers=owner_headers,
    ).json()["data"]
    member_update = api_client.post(
        "/api/v1/kbs/members/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "user_ids": [owner["id"], member["id"]],
        },
        headers=owner_headers,
    )
    assert member_update.status_code == 200, member_update.text
    upload = api_client.post(
        "/api/v1/docs/upload",
        data={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "visibility": "private",
            "metadata": json.dumps(
                {"product": "SecretProduct", "version_values": ["9.9"]}
            ),
        },
        files={"file": ("secret.md", b"# Secret\n\nOwner-only content.")},
        headers=owner_headers,
    ).json()["data"]
    document = upload["document"]

    detail = api_client.get(
        "/api/v1/docs/detail",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=member_headers,
    )
    assert detail.status_code == 404
    listing = api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=member_headers,
    )
    assert listing.json()["data"] == []
    download = api_client.get(
        "/api/v1/docs/download",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=member_headers,
    )
    assert download.status_code == 404

    member_facets = api_client.get(
        "/api/v1/facets",
        params={"team_id": team["id"]},
        headers=member_headers,
    )
    assert member_facets.status_code == 200
    assert member_facets.json()["data"] == {
        "products": [],
        "versions": [],
        "sources": [],
        "knowledge_base_ids": [],
    }

    api_client.post(
        "/api/v1/docs/grants/create",
        json={
            "team_id": team["id"],
            "document_id": document["id"],
            "user_id": member["id"],
        },
        headers=owner_headers,
    )

    granted = api_client.get(
        "/api/v1/docs/detail",
        params={"team_id": team["id"], "document_id": document["id"]},
        headers=member_headers,
    )
    assert granted.status_code == 200
    listing = api_client.get(
        "/api/v1/docs",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=member_headers,
    )
    assert [item["id"] for item in listing.json()["data"]] == [document["id"]]
    granted_facets = api_client.get(
        "/api/v1/facets",
        params={"team_id": team["id"]},
        headers=member_headers,
    )
    assert granted_facets.status_code == 200
    assert granted_facets.json()["data"]["products"] == ["SecretProduct"]
    assert granted_facets.json()["data"]["versions"] == ["9.9"]
    assert granted_facets.json()["data"]["sources"] == ["upload"]
    assert granted_facets.json()["data"]["knowledge_base_ids"] == [kb["id"]]
    assert owner["id"] != member["id"]


def test_viewer_cannot_upload_documents(api_client):
    admin_headers = admin_headers_for(api_client)
    team = create_team_as_admin(api_client, admin_headers, "Viewer Team")
    create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "viewer-owner@example.com",
        role="leader",
        display_name="Owner",
    )
    create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "readonly@example.com",
        role="viewer",
        display_name="Viewer",
    )
    owner_headers = login_headers(api_client, "viewer-owner@example.com")
    viewer_headers = login_headers(api_client, "readonly@example.com")
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Viewer KB"},
        headers=owner_headers,
    ).json()["data"]

    upload = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={"file": ("viewer.md", b"# Viewer\n\nNot allowed.")},
        headers=viewer_headers,
    )

    assert upload.status_code == 403
    assert upload.json()["error"]["code"] == "PERMISSION_DENIED"
