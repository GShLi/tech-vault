"""Celery application and async tasks.

Tasks run the document ingestion pipeline: parse, chunk, embed and index.
"""

from __future__ import annotations

import asyncio
import os
import random

from celery import Celery

from backend.app.core.config import Settings

_redis_url = os.getenv("TECHVAULT_REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "techvault",
    broker=_redis_url,
    backend=_redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    worker_max_tasks_per_child=50,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "recover-upload-batches": {
            "task": "techvault.recover_upload_batches",
            "schedule": 60.0,
        },
        "purge-expired-documents": {
            "task": "techvault.purge_expired_documents",
            "schedule": 3600.0,
        }
    },
)


MAX_PROCESSING_RETRIES = 3


@celery_app.task(name="techvault.ingest_upload_batch", bind=True, max_retries=None)
def ingest_upload_batch(self, batch_id: str, processing_retries: int = 0) -> dict:
    from backend.app.db.session import build_engine, build_session_factory
    from backend.app.modules.documents.batch_processing import process_upload_batch
    settings = Settings.from_env()
    engine = build_engine(settings.database_url)
    try:
        with build_session_factory(engine)() as session:
            try:
                result = process_upload_batch(session, batch_id, settings)
            except Exception as error:
                if processing_retries >= MAX_PROCESSING_RETRIES:
                    raise
                raise self.retry(exc=error, args=[batch_id, processing_retries + 1], countdown=30)
            if result.get("deferred"):
                raise self.retry(args=[batch_id, processing_retries], countdown=random.randint(15, 30))
            return result
    finally:
        engine.dispose()


@celery_app.task(name="techvault.recover_upload_batches")
def recover_upload_batches() -> dict:
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from backend.app.db.models import UploadBatch
    from backend.app.db.session import build_engine, build_session_factory
    settings = Settings.from_env()
    engine = build_engine(settings.database_url)
    count = 0
    try:
        with build_session_factory(engine)() as session:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
            rows = session.scalars(select(UploadBatch).where(
                UploadBatch.status.in_(("uploading", "queued", "processing")),
                UploadBatch.updated_at < cutoff,
            ).order_by(UploadBatch.updated_at).limit(100)).all()
            for batch in rows:
                # Closing the browser before sealing must not strand saved files.
                batch.sealed_at = batch.sealed_at or datetime.now(timezone.utc)
                batch.status = "queued"
                batch.updated_at = datetime.now(timezone.utc)
                session.commit()
                ingest_upload_batch.apply_async(args=[batch.id])
                count += 1
    finally:
        engine.dispose()
    return {"dispatched": count}


@celery_app.task(name="techvault.ingest_document", bind=True, max_retries=None)
def ingest_document(
    self, document_id: str, run_id: str | None = None, *, processing_retries: int = 0,
) -> dict:
    """Parse, chunk, embed and index a document version."""
    from backend.app.db.session import build_engine, build_session_factory

    settings = Settings.from_env()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    retry_kwargs = {
        "document_id": document_id,
        "run_id": run_id,
        "processing_retries": processing_retries,
    }

    try:
        with factory() as session:
            try:
                result = ingest_document_record(
                    session,
                    document_id,
                    settings,
                    run_id=run_id,
                )
            except Exception as exc:  # noqa: BLE001
                if processing_retries >= MAX_PROCESSING_RETRIES:
                    raise
                raise self.retry(
                    exc=exc, countdown=30, args=(),
                    kwargs={**retry_kwargs, "processing_retries": processing_retries + 1},
                ) from exc
            if result.get("deferred"):
                # Celery's delivery retry counter includes lock waits. Keep the
                # bounded processing error budget separate from that counter.
                raise self.retry(
                    countdown=random.randint(15, 30), args=(), kwargs=retry_kwargs,
                )
            if result["status"] == "failed" and result.get("retryable"):
                if processing_retries >= MAX_PROCESSING_RETRIES:
                    raise self.MaxRetriesExceededError("Document processing retry limit reached.")
                raise self.retry(
                    countdown=30, args=(),
                    kwargs={**retry_kwargs, "processing_retries": processing_retries + 1},
                )
            return result
    finally:
        engine.dispose()


