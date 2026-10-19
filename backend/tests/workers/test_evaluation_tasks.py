import json

from sqlalchemy import select

from backend.app.api.v1 import evaluations as evaluations_module
from backend.app.core.config import Settings
from backend.app.core.secrets import encrypt_secret
from backend.app.db.models import (
    DeploymentModelPolicyRecord,
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    IndexGenerationRecord,
    ModelCall,
    ModelPolicyRecord,
    ModelProvider,
    Team,
    User,
)
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.main import create_app
from backend.app.rag.answer.service import AnswerResult
from backend.app.rag.domain.models import RetrievedChunk, SearchResult
from backend.app.workers import tasks as tasks_module


def test_celery_evaluation_task_executes_persisted_run(monkeypatch, tmp_path):
    settings = Settings(
        environment="development",
        jwt_secret="test-secret-at-least-32-bytes-long",
        task_execution_mode="celery",
    )
    engine = build_engine(
        "sqlite+pysqlite:///{0}".format(tmp_path / "evaluation-worker.db")
    )
    create_schema(engine)
    factory = build_session_factory(engine)
    create_app(settings=settings, session_factory=factory)

    with factory() as session:
        admin = session.scalar(select(User).where(User.is_super_admin.is_(True)))
        team = Team(name="Worker Evaluation Team", created_by=admin.id)
        session.add(team)
        session.flush()
        dataset = EvaluationDataset(
            team_id=team.id,
            name="Worker Golden Set",
            created_by=admin.id,
        )
        session.add(dataset)
        session.flush()
        session.add(
            EvaluationCase(
                dataset_id=dataset.id,
                query_id="q1",
                query_type="concept",
                query="What is RAG?",
                relevant_chunk_ids='["chunk-1"]',
                relevance='{"chunk-1":1}',
            )
        )
        run = EvaluationRun(
            dataset_id=dataset.id,
            engine_mode="dual_engine",
            status="queued",
            created_by=admin.id,
        )
        session.add(run)
        session.commit()
        run_id = run.id

    monkeypatch.setattr(
        tasks_module.Settings,
        "from_env",
        classmethod(lambda _cls: settings),
    )
    monkeypatch.setattr(
        "backend.app.db.session.build_engine",
        lambda _database_url: engine,
    )
    monkeypatch.setattr(
        "backend.app.db.session.build_session_factory",
        lambda _engine: factory,
    )
    monkeypatch.setattr(
        evaluations_module,
        "_collect_evaluation_result",
        lambda *_args, **_kwargs: {
            "metrics": {"case_count": 1, "recall_at_10": 1.0},
            "report": {"cases": [{"query_id": "q1"}]},
        },
    )

    result = tasks_module.run_evaluation.run(run_id, "rules", {})

    assert result == {"id": run_id, "status": "succeeded"}
    with factory() as session:
        assert session.get(EvaluationRun, run_id).status == "succeeded"
        persisted = session.scalar(
            select(EvaluationResult).where(EvaluationResult.run_id == run_id)
        )
        assert persisted is not None
        assert '"recall_at_10":1.0' in persisted.metrics
    engine.dispose()


