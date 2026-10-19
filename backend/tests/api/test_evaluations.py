import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.api.v1 import evaluations as evaluations_module
from backend.app.core.config import Settings
from backend.app.db.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    IndexGenerationRecord,
    ModelCall,
    ModelProvider,
    Team,
    User,
)
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.main import create_app
from backend.app.rag.answer.service import AnswerResult
from backend.app.rag.domain.models import RetrievedChunk, SearchResult
from backend.app.workers import dispatch as dispatch_module
from backend.tests.api.conftest import create_user_as_admin, login_headers


def _create_dataset(api_client, api_app, headers):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Evaluation Team"},
        headers=headers,
    ).json()["data"]
    dataset = api_client.post(
        "/api/v1/evals/datasets/create",
        json={"team_id": team["id"], "name": "Golden Set"},
        headers=headers,
    ).json()["data"]
    with api_app.state.session_factory() as session:
        session.add(
            EvaluationCase(
                dataset_id=dataset["id"],
                query_id="q1",
                query_type="concept",
                query="What is RAG?",
                relevant_chunk_ids='["chunk-1"]',
                relevance='{"chunk-1":1}',
            )
        )
        db_dataset = session.get(EvaluationDataset, dataset["id"])
        db_dataset.case_count = 1
        session.commit()
    return team, dataset


def _create_evaluation_provider(
    client,
    headers,
    team_id,
    *,
    model_id="model-a",
):
    response = client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team_id,
            "name": "Evaluation Provider",
            "provider_type": "openai_chat_completions",
            "base_url": "http://evaluation-provider.test/v1",
            "api_key": "sk-evaluation-secret",
            "model_ids": [model_id],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    provider = response.json()["data"]
    deployment_policy = client.post(
        "/api/v1/admin/model-policy/update",
        json={
            "mode": "external_allowed",
            "allowed_provider_ids": [provider["id"]],
            "max_data_classification": "internal",
        },
        headers=headers,
    )
    assert deployment_policy.status_code == 200, deployment_policy.text
    team_policy = client.post(
        "/api/v1/model-policy/update",
        json={
            "team_id": team_id,
            "mode": "external_allowed",
            "allowed_provider_ids": [provider["id"]],
            "max_data_classification": "internal",
        },
        headers=headers,
    )
    assert team_policy.status_code == 200, team_policy.text
    return provider


def _create_run(api_app, dataset, status="running"):
    with api_app.state.session_factory() as session:
        admin_id = session.scalar(select(User.id).where(User.is_super_admin.is_(True)))
        run = EvaluationRun(
            dataset_id=dataset["id"],
            engine_mode="dual_engine",
            status=status,
            created_by=admin_id,
        )
        session.add(run)
        session.commit()
        return run.id


def _add_active_generation(api_app, team_id):
    with api_app.state.session_factory() as session:
        session.add(IndexGenerationRecord(team_id=team_id, status="active"))
        session.commit()


def _install_evaluation_provider_stack(monkeypatch):
    captured = {}

    class Adapter:
        def __init__(self, **kwargs):
            self.provider_id = kwargs["provider_id"]
            self.model_id = kwargs["model_id"]
            self.route = "openai_chat_completions"

        def generate(self, *, question, chunks, max_chunks):
            captured["generate"] = {
                "question": question,
                "chunk_ids": [chunk.chunk_id for chunk in chunks],
            }
            return AnswerResult(
                text="Provider evaluation answer [c1].",
                status="completed",
                citation_chunk_ids=("chunk-1",),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
            )

    def build_adapter(**kwargs):
        captured["adapter"] = kwargs
        return Adapter(**kwargs)

    class Retriever:
        async def search(self, request):
            return SearchResult(
                chunks=[
                    RetrievedChunk(
                        chunk_id="chunk-1",
                        document_version_id="version-1",
                        content="Grounded evidence.",
                        fused_rank=1,
                    )
                ],
                stage_latency={},
                degraded=False,
                trace_id="trace-evaluation-provider",
            )

    monkeypatch.setattr(
        evaluations_module,
        "build_provider_adapter",
        build_adapter,
    )
    monkeypatch.setattr(
        evaluations_module.EmbeddingClient,
        "embed",
        lambda self, texts: [[0.1]],
    )
    monkeypatch.setattr(
        evaluations_module.RerankerClient,
        "rerank",
        lambda self, query, chunks, top_n: list(chunks),
    )
    monkeypatch.setattr(
        evaluations_module,
        "build_retriever",
        lambda *args: Retriever(),
    )
    return captured


