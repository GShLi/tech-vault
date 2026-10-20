from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.models import Document, IngestionRun
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.main import create_app
from backend.app.workers.dispatch import ingest_document, sync_github_source_task
from backend.tests.api.conftest import admin_headers_for


def _celery_client():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    factory = build_session_factory(engine)
    app = create_app(
        settings=Settings(
            environment="development",
            jwt_secret="test-secret-at-least-32-bytes-long",
            task_execution_mode="celery",
        ),
        session_factory=factory,
    )
    return app, factory


def _headers(client, email="async-upload@example.com"):
    return admin_headers_for(client)


def _team_and_kb(client, headers):
    team = client.post(
        "/api/v1/teams/create",
        json={"name": "Async Team"},
        headers=headers,
    ).json()["data"]
    kb = client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Async KB"},
        headers=headers,
    ).json()["data"]
    return team, kb


def test_upload_queues_celery_task_and_returns_building_document(monkeypatch):
    app, factory = _celery_client()
    calls = []
    monkeypatch.setattr(
        ingest_document,
        "apply_async",
        lambda **kwargs: calls.append(kwargs),
    )

    with TestClient(app) as client:
        headers = _headers(client)
        team, kb = _team_and_kb(client, headers)
        response = client.post(
            "/api/v1/docs/upload",
            data={"team_id": team["id"], "kb_id": kb["id"]},
            files={"file": ("queued.md", b"# Queued\n\nBackground ingestion.")},
            headers=headers,
        )

    assert response.status_code == 202, response.text
    data = response.json()["data"]
    assert data["document"]["doc_status"] == "building"
    assert calls == [
        {
            "args": [data["document"]["id"], data["ingestion_run_id"]],
            "retry": False,
        }
    ]
    with factory() as session:
        run = session.get(IngestionRun, data["ingestion_run_id"])
        assert run is not None
        assert run.status == "queued"
        assert run.current_stage == "queued"


