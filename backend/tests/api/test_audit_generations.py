from datetime import datetime, timedelta, timezone

from backend.app.db.models import (
    AuditLog,
    ChunkRecord,
    Document,
    DocumentVersion,
    IndexGenerationRecord,
    KnowledgeBase,
    User,
)


def _admin_session(api_client, api_app):
    login = api_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@techvault.local", "password": "ChangeMe-123!"},
    )
    token = login.json()["data"]["access_token"]
    headers = {"Authorization": "Bearer " + token}
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Audit Team"},
        headers=headers,
    ).json()["data"]
    return headers, team, api_app.state.session_factory


def _seed_generations(session_factory, team_id):
    with session_factory() as session:
        admin = session.query(User).filter(User.email == "admin@techvault.local").one()
        kb = KnowledgeBase(
            team_id=team_id,
            name="Generation KB",
            created_by=admin.id,
        )
        session.add(kb)
        session.flush()
        document = Document(
            knowledge_base_id=kb.id,
            owner_user_id=admin.id,
            file_name="guide.md",
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            document_id=document.id,
            content_fingerprint="fingerprint",
            file_size_bytes=10,
        )
        session.add(version)
        session.flush()

        created = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
        first = IndexGenerationRecord(
            team_id=team_id,
            status="staging",
            chunk_count=1,
            created_at=created,
        )
        second = IndexGenerationRecord(
            team_id=team_id,
            status="staging",
            chunk_count=1,
            created_at=created + timedelta(minutes=1),
        )
        session.add_all([first, second])
        session.flush()
        for generation in (first, second):
            session.add(
                ChunkRecord(
                    document_id=document.id,
                    team_id=team_id,
                    knowledge_base_id=kb.id,
                    owner_user_id=admin.id,
                    content="Grounded content",
                    index_generation=generation.id,
                )
            )
        session.commit()
        return first.id, second.id


def test_generation_validation_activation_rollback_and_audit(api_client, api_app):
    headers, team, session_factory = _admin_session(api_client, api_app)
    first_id, second_id = _seed_generations(session_factory, team["id"])

    listed = api_client.get(
        "/api/v1/generations",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [second_id, first_id]

    validated = api_client.post(
        "/api/v1/generations/validate",
        json={"team_id": team["id"], "generation_id": first_id},
        headers=headers,
    )
    assert validated.status_code == 202
    assert validated.json()["data"]["status"] == "validated"

    validation = api_client.get(
        "/api/v1/generations/validation",
        params={"team_id": team["id"], "generation_id": first_id},
        headers=headers,
    )
    assert validation.status_code == 200
    assert validation.json()["data"]["passed"] is True
    assert validation.json()["data"]["checked_chunks"] == 1

    first_active = api_client.post(
        "/api/v1/generations/activate",
        json={"team_id": team["id"], "generation_id": first_id},
        headers=headers,
    )
    assert first_active.status_code == 202
    assert first_active.json()["data"]["status"] == "active"

    api_client.post(
        "/api/v1/generations/validate",
        json={"team_id": team["id"], "generation_id": second_id},
        headers=headers,
    )
    second_active = api_client.post(
        "/api/v1/generations/activate",
        json={"team_id": team["id"], "generation_id": second_id},
        headers=headers,
    )
    assert second_active.status_code == 202

    rolled_back = api_client.post(
        "/api/v1/generations/rollback",
        json={"team_id": team["id"]},
        headers=headers,
    )
    assert rolled_back.status_code == 202
    assert rolled_back.json()["data"]["id"] == first_id
    assert rolled_back.json()["data"]["status"] == "active"

    audit = api_client.get(
        "/api/v1/audit",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["data"]]
    assert actions.count("generation.activate") == 2
    assert actions[0] == "generation.rollback"

    audit_id = audit.json()["data"][0]["id"]
    detail = api_client.get(
        "/api/v1/audit/detail",
        params={"team_id": team["id"], "audit_id": audit_id},
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["details"]["generation_id"] == first_id


def test_generation_validation_fails_when_chunk_count_does_not_match(api_client, api_app):
    headers, team, session_factory = _admin_session(api_client, api_app)
    with session_factory() as session:
        generation = IndexGenerationRecord(
            team_id=team["id"],
            status="staging",
            chunk_count=2,
        )
        session.add(generation)
        session.commit()
        generation_id = generation.id

    response = api_client.post(
        "/api/v1/generations/validate",
        json={"team_id": team["id"], "generation_id": generation_id},
        headers=headers,
    )

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "failed"
    validation = api_client.get(
        "/api/v1/generations/validation",
        params={"team_id": team["id"], "generation_id": generation_id},
        headers=headers,
    )
    assert validation.status_code == 200
    assert validation.json()["data"]["passed"] is False
    assert validation.json()["data"]["checked_chunks"] == 0


def test_audit_detail_hides_records_from_other_teams(api_client, api_app):
    headers, team, session_factory = _admin_session(api_client, api_app)
    other_team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Other Team"},
        headers=headers,
    ).json()["data"]
    with session_factory() as session:
        admin = session.query(User).filter(User.email == "admin@techvault.local").one()
        audit = AuditLog(
            team_id=other_team["id"],
            actor_id=admin.id,
            action="private.action",
            resource_type="document",
            details="{}",
        )
        session.add(audit)
        session.commit()
        audit_id = audit.id

    response = api_client.get(
        "/api/v1/audit/detail",
        params={"team_id": team["id"], "audit_id": audit_id},
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_audit_reads_require_leader_role(api_client, api_app):
    headers, team, session_factory = _admin_session(api_client, api_app)
    with session_factory() as session:
        admin = session.query(User).filter(User.email == "admin@techvault.local").one()
        audit = AuditLog(
            team_id=team["id"],
            actor_id=admin.id,
            action="document.upload",
            resource_type="document",
            details="{}",
        )
        session.add(audit)
        session.commit()
        audit_id = audit.id

    for role in ("member", "viewer"):
        email = "{0}-audit-reader@example.com".format(role)
        created = api_client.post(
            "/api/v1/admin/users/create",
            json={
                "email": email,
                "display_name": role.title(),
                "password": "password-123",
                "team_id": team["id"],
                "role": role,
            },
            headers=headers,
        )
        assert created.status_code == 201
        login = api_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "password-123"},
        )
        role_headers = {
            "Authorization": "Bearer " + login.json()["data"]["access_token"]
        }

        listed = api_client.get(
            "/api/v1/audit",
            params={"team_id": team["id"]},
            headers=role_headers,
        )
        detail = api_client.get(
            "/api/v1/audit/detail",
            params={"team_id": team["id"], "audit_id": audit_id},
            headers=role_headers,
        )

        assert listed.status_code == 403
        assert listed.json()["error"]["code"] == "PERMISSION_DENIED"
        assert detail.status_code == 403
        assert detail.json()["error"]["code"] == "PERMISSION_DENIED"