def _sse_events(body):
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append((event, json.loads(data)))
    return events


def _celery_app():
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


def test_start_run_persists_real_evaluation_result(
    api_client, api_app, admin_headers, monkeypatch
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    provider = _create_evaluation_provider(
        api_client, admin_headers, team["id"]
    )

    def fake_collect(*_args, **_kwargs):
        return {
            "metrics": {
                "case_count": 1,
                "recall_at_10": 1.0,
                "mrr": 1.0,
                "ndcg_at_10": 1.0,
            },
            "report": {"cases": [{"query_id": "q1", "ranked_chunk_ids": ["chunk-1"]}]},
        }

    monkeypatch.setattr(
        evaluations_module,
        "_collect_evaluation_result",
        fake_collect,
    )
    response = api_client.post(
        "/api/v1/evals/runs/start",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "provider_id": provider["id"],
            "model_id": "model-a",
        },
        headers=admin_headers,
    )

    assert response.status_code == 202
    payload = response.json()["data"]
    assert payload["status"] == "succeeded"
    assert payload["provider_id"] == provider["id"]
    assert payload["model_id"] == "model-a"
    with api_app.state.session_factory() as session:
        run = session.get(EvaluationRun, payload["id"])
        assert run.provider_id == provider["id"]
        assert run.model_id == "model-a"
        result = session.scalar(
            select(EvaluationResult).where(EvaluationResult.run_id == payload["id"])
        )
        assert result is not None
        assert '"recall_at_10":1.0' in result.metrics
    listed = api_client.get(
        "/api/v1/evals/runs",
        params={"team_id": team["id"], "dataset_id": dataset["id"]},
        headers=admin_headers,
    ).json()["data"][0]
    assert listed["provider_id"] == provider["id"]
    assert listed["model_id"] == "model-a"
    detail = api_client.get(
        "/api/v1/evals/runs/detail",
        params={"team_id": team["id"], "run_id": payload["id"]},
        headers=admin_headers,
    ).json()["data"]
    assert detail["provider_id"] == provider["id"]
    assert detail["model_id"] == "model-a"


def test_start_run_failure_is_persisted(
    api_client, api_app, admin_headers, monkeypatch
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    provider = _create_evaluation_provider(
        api_client, admin_headers, team["id"]
    )

    def fail_collect(*_args, **_kwargs):
        raise RuntimeError("retrieval stack unavailable")

    monkeypatch.setattr(
        evaluations_module,
        "_collect_evaluation_result",
        fail_collect,
    )
    response = api_client.post(
        "/api/v1/evals/runs/start",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "provider_id": provider["id"],
            "model_id": "model-a",
        },
        headers=admin_headers,
    )

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "failed"
    report = api_client.get(
        "/api/v1/evals/runs/report",
        params={"team_id": team["id"], "run_id": response.json()["data"]["id"]},
        headers=admin_headers,
    )
    assert report.status_code == 200
    assert report.json()["data"]["report"]["error"] == "retrieval stack unavailable"


def test_start_run_does_not_overwrite_concurrent_cancellation(
    api_client, api_app, admin_headers, monkeypatch
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    provider = _create_evaluation_provider(
        api_client, admin_headers, team["id"]
    )

    def cancel_during_execution(_session, run, *_args, **_kwargs):
        with api_app.state.session_factory() as cancel_session:
            cancelled = cancel_session.get(EvaluationRun, run.id)
            cancelled.status = "cancelled"
            cancel_session.commit()
        return {"metrics": {"case_count": 1}, "report": {"cases": []}}

    monkeypatch.setattr(
        evaluations_module,
        "_collect_evaluation_result",
        cancel_during_execution,
    )
    response = api_client.post(
        "/api/v1/evals/runs/start",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "provider_id": provider["id"],
            "model_id": "model-a",
        },
        headers=admin_headers,
    )

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "cancelled"
    report = api_client.get(
        "/api/v1/evals/runs/report",
        params={"team_id": team["id"], "run_id": response.json()["data"]["id"]},
        headers=admin_headers,
    )
    assert report.json()["data"]["status"] == "cancelled"
    assert report.json()["data"]["metrics"] == {}


