from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app.core.config import Settings
from backend.app.db.models import AuditLog, IndexGenerationRecord
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.main import create_app
from backend.app.workers import dispatch as dispatch_module
from backend.tests.api.conftest import admin_headers_for


def _celery_app():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    factory = build_session_factory(engine)
    app = create_app(
        settings=Settings(
            environment="development",
            jwt_secret="test-secret-at-least-32-bytes-long",
            enable_indexing=True,
            task_execution_mode="celery",
        ),
        session_factory=factory,
    )
    return app, factory


def _admin_headers(client):
    return admin_headers_for(client)


def _create_team(client, headers, name="Index Team"):
    response = client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_reindex_generation_inline_returns_generation_and_run(
    api_client, api_app, admin_headers, monkeypatch
):
    team = _create_team(api_client, admin_headers, "Inline Reindex Team")

    def fake_reindex(session, generation_id, settings):
        generation = session.get(IndexGenerationRecord, generation_id)
        generation.status = "active"
        generation.chunk_count = 3
        session.commit()
        return {
            "generation_id": generation_id,
            "passed": True,
            "status": "active",
            "errors": [],
            "checked_chunks": 3,
            "validated_at": generation.validated_at.isoformat()
            if generation.validated_at is not None
            else None,
        }

    monkeypatch.setattr(dispatch_module, "reindex_generation_record", fake_reindex)

    response = api_client.post(
        "/api/v1/generations/reindex",
        json={"team_id": team["id"]},
        headers=admin_headers,
    )

    assert response.status_code == 202, response.text
    payload = response.json()["data"]
    assert payload["generation"]["status"] == "active"
    assert payload["generation"]["chunk_count"] == 3
    assert payload["run"] == {
        "generation_id": payload["generation"]["id"],
        "status": "active",
        "execution_mode": "inline",
        "task_id": None,
        "passed": True,
        "checked_chunks": 3,
        "errors": [],
    }
    with api_app.state.session_factory() as session:
        generation = session.get(IndexGenerationRecord, payload["generation"]["id"])
        assert generation.status == "active"
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.team_id == team["id"],
                AuditLog.action == "generation.reindex",
            )
        )
        assert audit is not None


def test_reindex_generation_queues_celery_task_and_returns_staging(
    monkeypatch,
):
    app, factory = _celery_app()
    calls = []
    monkeypatch.setattr(
        dispatch_module.reindex_generation,
        "apply_async",
        lambda **kwargs: calls.append(kwargs)
        or SimpleNamespace(id="celery-task-1"),
    )

    with TestClient(app) as client:
        headers = _admin_headers(client)
        team = _create_team(client, headers, "Queued Reindex Team")
        response = client.post(
            "/api/v1/generations/reindex",
            json={"team_id": team["id"]},
            headers=headers,
        )

    assert response.status_code == 202, response.text
    payload = response.json()["data"]
    generation_id = payload["generation"]["id"]
    assert payload["generation"]["status"] == "staging"
    assert payload["run"] == {
        "generation_id": generation_id,
        "status": "queued",
        "execution_mode": "celery",
        "task_id": "celery-task-1",
        "passed": None,
        "checked_chunks": 0,
        "errors": [],
    }
    assert calls == [{"args": [generation_id], "retry": False}]
    with factory() as session:
        generation = session.get(IndexGenerationRecord, generation_id)
        assert generation.team_id == team["id"]
        assert generation.status == "staging"


def test_reindex_generation_marks_staging_failed_when_queue_is_unavailable(
    monkeypatch,
):
    app, factory = _celery_app()

    def unavailable(**kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(dispatch_module.reindex_generation, "apply_async", unavailable)

    with TestClient(app) as client:
        headers = _admin_headers(client)
        team = _create_team(client, headers, "Unavailable Reindex Team")
        response = client.post(
            "/api/v1/generations/reindex",
            json={"team_id": team["id"]},
            headers=headers,
        )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "TASK_QUEUE_UNAVAILABLE"
    generation_id = error["details"]["generation_id"]
    with factory() as session:
        generation = session.get(IndexGenerationRecord, generation_id)
        assert generation.status == "failed"
        assert "queue is unavailable" in generation.error_message
        assert "TASK_QUEUE_UNAVAILABLE" in generation.validation_errors
        audit = session.scalar(
            select(AuditLog).where(
                AuditLog.team_id == team["id"],
                AuditLog.action == "generation.reindex.queue_failed",
            )
        )
        assert audit is not None


def test_reindex_generation_requires_team_leader(api_client, api_app, admin_headers):
    team = _create_team(api_client, admin_headers, "Reindex Permission Team")
    created = api_client.post(
        "/api/v1/admin/users/create",
        json={
            "email": "reindex-member@example.com",
            "display_name": "Reindex Member",
            "password": "password-123",
            "team_id": team["id"],
            "role": "member",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    login = api_client.post(
        "/api/v1/auth/login",
        json={"email": "reindex-member@example.com", "password": "password-123"},
    )
    member_headers = {
        "Authorization": "Bearer " + login.json()["data"]["access_token"]
    }

    response = api_client.post(
        "/api/v1/generations/reindex",
        json={"team_id": team["id"]},
        headers=member_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    with api_app.state.session_factory() as session:
        count = session.scalar(
            select(func.count()).select_from(IndexGenerationRecord)
        )
        assert count == 0
