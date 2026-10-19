"""Celery application and async tasks.

Tasks run the document ingestion pipeline: parse, chunk, embed and index.
"""

from __future__ import annotations

import asyncio
import os

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
    worker_prefetch_multiplier=1,
    beat_schedule={
        "purge-expired-documents": {
            "task": "techvault.purge_expired_documents",
            "schedule": 3600.0,
        }
    },
)


@celery_app.task(name="techvault.ingest_document", bind=True, max_retries=3)
def ingest_document(self, document_id: str, run_id: str | None = None) -> dict:
    """Parse, chunk, embed and index a document version."""
    from backend.app.db.session import build_engine, build_session_factory

    settings = Settings.from_env()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)

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
                raise self.retry(exc=exc, countdown=30) from exc
            if result["status"] == "failed" and result.get("retryable"):
                raise self.retry(countdown=30)
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
    from backend.app.rag.ingestion.processor import process_markdown

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
    if run.status == "cancelled":
        return {
            "document_id": document_id,
            "run_id": run.id,
            "status": "cancelled",
            "chunks": 0,
        }

    try:
        chunk_ids = process_markdown(document, run, session, settings)
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


@celery_app.task(name="techvault.sync_github_source", bind=True, max_retries=3)
def sync_github_source_task(self, source_id: str) -> dict:
    """Synchronize a GitHub source in the background."""
    from backend.app.db.session import build_engine, build_session_factory

    settings = Settings.from_env()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            try:
                return sync_github_source_record(session, source_id, settings)
            except Exception as exc:  # noqa: BLE001
                raise self.retry(exc=exc, countdown=60) from exc
    finally:
        engine.dispose()


def sync_github_source_record(session, source_id: str, settings: Settings) -> dict:
    """Run one source synchronization against an existing database session."""
    from backend.app.db.models import SourceConnection
    from backend.app.modules.sources.github import sync_github_source
    from backend.app.modules.audit.service import write_audit

    source = session.get(SourceConnection, source_id)
    if source is None:
        return {"source_id": source_id, "status": "not_found"}
    if source.status == "paused":
        return {"source_id": source_id, "status": "paused"}
    result = sync_github_source(source, session, settings)
    payload = result.as_dict()
    write_audit(
        session,
        team_id=source.team_id,
        actor_id=source.created_by,
        action="source.sync.completed",
        resource_type="source_connection",
        resource_id=source.id,
        details=payload,
    )
    session.commit()
    return payload


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