def ingest_document_record(
    session,
    document_id: str,
    settings: Settings,
    *,
    run_id: str | None = None,
) -> dict:
    """Run one document ingestion against an existing database session."""
    from backend.app.db.models import Document, IngestionRun
    from backend.app.rag.ingestion.leases import IngestionBusy
    from backend.app.rag.ingestion.processor import process_markdown
    from sqlalchemy import update

    document = session.get(Document, document_id)
    if document is None:
        return {"document_id": document_id, "status": "not_found", "chunks": 0}

    if run_id:
        run = session.get(IngestionRun, run_id)
        if run is not None and run.document_version_id != document.current_version_id:
            run = None
    else:
        run = (
            session.query(IngestionRun)
            .filter(IngestionRun.document_version_id == document.current_version_id)
            .order_by(IngestionRun.created_at.desc())
            .first()
        )
    if run is None:
        return {"document_id": document_id, "status": "no_run", "chunks": 0}
    if run.status in {"cancelled", "completed"}:
        return {
            "document_id": document_id,
            "run_id": run.id,
            "status": run.status,
            "chunks": 0,
        }

    try:
        chunk_ids = process_markdown(document, run, session, settings)
    except IngestionBusy:
        session.rollback()
        # A duplicate delivery must not reset a run that is already processing.
        # The conditional update also preserves concurrent cancellation/completion.
        session.execute(
            update(IngestionRun)
            .where(IngestionRun.id == run.id, IngestionRun.status.in_(("queued", "failed")))
            .values(
                status="queued", current_stage="waiting_index", stage_progress_pct=0,
                error_code=None, failure_details="{}", retryable=False,
            )
        )
        session.commit()
        session.refresh(run)
        return {
            "document_id": document_id, "run_id": run.id, "status": run.status,
            "deferred": run.status not in {"cancelled", "completed"}, "chunks": 0,
        }
    except Exception:
        if run.status != "cancelled":
            run.status = "failed"
            run.current_stage = "failed"
            run.error_code = "PROCESSING_ERROR"
            run.retryable = True
            document.doc_status = "failed"
            session.commit()
        raise
    return {
        "document_id": document_id,
        "run_id": run.id,
        "status": run.status,
        "error_code": run.error_code,
        "retryable": run.retryable,
        "chunks": len(chunk_ids),
    }


@celery_app.task(name="techvault.reindex_generation")
def reindex_generation(generation_id: str) -> dict:
    """Rebuild a team's enabled chunks into a validated staging generation."""
    from backend.app.db.session import build_engine, build_session_factory

    settings = Settings.from_env()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            return reindex_generation_record(session, generation_id, settings)
    finally:
        engine.dispose()


def reindex_generation_record(session, generation_id: str, settings: Settings) -> dict:
    """Synchronous worker body kept separate for deterministic testing."""
    from backend.app.db.models import IndexGenerationRecord
    from backend.app.rag.indexing.generation import rebuild_generation

    generation = session.get(IndexGenerationRecord, generation_id)
    if generation is None:
        return {
            "generation_id": generation_id,
            "status": "not_found",
            "passed": False,
            "errors": ["index generation was not found"],
            "checked_chunks": 0,
        }
    return asyncio.run(rebuild_generation(session, generation, settings))


@celery_app.task(name="techvault.run_evaluation")
def run_evaluation(
    run_id: str,
    judge_mode: str,
    baseline_metrics: dict,
) -> dict:
    """Execute one queued evaluation run against an isolated worker session."""
    from backend.app.api.v1.evaluations import execute_evaluation_run_record
    from backend.app.db.session import build_engine, build_session_factory

    settings = Settings.from_env()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            return execute_evaluation_run_record(
                session,
                run_id,
                settings,
                judge_mode,
                baseline_metrics,
            )
    finally:
        engine.dispose()


@celery_app.task(name="techvault.purge_expired_documents")
def purge_expired_documents() -> dict:
    """Purge expired soft-deleted documents in bounded batches."""
    from backend.app.db.session import build_engine, build_session_factory
    from backend.app.modules.documents.lifecycle import (
        purge_expired_documents_record,
    )

    settings = Settings.from_env()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            return purge_expired_documents_record(session, settings)
    finally:
        engine.dispose()
