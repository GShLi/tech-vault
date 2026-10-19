from sqlalchemy import select

from backend.app.api.v1 import evaluations as evaluations_module
from backend.app.core.config import Settings
from backend.app.db.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    Team,
    User,
)
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.main import create_app
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
