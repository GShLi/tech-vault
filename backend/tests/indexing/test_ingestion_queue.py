"""Lock contention must not consume the document processing retry budget."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from celery.exceptions import MaxRetriesExceededError, Retry

from backend.app.db.models import KnowledgeBase, ProcessingLease
from backend.app.rag.ingestion.leases import IngestionBusy
from backend.app.workers import tasks
from backend.tests.indexing.test_processor_documents import _ingestion_context


@pytest.fixture
def context(tmp_path, monkeypatch):
    session, document, run, settings, path = _ingestion_context(tmp_path, "queued.md")
    path.write_text("# Java\n\nJava records describe immutable data.", encoding="utf-8")
    engine = session.get_bind()
    monkeypatch.setattr(tasks.Settings, "from_env", lambda: settings)
    monkeypatch.setattr("backend.app.db.session.build_engine", lambda _url: engine)
    monkeypatch.setattr(engine, "dispose", Mock())
    yield session, document, run, settings
    session.close()


def hold_lease(session, document):
    team_id = session.get(KnowledgeBase, document.knowledge_base_id).team_id
    lease = ProcessingLease(
        team_id=team_id, owner="other-worker",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.add(lease)
    session.commit()
    return lease


def invoke(document_id, run_id, *, delivery_retries=0, processing_retries=0):
    # Exercise Celery's real retry signatures, without publishing to a broker.
    task = tasks.ingest_document
    task.push_request(
        id="test-delivery", called_directly=False, is_eager=True,
        retries=delivery_retries, args=[document_id, run_id], kwargs={},
    )
    try:
        return task.run(document_id, run_id, processing_retries=processing_retries)
    finally:
        task.pop_request()


def test_busy_waits_beyond_retry_limit_then_completes(context):
    session, document, run, _settings = context
    lease = hold_lease(session, document)
    for attempt in range(6):
        with pytest.raises(Retry) as retry:
            invoke(document.id, run.id, delivery_retries=attempt)
        signature = retry.value.sig
        assert signature.args == ()
        assert signature.kwargs == {
            "document_id": document.id, "run_id": run.id, "processing_retries": 0,
        }
        assert signature.options["retries"] == attempt + 1
        assert 15 <= retry.value.when <= 30
        session.refresh(run)
        session.refresh(document)
        assert (run.status, run.current_stage) == ("queued", "waiting_index")
        assert run.error_code is None
        assert document.doc_status == "building"
        assert session.get(ProcessingLease, lease.team_id).owner == "other-worker"

    session.delete(lease)
    session.commit()
    result = invoke(document.id, run.id, delivery_retries=6)
    assert result["status"] == "completed"
    assert result["chunks"] > 0
    session.refresh(document)
    assert document.doc_status == "active"


def test_waiting_run_can_be_cancelled(context):
    session, document, run, settings = context
    hold_lease(session, document)
    assert tasks.ingest_document_record(session, document.id, settings, run_id=run.id)["deferred"]
    run.status = run.current_stage = "cancelled"
    session.commit()
    result = invoke(document.id, run.id, delivery_retries=100)
    assert result["status"] == "cancelled"
    assert not result.get("deferred")


def test_duplicate_delivery_does_not_reset_running_task_or_active_document(context):
    session, document, run, settings = context
    run.status, run.current_stage, run.stage_progress_pct = "running", "embedding", 60
    document.doc_status = "active"
    session.commit()
    hold_lease(session, document)
    result = tasks.ingest_document_record(session, document.id, settings, run_id=run.id)
    assert result["deferred"]
    assert (run.status, run.current_stage, run.stage_progress_pct) == ("running", "embedding", 60)
    assert document.doc_status == "active"


@pytest.mark.parametrize("terminal", ["cancelled", "completed"])
def test_contention_does_not_overwrite_concurrent_terminal_state(context, monkeypatch, terminal):
    session, document, run, settings = context

    def busy_after_terminal(_document, current_run, current_session, _settings):
        current_run.status = current_run.current_stage = terminal
        current_session.commit()
        raise IngestionBusy()

    monkeypatch.setattr("backend.app.rag.ingestion.processor.process_markdown", busy_after_terminal)
    result = tasks.ingest_document_record(session, document.id, settings, run_id=run.id)
    assert result["status"] == terminal
    assert not result["deferred"]


@pytest.mark.parametrize("raises", [False, True])
def test_real_errors_have_separate_bounded_retry_budget(context, monkeypatch, raises):
    _session, document, run, _settings = context

    def fail(*_args, **_kwargs):
        if raises:
            raise ConnectionError("database unavailable")
        return {"status": "failed", "retryable": True}

    monkeypatch.setattr(tasks, "ingest_document_record", fail)
    for processing_retries in range(3):
        with pytest.raises(Retry) as retry:
            invoke(document.id, run.id, delivery_retries=100, processing_retries=processing_retries)
        assert retry.value.sig.kwargs["processing_retries"] == processing_retries + 1
    with pytest.raises(ConnectionError if raises else MaxRetriesExceededError):
        invoke(document.id, run.id, delivery_retries=100, processing_retries=3)


def test_permanent_error_is_not_retried(context, monkeypatch):
    _session, document, run, _settings = context
    monkeypatch.setattr(tasks, "ingest_document_record", lambda *_args, **_kwargs: {
        "status": "failed", "retryable": False, "error_code": "DOCUMENT_PARSE_FAILED",
    })
    assert invoke(document.id, run.id)["error_code"] == "DOCUMENT_PARSE_FAILED"


def test_expired_lease_is_reclaimed(context):
    session, document, run, _settings = context
    lease = hold_lease(session, document)
    lease.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.commit()
    assert invoke(document.id, run.id)["status"] == "completed"