def test_upload_marks_run_failed_when_broker_is_unavailable(monkeypatch):
    app, factory = _celery_client()

    def unavailable(**_kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(ingest_document, "apply_async", unavailable)

    with TestClient(app) as client:
        headers = _headers(client, "queue-down@example.com")
        team, kb = _team_and_kb(client, headers)
        response = client.post(
            "/api/v1/docs/upload",
            data={"team_id": team["id"], "kb_id": kb["id"]},
            files={"file": ("queued.md", b"# Queue\n\nUnavailable.")},
            headers=headers,
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "TASK_QUEUE_UNAVAILABLE"
    with factory() as session:
        run = session.query(IngestionRun).one()
        document = session.query(Document).one()
        assert run.status == "failed"
        assert run.error_code == "TASK_QUEUE_UNAVAILABLE"
        assert run.retryable is True
        assert document.doc_status == "failed"


def test_rebuild_and_retry_queue_the_requested_run(monkeypatch):
    app, _factory = _celery_client()
    calls = []
    monkeypatch.setattr(
        ingest_document,
        "apply_async",
        lambda **kwargs: calls.append(kwargs),
    )

    with TestClient(app) as client:
        headers = _headers(client, "async-rebuild@example.com")
        team, kb = _team_and_kb(client, headers)
        upload = client.post(
            "/api/v1/docs/upload",
            data={"team_id": team["id"], "kb_id": kb["id"]},
            files={"file": ("rebuild.md", b"# Rebuild\n\nQueued content.")},
            headers=headers,
        ).json()["data"]

        rebuilt = client.post(
            "/api/v1/docs/rebuild",
            json={"team_id": team["id"], "document_id": upload["document"]["id"]},
            headers=headers,
        )
        with _factory() as session:
            run = session.get(IngestionRun, upload["ingestion_run_id"])
            run.status = "failed"
            run.current_stage = "failed"
            run.error_code = "PROCESSING_ERROR"
            session.commit()
        retried = client.post(
            "/api/v1/ingestions/retry",
            json={"team_id": team["id"], "run_id": upload["ingestion_run_id"]},
            headers=headers,
        )

    assert rebuilt.status_code == 202, rebuilt.text
    assert retried.status_code == 202, retried.text
    assert len(calls) == 3
    assert calls[0]["args"][0] == upload["document"]["id"]
    assert calls[1]["args"][0] == upload["document"]["id"]
    assert calls[1]["args"][1] == rebuilt.json()["data"]["ingestion_run_id"]
    assert calls[2]["args"] == [upload["document"]["id"], upload["ingestion_run_id"]]


def test_retry_rejects_completed_run_without_dispatching(monkeypatch):
    app, factory = _celery_client()
    calls = []
    monkeypatch.setattr(
        ingest_document,
        "apply_async",
        lambda **kwargs: calls.append(kwargs),
    )

    with TestClient(app) as client:
        headers = _headers(client, "async-retry-completed@example.com")
        team, kb = _team_and_kb(client, headers)
        upload = client.post(
            "/api/v1/docs/upload",
            data={"team_id": team["id"], "kb_id": kb["id"]},
            files={"file": ("completed.md", b"# Complete\n\nDone.")},
            headers=headers,
        ).json()["data"]
        with factory() as session:
            run = session.get(IngestionRun, upload["ingestion_run_id"])
            run.status = "completed"
            run.current_stage = "completed"
            session.commit()
        retried = client.post(
            "/api/v1/ingestions/retry",
            json={"team_id": team["id"], "run_id": upload["ingestion_run_id"]},
            headers=headers,
        )

    assert retried.status_code == 409
    assert retried.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"
    assert len(calls) == 1


def test_cancel_rejects_run_after_indexing_has_started(monkeypatch):
    app, factory = _celery_client()
    monkeypatch.setattr(ingest_document, "apply_async", lambda **_kwargs: None)

    with TestClient(app) as client:
        headers = _headers(client, "async-cancel-indexing@example.com")
        team, kb = _team_and_kb(client, headers)
        upload = client.post(
            "/api/v1/docs/upload",
            data={"team_id": team["id"], "kb_id": kb["id"]},
            files={"file": ("indexing.md", b"# Indexing\n\nStarted.")},
            headers=headers,
        ).json()["data"]
        with factory() as session:
            run = session.get(IngestionRun, upload["ingestion_run_id"])
            run.current_stage = "indexing"
            run.status = "queued"
            session.commit()
        cancelled = client.post(
            "/api/v1/ingestions/cancel",
            json={"team_id": team["id"], "run_id": upload["ingestion_run_id"]},
            headers=headers,
        )

    assert cancelled.status_code == 409
    assert cancelled.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"


def test_chunk_regenerate_queues_a_new_ingestion_run(monkeypatch):
    app, factory = _celery_client()
    calls = []
    monkeypatch.setattr(
        ingest_document,
        "apply_async",
        lambda **kwargs: calls.append(kwargs),
    )

    with TestClient(app) as client:
        headers = _headers(client, "async-chunk-regenerate@example.com")
        team, kb = _team_and_kb(client, headers)
        upload = client.post(
            "/api/v1/docs/upload",
            data={"team_id": team["id"], "kb_id": kb["id"]},
            files={"file": ("regenerate.md", b"# Regenerate\n\nQueued content.")},
            headers=headers,
        ).json()["data"]
        regenerated = client.post(
            "/api/v1/chunks/regenerate",
            json={"team_id": team["id"], "document_id": upload["document"]["id"]},
            headers=headers,
        )

    assert regenerated.status_code == 202, regenerated.text
    data = regenerated.json()["data"]
    assert data["status"] == "queued"
    assert len(calls) == 2
    assert calls[1] == {
        "args": [upload["document"]["id"], data["run_id"]],
        "retry": False,
    }
    with factory() as session:
        run = session.get(IngestionRun, data["run_id"])
        assert run is not None
        assert run.status == "queued"
        assert run.current_stage == "queued"


def test_source_sync_queues_celery_task(monkeypatch):
    app, _factory = _celery_client()
    calls = []
    monkeypatch.setattr(
        sync_github_source_task,
        "apply_async",
        lambda **kwargs: calls.append(kwargs),
    )

    with TestClient(app) as client:
        headers = _headers(client, "async-source@example.com")
        team, kb = _team_and_kb(client, headers)
        source = client.post(
            "/api/v1/sources/github/create",
            json={
                "team_id": team["id"],
                "kb_id": kb["id"],
                "repo_url": "https://github.com/acme/queued.git",
            },
            headers=headers,
        ).json()["data"]
        response = client.post(
            "/api/v1/sources/sync",
            json={"team_id": team["id"], "source_id": source["id"]},
            headers=headers,
        )

    assert response.status_code == 202, response.text
    assert response.json()["data"]["status"] == "queued"
    assert calls == [{"args": [source["id"]], "retry": False}]
