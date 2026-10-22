"""Task dispatch helpers with an explicit inline mode for local tests."""

from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.workers.tasks import (
    ingest_document,
    ingest_document_record,
    ingest_upload_batch,
    reindex_generation,
    reindex_generation_record,
    run_evaluation,
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
    from sqlalchemy import select
    from backend.app.db.models import UploadBatchFile
    item = session.scalar(select(UploadBatchFile).where(UploadBatchFile.run_id == run_id)) if run_id else None
    if item:
        item.processing_retries = 0
        session.commit()
        return dispatch_upload_batch(session, item.batch_id, settings)
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


def dispatch_upload_batch(session, batch_id: str, settings: Settings) -> dict:
    if settings.task_execution_mode == "inline":
        from backend.app.modules.documents.batch_processing import process_upload_batch
        # Inline mode is only used by local tests. Bound work even on errors.
        for _ in range(settings.upload_batch_max_files * 4 + 1):
            result = process_upload_batch(session, batch_id, settings)
            if not result.get("deferred"):
                return result
        return result
    try:
        ingest_upload_batch.apply_async(args=[batch_id], retry=False)
    except Exception as error:
        raise TaskDispatchError("The upload batch queue is unavailable.") from error
    return {"batch_id": batch_id, "status": "queued"}


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