def test_celery_evaluation_task_injects_persisted_provider_adapter(
    monkeypatch, tmp_path
):
    settings = Settings(
        environment="development",
        jwt_secret="test-secret-at-least-32-bytes-long",
        task_execution_mode="celery",
    )
    engine = build_engine(
        "sqlite+pysqlite:///{0}".format(tmp_path / "evaluation-provider-worker.db")
    )
    create_schema(engine)
    factory = build_session_factory(engine)
    create_app(settings=settings, session_factory=factory)

    with factory() as session:
        admin = session.scalar(select(User).where(User.is_super_admin.is_(True)))
        team = Team(name="Provider Evaluation Team", created_by=admin.id)
        session.add(team)
        session.flush()
        provider = ModelProvider(
            team_id=team.id,
            name="Worker Provider",
            provider_type="openai_chat_completions",
            base_url="http://worker-provider.test/v1",
            api_key_masked="****cret",
            api_key_encrypted=encrypt_secret("sk-worker-secret", settings),
            model_ids=json.dumps(["model-a"]),
            status="active",
            created_by=admin.id,
        )
        session.add(provider)
        session.flush()
        deployment_policy = session.scalar(
            select(DeploymentModelPolicyRecord)
        )
        if deployment_policy is None:
            deployment_policy = DeploymentModelPolicyRecord()
            session.add(deployment_policy)
        deployment_policy.mode = "external_allowed"
        deployment_policy.allowed_provider_ids = json.dumps([provider.id])
        deployment_policy.max_data_classification = "internal"
        session.add(
            ModelPolicyRecord(
                team_id=team.id,
                mode="external_allowed",
                allowed_provider_ids=json.dumps([provider.id]),
                max_data_classification="internal",
            )
        )
        dataset = EvaluationDataset(
            team_id=team.id,
            name="Provider Golden Set",
            created_by=admin.id,
        )
        session.add(dataset)
        session.flush()
        session.add(
            EvaluationCase(
                dataset_id=dataset.id,
                query_id="q1",
                query_type="concept",
                query="What is RAG?",
                relevant_chunk_ids='["chunk-1"]',
                relevance='{"chunk-1":1}',
            )
        )
        session.add(IndexGenerationRecord(team_id=team.id, status="active"))
        run = EvaluationRun(
            dataset_id=dataset.id,
            engine_mode="dual_engine",
            status="queued",
            provider_id=provider.id,
            model_id="model-a",
            created_by=admin.id,
        )
        session.add(run)
        session.commit()
        run_id = run.id
        provider_id = provider.id
        encrypted_api_key = provider.api_key_encrypted

    monkeypatch.setattr(
        tasks_module.Settings,
        "from_env",
        classmethod(lambda _cls: settings),
    )
    monkeypatch.setattr(
        "backend.app.db.session.build_engine",
        lambda _database_url: engine,
    )
    monkeypatch.setattr(
        "backend.app.db.session.build_session_factory",
        lambda _engine: factory,
    )

    generated = []

    class Adapter:
        def __init__(self):
            self.provider_id = provider_id
            self.model_id = "model-a"
            self.route = "openai_chat_completions"

        def generate(self, *, question, chunks, max_chunks):
            generated.append(
                {
                    "question": question,
                    "chunk_ids": [chunk.chunk_id for chunk in chunks],
                }
            )
            return AnswerResult(
                text="Provider answer [c1].",
                status="completed",
                citation_chunk_ids=("chunk-1",),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
            )

    adapter_calls = []

    def build_adapter(**kwargs):
        adapter_calls.append(kwargs)
        return Adapter()

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

    decrypt_calls = []
    original_decrypt = evaluations_module.decrypt_secret

    def decrypt_once(value, decrypt_settings):
        decrypt_calls.append(value)
        return original_decrypt(value, decrypt_settings)

    monkeypatch.setattr(evaluations_module, "decrypt_secret", decrypt_once)
    monkeypatch.setattr(evaluations_module, "build_provider_adapter", build_adapter)
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

    result = tasks_module.run_evaluation.run(run_id, "rules", {})

    assert result == {"id": run_id, "status": "succeeded"}
    assert adapter_calls[0]["provider_id"] == provider_id
    assert adapter_calls[0]["api_key"] == "sk-worker-secret"
    assert adapter_calls[0]["model_id"] == "model-a"
    assert generated == [
        {
            "question": "What is RAG?",
            "chunk_ids": ["chunk-1"],
        }
    ]
    assert decrypt_calls == [encrypted_api_key]
    with factory() as session:
        model_call = session.scalar(
            select(ModelCall).where(ModelCall.purpose == "answer")
        )
        assert model_call is not None
        assert model_call.provider_id == provider_id
        assert model_call.model_id == "model-a"
        persisted = session.scalar(
            select(EvaluationResult).where(EvaluationResult.run_id == run_id)
        )
        assert persisted is not None
        report = json.loads(persisted.report)
        assert report["provider_id"] == provider_id
        assert report["model_id"] == "model-a"
    engine.dispose()