def test_start_run_persists_release_gate_against_baseline(
    api_client, api_app, admin_headers, monkeypatch
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    provider = _create_evaluation_provider(
        api_client, admin_headers, team["id"]
    )
    with api_app.state.session_factory() as session:
        admin_id = session.scalar(select(User.id).where(User.is_super_admin.is_(True)))
        baseline = EvaluationRun(
            dataset_id=dataset["id"],
            engine_mode="dual_engine",
            status="succeeded",
            created_by=admin_id,
        )
        session.add(baseline)
        session.flush()
        session.add(
            EvaluationResult(
                run_id=baseline.id,
                metrics='{"recall_at_20":0.9,"ndcg_at_10":0.9,"citation_accuracy":0.9,"groundedness":0.9}',
                report="{}",
            )
        )
        session.commit()
        baseline_id = baseline.id

    monkeypatch.setattr(
        evaluations_module,
        "_collect_evaluation_result",
        lambda *args: {
            "metrics": {
                "case_count": 1,
                "permission_leakage_count": 0,
                "recall_at_20": 0.8,
                "ndcg_at_10": 0.95,
                "citation_accuracy": 0.85,
                "groundedness": 0.9,
                "latency_p95_ms": 120.0,
            },
            "report": {"cases": []},
        },
    )
    response = api_client.post(
        "/api/v1/evals/runs/start",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "provider_id": provider["id"],
            "model_id": "model-a",
            "baseline_run_id": baseline_id,
        },
        headers=admin_headers,
    )

    assert response.status_code == 202
    report = api_client.get(
        "/api/v1/evals/runs/report",
        params={"team_id": team["id"], "run_id": response.json()["data"]["id"]},
        headers=admin_headers,
    )
    gate = report.json()["data"]["report"]["release_gate"]
    assert gate["passed"] is False
    assert "recall_at_20" in gate["failed_checks"]
    assert "citation_accuracy" in gate["failed_checks"]


def test_start_run_rejects_missing_required_body_fields(
    api_client, admin_headers
):
    response = api_client.post(
        "/api/v1/evals/runs/start",
        json={"team_id": "team-id"},
        headers=admin_headers,
    )

    assert response.status_code == 422


