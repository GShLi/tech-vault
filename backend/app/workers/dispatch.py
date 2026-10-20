"""Task dispatch helpers with an explicit inline mode for local tests."""

from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.workers.tasks import (
    ingest_document,
    ingest_document_record,
    reindex_generation,
    reindex_generation_record,
    run_evaluation,
    sync_github_source_record,
    sync_github_source_task,
)


class TaskDispatchError(RuntimeError):
    """Raised when a background task cannot be submitted to the broker."""


def dispatch_document_ingestion(
    session,
    document_id: str,
    settings: Settings,
    *,
    run_id: str | None = None,
) -> dict:
    if settings.task_execution_mode == "inline":
        return ingest_document_record(
            session,
            document_id,
            settings,
            run_id=run_id,
        )
    try:
        ingest_document.apply_async(args=[document_id, run_id], retry=False)
    except Exception as error:  # noqa: BLE001
        raise TaskDispatchError("The ingestion task queue is unavailable.") from error
    return {"document_id": document_id, "status": "queued"}


def dispatch_source_sync(session, source_id: str, settings: Settings) -> dict:
    if settings.task_execution_mode == "inline":
        return sync_github_source_record(session, source_id, settings)
    try:
        sync_github_source_task.apply_async(args=[source_id], retry=False)
    except Exception as error:  # noqa: BLE001
        raise TaskDispatchError("The source synchronization queue is unavailable.") from error
    return {"source_id": source_id, "status": "queued"}


def dispatch_generation_reindex(
    session,
    generation_id: str,
    settings: Settings,
) -> dict:
    if settings.task_execution_mode == "inline":
        result = reindex_generation_record(session, generation_id, settings)
        return {
            "generation_id": generation_id,
            "status": result["status"],
            "execution_mode": "inline",
            "task_id": None,
            "passed": result.get("passed"),
            "checked_chunks": result.get("checked_chunks", 0),
            "errors": result.get("errors", []),
        }
    try:
        task = reindex_generation.apply_async(args=[generation_id], retry=False)
    except Exception as error:  # noqa: BLE001
        raise TaskDispatchError("The reindex task queue is unavailable.") from error
    return {
        "generation_id": generation_id,
        "status": "queued",
        "execution_mode": "celery",
        "task_id": getattr(task, "id", None),
        "passed": None,
        "checked_chunks": 0,
        "errors": [],
    }


def dispatch_evaluation_run(
    session,
    run_id: str,
    settings: Settings,
    judge_mode: str,
    baseline_metrics: dict,
) -> dict:
    if settings.task_execution_mode == "inline":
        from backend.app.api.v1.evaluations import execute_evaluation_run_record

        result = execute_evaluation_run_record(
            session,
            run_id,
            settings,
            judge_mode,
            baseline_metrics,
        )
        return {
            "run_id": run_id,
            "status": result["status"],
            "execution_mode": "inline",
            "task_id": None,
        }
    try:
        task = run_evaluation.apply_async(
            args=[run_id, judge_mode, baseline_metrics],
            retry=False,
        )
    except Exception as error:  # noqa: BLE001
        raise TaskDispatchError(
            "The evaluation task queue is unavailable."
        ) from error
    return {
        "run_id": run_id,
        "status": "queued",
        "execution_mode": "celery",
        "task_id": getattr(task, "id", None),
    }
