"""Celery application and async tasks.

Tasks run the document ingestion pipeline: parse, chunk, embed and index.
"""

from __future__ import annotations

import os

from celery import Celery

from backend.app.core.config import Settings

_settings = Settings.from_env()

celery_app = Celery(
    "techvault",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
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
)


@celery_app.task(name="techvault.ingest_document", bind=True, max_retries=3)
def ingest_document(self, document_id: str) -> dict:
    """Parse, chunk, embed and index a document version."""
    from backend.app.db.session import build_engine, build_session_factory
    from backend.app.db.models import Document, IngestionRun
    from backend.app.rag.ingestion.processor import process_markdown

    engine = build_engine(_settings.database_url)
    factory = build_session_factory(engine)

    with factory() as session:
        document = session.get(Document, document_id)
        if document is None:
            return {"document_id": document_id, "status": "not_found"}

        run = (
            session.query(IngestionRun)
            .filter(
                IngestionRun.document_version_id == document.current_version_id
            )
            .first()
        )
        if run is None:
            return {"document_id": document_id, "status": "no_run"}

        try:
            chunk_ids = process_markdown(document, run, session)
            return {
                "document_id": document_id,
                "status": run.status,
                "chunks": len(chunk_ids),
            }
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            run.error_code = "PROCESSING_ERROR"
            run.retryable = True
            session.commit()
            raise self.retry(exc=exc, countdown=30) from exc


@celery_app.task(name="techvault.reindex_generation")
def reindex_generation(generation_id: str) -> dict:
    """Placeholder for index generation rebuild."""
    return {"generation_id": generation_id, "status": "not_implemented"}
