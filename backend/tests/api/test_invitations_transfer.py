from sqlalchemy import select

from backend.app.db.models import ChunkRecord, Document, KnowledgeBase, User


def _login(client, email, password="ChangeMe-123!"):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}


def _create_team(client, headers, name):
    response = client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _create_user(client, headers, team_id, email, role="member"):
    response = client.post(
        "/api/v1/admin/users/create",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "password": "password-123",
            "team_id": team_id,
            "role": role,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["user"]


def test_leader_can_invite_and_matching_user_can_accept(api_client):
    admin = _login(api_client, "admin@techvault.local")
    host_team = _create_team(api_client, admin, "Host Team")
    home_team = _create_team(api_client, admin, "Home Team")
    invited_user = _create_user(
        api_client, admin, home_team["id"], "invitee@example.com", role="viewer"
    )

    created = api_client.post(
        "/api/v1/invitations/create",
        json={
            "team_id": host_team["id"],
            "email": "Invitee@Example.com",
            "role": "member",
        },
        headers=admin,
    )
    assert created.status_code == 201
    invitation = created.json()["data"]
    assert invitation["email"] == "invitee@example.com"
    assert invitation["status"] == "pending"
    assert invitation["token"]

    detail = api_client.get(
        "/api/v1/invitations/detail",
        params={"token": invitation["token"]},
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["team_name"] == "Host Team"
    assert detail.json()["data"]["role"] == "member"

    invitee = _login(api_client, "invitee@example.com", "password-123")
    accepted = api_client.post(
        "/api/v1/invitations/accept",
        json={"token": invitation["token"]},
        headers=invitee,
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["team_id"] == host_team["id"]
    assert accepted.json()["data"]["user_id"] == invited_user["id"]
    assert accepted.json()["data"]["role"] == "member"

    me = api_client.get("/api/v1/auth/me", headers=invitee).json()["data"]
    assert host_team["id"] in {item["team_id"] for item in me["memberships"]}


def test_non_leader_cannot_invite_and_wrong_user_cannot_accept(api_client):
    admin = _login(api_client, "admin@techvault.local")
    team = _create_team(api_client, admin, "Secure Team")
    _create_user(api_client, admin, team["id"], "viewer@example.com", role="viewer")
    _create_user(api_client, admin, team["id"], "other@example.com", role="member")
    viewer = _login(api_client, "viewer@example.com", "password-123")

    denied = api_client.post(
        "/api/v1/invitations/create",
        json={"team_id": team["id"], "email": "new@example.com", "role": "member"},
        headers=viewer,
    )
    assert denied.status_code == 403

    invitation = api_client.post(
        "/api/v1/invitations/create",
        json={"team_id": team["id"], "email": "new@example.com", "role": "member"},
        headers=admin,
    ).json()["data"]
    other = _login(api_client, "other@example.com", "password-123")
    mismatch = api_client.post(
        "/api/v1/invitations/accept",
        json={"token": invitation["token"]},
        headers=other,
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "INVITATION_EMAIL_MISMATCH"


def test_leader_can_transfer_only_private_documents(api_client, api_app):
    admin = _login(api_client, "admin@techvault.local")
    team = _create_team(api_client, admin, "Transfer Team")
    source = _create_user(
        api_client, admin, team["id"], "source@example.com", role="member"
    )
    target = _create_user(
        api_client, admin, team["id"], "target@example.com", role="member"
    )

    with api_app.state.session_factory() as session:
        admin_user = session.scalar(
            select(User).where(User.email == "admin@techvault.local")
        )
        kb = KnowledgeBase(
            team_id=team["id"], name="Transfer KB", created_by=admin_user.id
        )
        session.add(kb)
        session.flush()
        private_doc = Document(
            knowledge_base_id=kb.id,
            owner_user_id=source["id"],
            file_name="private.md",
            visibility="private",
        )
        shared_doc = Document(
            knowledge_base_id=kb.id,
            owner_user_id=source["id"],
            file_name="shared.md",
            visibility="team_shared",
        )
        session.add_all([private_doc, shared_doc])
        session.flush()
        session.add(
            ChunkRecord(
                document_id=private_doc.id,
                team_id=team["id"],
                knowledge_base_id=kb.id,
                owner_user_id=source["id"],
                content="private",
            )
        )
        session.add(
            ChunkRecord(
                document_id=shared_doc.id,
                team_id=team["id"],
                knowledge_base_id=kb.id,
                owner_user_id=source["id"],
                content="shared",
            )
        )
        session.commit()
        private_doc_id = private_doc.id
        shared_doc_id = shared_doc.id

    transferred = api_client.post(
        "/api/v1/members/transfer-documents",
        json={
            "team_id": team["id"],
            "from_user_id": source["id"],
            "to_user_id": target["id"],
        },
        headers=admin,
    )
    assert transferred.status_code == 202
    assert transferred.json()["data"]["transferred_documents"] == 1
    assert transferred.json()["data"]["transferred_chunks"] == 1

    with api_app.state.session_factory() as session:
        assert session.get(Document, private_doc_id).owner_user_id == target["id"]
        assert session.get(Document, shared_doc_id).owner_user_id == source["id"]
        private_chunk = session.scalar(
            select(ChunkRecord).where(ChunkRecord.document_id == private_doc_id)
        )
        assert private_chunk.owner_user_id == target["id"]