def test_start_run_requires_provider_and_model(api_client, admin_headers):
    response = api_client.post(
        "/api/v1/evals/runs/start",
        json={"team_id": "team-id", "dataset_id": "dataset-id"},
        headers=admin_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_start_run_rejects_missing_provider(
    api_client, api_app, admin_headers
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)

    response = api_client.post(
        "/api/v1/evals/runs/start",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "provider_id": "01JPROVIDER000000000000001",
            "model_id": "model-a",
        },
        headers=admin_headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["message"] == "Provider was not found."


def test_start_run_uses_selected_provider_and_persists_model_call(
    api_client, api_app, admin_headers, monkeypatch
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    provider = _create_evaluation_provider(
        api_client, admin_headers, team["id"]
    )
    _add_active_generation(api_app, team["id"])
    captured = _install_evaluation_provider_stack(monkeypatch)

    response = api_client.post(
        "/api/v1/evals/runs/start",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "provider_id": provider["id"],
            "model_id": "model-a",
        },
        headers=admin_headers,
    )

    assert response.status_code == 202, response.text
    payload = response.json()["data"]
    assert payload["status"] == "succeeded"
    assert captured["adapter"]["provider_id"] == provider["id"]
    assert captured["adapter"]["model_id"] == "model-a"
    assert captured["adapter"]["api_key"] == "sk-evaluation-secret"
    assert captured["generate"] == {
        "question": "What is RAG?",
        "chunk_ids": ["chunk-1"],
    }
    report_response = api_client.get(
        "/api/v1/evals/runs/report",
        params={"team_id": team["id"], "run_id": payload["id"]},
        headers=admin_headers,
    )
    report = report_response.json()["data"]
    assert report["provider_id"] == provider["id"]
    assert report["model_id"] == "model-a"
    assert report["report"]["provider_id"] == provider["id"]
    assert report["report"]["model_id"] == "model-a"
    with api_app.state.session_factory() as session:
        model_call = session.scalar(
            select(ModelCall).where(ModelCall.purpose == "answer")
        )
        assert model_call is not None
        assert model_call.provider_id == provider["id"]
        assert model_call.model_id == "model-a"
        assert "sk-evaluation-secret" not in model_call.request_id


def test_start_run_fails_when_provider_credentials_cannot_be_decrypted(
    api_client, api_app, admin_headers
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    provider = _create_evaluation_provider(
        api_client, admin_headers, team["id"]
    )
    _add_active_generation(api_app, team["id"])
    with api_app.state.session_factory() as session:
        stored = session.get(ModelProvider, provider["id"])
        assert stored is not None
        stored.api_key_encrypted = "not-a-valid-fernet-token"
        session.commit()

    response = api_client.post(
        "/api/v1/evals/runs/start",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "provider_id": provider["id"],
            "model_id": "model-a",
        },
        headers=admin_headers,
    )

    assert response.status_code == 202
    payload = response.json()["data"]
    assert payload["status"] == "failed"
    report = api_client.get(
        "/api/v1/evals/runs/report",
        params={"team_id": team["id"], "run_id": payload["id"]},
        headers=admin_headers,
    ).json()["data"]
    assert report["provider_id"] == provider["id"]
    assert report["model_id"] == "model-a"
    assert report["report"]["error_code"] == "RESOURCE_STATE_CONFLICT"
    assert report["report"]["error"] == "Provider credentials are unavailable."


def test_start_run_celery_mode_queues_shared_dispatch(monkeypatch):
    app, factory = _celery_app()
    calls = []
    monkeypatch.setattr(
        dispatch_module.run_evaluation,
        "apply_async",
        lambda **kwargs: calls.append(kwargs)
        or SimpleNamespace(id="evaluation-task-1"),
    )

    with TestClient(app) as client:
        headers = login_headers(client, "admin@techvault.local", "ChangeMe-123!")
        team = client.post(
            "/api/v1/teams/create",
            json={"name": "Queued Evaluation Team"},
            headers=headers,
        ).json()["data"]
        dataset = client.post(
            "/api/v1/evals/datasets/create",
            json={"team_id": team["id"], "name": "Queued Golden Set"},
            headers=headers,
        ).json()["data"]
        provider = _create_evaluation_provider(
            client,
            headers,
            team["id"],
        )
        with factory() as session:
            session.add(
                EvaluationCase(
                    dataset_id=dataset["id"],
                    query_id="q1",
                    query_type="concept",
                    query="What is RAG?",
                    relevant_chunk_ids='["chunk-1"]',
                    relevance='{"chunk-1":1}',
                )
            )
            db_dataset = session.get(EvaluationDataset, dataset["id"])
            db_dataset.case_count = 1
            session.commit()

        response = client.post(
            "/api/v1/evals/runs/start",
            json={
                "team_id": team["id"],
                "dataset_id": dataset["id"],
                "provider_id": provider["id"],
                "model_id": "model-a",
                "judge_mode": "rules",
            },
            headers=headers,
        )

    assert response.status_code == 202, response.text
    payload = response.json()["data"]
    assert payload["status"] == "queued"
    assert calls == [
        {
            "args": [payload["id"], "rules", {}],
            "retry": False,
        }
    ]
    with factory() as session:
        run = session.get(EvaluationRun, payload["id"])
        assert run.status == "queued"
        assert run.provider_id == provider["id"]
        assert run.model_id == "model-a"


def test_start_run_returns_503_when_evaluation_queue_is_unavailable(monkeypatch):
    app, factory = _celery_app()

    def unavailable(**_kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(
        dispatch_module.run_evaluation,
        "apply_async",
        unavailable,
    )

    with TestClient(app) as client:
        headers = login_headers(client, "admin@techvault.local", "ChangeMe-123!")
        team = client.post(
            "/api/v1/teams/create",
            json={"name": "Unavailable Evaluation Team"},
            headers=headers,
        ).json()["data"]
        dataset = client.post(
            "/api/v1/evals/datasets/create",
            json={"team_id": team["id"], "name": "Unavailable Golden Set"},
            headers=headers,
        ).json()["data"]
        provider = _create_evaluation_provider(
            client,
            headers,
            team["id"],
        )
        with factory() as session:
            session.add(
                EvaluationCase(
                    dataset_id=dataset["id"],
                    query_id="q1",
                    query_type="concept",
                    query="What is RAG?",
                    relevant_chunk_ids='["chunk-1"]',
                    relevance='{"chunk-1":1}',
                )
            )
            db_dataset = session.get(EvaluationDataset, dataset["id"])
            db_dataset.case_count = 1
            session.commit()

        response = client.post(
            "/api/v1/evals/runs/start",
            json={
                "team_id": team["id"],
                "dataset_id": dataset["id"],
                "provider_id": provider["id"],
                "model_id": "model-a",
            },
            headers=headers,
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "TASK_QUEUE_UNAVAILABLE"
    with factory() as session:
        run = session.query(EvaluationRun).one()
        assert run.status == "failed"
        result = session.query(EvaluationResult).one()
        assert "TASK_QUEUE_UNAVAILABLE" in result.report


def test_execute_record_persists_failure_without_starlette_request(
    api_app, monkeypatch
):
    with api_app.state.session_factory() as session:
        admin = session.scalar(select(User).where(User.is_super_admin.is_(True)))
        team_record = Team(name="Direct Evaluation Team", created_by=admin.id)
        session.add(team_record)
        session.flush()
        dataset_record = EvaluationDataset(
            team_id=team_record.id,
            name="Direct Golden Set",
            created_by=admin.id,
        )
        session.add(dataset_record)
        session.flush()
        session.add(
            EvaluationCase(
                dataset_id=dataset_record.id,
                query_id="q1",
                query_type="concept",
                query="What is RAG?",
                relevant_chunk_ids='["chunk-1"]',
                relevance='{"chunk-1":1}',
            )
        )
        run = EvaluationRun(
            dataset_id=dataset_record.id,
            engine_mode="dual_engine",
            status="queued",
            created_by=admin.id,
        )
        session.add(run)
        session.commit()
        run_id = run.id

    def fail_collection(*_args, **_kwargs):
        raise RuntimeError("retrieval stack unavailable")

    monkeypatch.setattr(
        evaluations_module,
        "_collect_evaluation_result",
        fail_collection,
    )
    with api_app.state.session_factory() as session:
        result = evaluations_module.execute_evaluation_run_record(
            session,
            run_id,
            api_app.state.settings,
            "rules",
            {},
        )
        assert result["status"] == "failed"

    with api_app.state.session_factory() as session:
        assert session.get(EvaluationRun, run_id).status == "failed"
        persisted = session.scalar(
            select(EvaluationResult).where(EvaluationResult.run_id == run_id)
        )
        assert persisted is not None
        assert "retrieval stack unavailable" in persisted.report


def test_execute_record_preserves_cancellation_from_concurrent_session(
    api_app, monkeypatch
):
    with api_app.state.session_factory() as session:
        admin = session.scalar(select(User).where(User.is_super_admin.is_(True)))
        team_record = Team(name="Cancelled Evaluation Team", created_by=admin.id)
        session.add(team_record)
        session.flush()
        dataset_record = EvaluationDataset(
            team_id=team_record.id,
            name="Cancelled Golden Set",
            created_by=admin.id,
        )
        session.add(dataset_record)
        session.flush()
        session.add(
            EvaluationCase(
                dataset_id=dataset_record.id,
                query_id="q1",
                query_type="concept",
                query="What is RAG?",
                relevant_chunk_ids='["chunk-1"]',
                relevance='{"chunk-1":1}',
            )
        )
        run = EvaluationRun(
            dataset_id=dataset_record.id,
            engine_mode="dual_engine",
            status="queued",
            created_by=admin.id,
        )
        session.add(run)
        session.commit()
        run_id = run.id

    def cancel_during_collection(_session, run, *_args, **_kwargs):
        with api_app.state.session_factory() as cancel_session:
            cancelled = cancel_session.get(EvaluationRun, run.id)
            cancelled.status = "cancelled"
            cancel_session.commit()
        return {"metrics": {"case_count": 1}, "report": {"cases": []}}

    monkeypatch.setattr(
        evaluations_module,
        "_collect_evaluation_result",
        cancel_during_collection,
    )
    with api_app.state.session_factory() as session:
        result = evaluations_module.execute_evaluation_run_record(
            session,
            run_id,
            api_app.state.settings,
            "rules",
            {},
        )
        assert result["status"] == "cancelled"

    with api_app.state.session_factory() as session:
        assert session.get(EvaluationRun, run_id).status == "cancelled"
        assert (
            session.scalar(
                select(EvaluationResult).where(EvaluationResult.run_id == run_id)
            )
            is None
        )


def test_succeeded_run_events_emit_exact_completed_terminal_event(
    api_client, api_app, admin_headers
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    run_id = _create_run(api_app, dataset, status="succeeded")

    response = api_client.get(
        "/api/v1/evals/runs/events",
        params={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert _sse_events(response.text) == [
        (
            "completed",
            {"run_id": run_id, "status": "succeeded", "stage": "completed"},
        )
    ]


def test_failed_run_events_emit_exact_failed_terminal_event(
    api_client, api_app, admin_headers
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    run_id = _create_run(api_app, dataset, status="failed")

    response = api_client.get(
        "/api/v1/evals/runs/events",
        params={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert _sse_events(response.text) == [
        (
            "failed",
            {"run_id": run_id, "status": "failed", "stage": "failed"},
        )
    ]


def test_cancelled_run_events_never_map_to_failed(
    api_client, api_app, admin_headers
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    run_id = _create_run(api_app, dataset, status="running")

    cancelled = api_client.post(
        "/api/v1/evals/runs/cancel",
        json={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )
    response = api_client.get(
        "/api/v1/evals/runs/events",
        params={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )

    assert cancelled.status_code == 202
    assert cancelled.json()["data"]["status"] == "cancelled"
    assert _sse_events(response.text) == [
        (
            "cancelled",
            {"run_id": run_id, "status": "cancelled", "stage": "cancelled"},
        )
    ]


def test_cancel_running_run_is_idempotent(api_client, api_app, admin_headers):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    run_id = _create_run(api_app, dataset, status="running")

    first = api_client.post(
        "/api/v1/evals/runs/cancel",
        json={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )
    second = api_client.post(
        "/api/v1/evals/runs/cancel",
        json={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["data"] == {"id": run_id, "status": "cancelled"}


def test_running_run_streams_progress_until_success(
    api_client, api_app, admin_headers, monkeypatch
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    run_id = _create_run(api_app, dataset, status="running")
    transitions = []

    async def complete_after_first_poll():
        transitions.append("poll")
        with api_app.state.session_factory() as session:
            run = session.get(EvaluationRun, run_id)
            run.status = "succeeded"
            session.commit()

    monkeypatch.setattr(
        evaluations_module,
        "_wait_for_evaluation_poll",
        complete_after_first_poll,
    )
    response = api_client.get(
        "/api/v1/evals/runs/events",
        params={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert transitions == ["poll"]
    assert _sse_events(response.text) == [
        (
            "progress",
            {"run_id": run_id, "status": "running", "stage": "evaluating"},
        ),
        (
            "completed",
            {"run_id": run_id, "status": "succeeded", "stage": "completed"},
        ),
    ]


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_cancel_rejects_finished_run_without_changing_terminal_status(
    api_client, api_app, admin_headers, status
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    run_id = _create_run(api_app, dataset, status=status)

    response = api_client.post(
        "/api/v1/evals/runs/cancel",
        json={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"
    with api_app.state.session_factory() as session:
        assert session.get(EvaluationRun, run_id).status == status


def test_evaluation_events_allow_team_member_and_reject_outsider(
    api_client, api_app, admin_headers
):
    team, dataset = _create_dataset(api_client, api_app, admin_headers)
    run_id = _create_run(api_app, dataset, status="succeeded")
    member = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "eval-member@example.com",
        display_name="Evaluation Member",
    )
    member_headers = login_headers(
        api_client,
        email="eval-member@example.com",
        password="password-123",
    )
    other_team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Other Evaluation Team"},
        headers=admin_headers,
    ).json()["data"]
    outsider = create_user_as_admin(
        api_client,
        admin_headers,
        other_team["id"],
        "eval-outsider@example.com",
        display_name="Evaluation Outsider",
    )
    outsider_headers = login_headers(
        api_client,
        email="eval-outsider@example.com",
        password="password-123",
    )

    member_response = api_client.get(
        "/api/v1/evals/runs/events",
        params={"team_id": team["id"], "run_id": run_id},
        headers=member_headers,
    )
    outsider_response = api_client.get(
        "/api/v1/evals/runs/events",
        params={"team_id": team["id"], "run_id": run_id},
        headers=outsider_headers,
    )
    member_cancel = api_client.post(
        "/api/v1/evals/runs/cancel",
        json={"team_id": team["id"], "run_id": run_id},
        headers=member_headers,
    )

    assert member_response.status_code == 200
    assert outsider_response.status_code == 403
    assert outsider_response.json()["error"]["code"] == "PERMISSION_DENIED"
    assert member_cancel.status_code == 403
    assert member_cancel.json()["error"]["code"] == "PERMISSION_DENIED"
