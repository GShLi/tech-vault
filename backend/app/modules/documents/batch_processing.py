"""Resume a bounded group of documents and publish them together."""
from datetime import datetime, timezone

from sqlalchemy import select, update

from backend.app.db.models import Document, IngestionRun, KnowledgeBase, UploadBatch
from backend.app.modules.documents.batches import batch_files
from backend.app.rag.ingestion.leases import IngestionBusy, team_lease
from backend.app.rag.ingestion.processor import process_document, publish_prepared, fail_ingestion


def _record_attempt(session, item, run):
    item.processing_retries += 1
    if run.retryable and item.processing_retries <= 3:
        run.status, run.current_stage = "queued", "retrying"
    session.commit()


def process_upload_batch(session, batch_id, settings):
    batch = session.get(UploadBatch, batch_id)
    if batch is None or batch.sealed_at is None:
        return {"status": "not_ready"}
    if batch.status == "completed":
        return {"status": "completed"}
    items = batch_files(session, batch.id)
    try:
        # Preparation is serial within a team to bound model load. Publication
        # is grouped; checkpoints survive redelivery and graceful worker restarts.
        with team_lease(session, batch.team_id):
            session.refresh(batch)
            batch.status = "processing"
            session.commit()
            pairs, attempted = [], []
            started = datetime.now(timezone.utc)
            for item in items:
                session.refresh(item)
                run = session.get(IngestionRun, item.run_id) if item.run_id else None
                if run is None or run.status in {"cancelled", "completed"}:
                    continue
                if run.status == "failed" and (not run.retryable or item.processing_retries > 3):
                    continue
                document = session.get(Document, item.document_id)
                kb = session.get(KnowledgeBase, batch.kb_id)
                if document is None or document.doc_status in {"deleted", "deleting"} or kb.status != "active":
                    run.status, run.current_stage, run.retryable = "cancelled", "cancelled", False
                    session.commit()
                    continue
                process_document(document, run, session, settings, prepare_only=True)
                attempted.append(item)
                if run.status == "prepared":
                    pairs.append((document, run))
                elif run.status == "failed":
                    _record_attempt(session, item, run)
                if len(attempted) >= settings.ingestion_publish_group_size or (datetime.now(timezone.utc) - started).total_seconds() > 1200:
                    break
            try:
                publish_prepared(session, pairs, settings)
            except Exception as error:
                for document, run in pairs:
                    fail_ingestion(document, run, session, error)
                    item = next(item for item in attempted if item.run_id == run.id)
                    _record_attempt(session, item, run)
            # Requery: additional failed uploads may have been submitted meanwhile.
            session.expire_all()
            states, pending = [], False
            for item in batch_files(session, batch.id):
                run = session.get(IngestionRun, item.run_id) if item.run_id else None
                states.append(run.status if run else "upload_failed")
                if run and (run.status in {"queued", "running", "prepared"} or (
                    run.status == "failed" and run.retryable and item.processing_retries <= 3
                )):
                    pending = True
            batch.status = "queued" if pending else ("completed" if states and all(s == "completed" for s in states) else "partial_failed")
            batch.updated_at = datetime.now(timezone.utc)
            session.commit()
            return {"batch_id": batch.id, "status": batch.status, "deferred": pending}
    except IngestionBusy:
        session.rollback()
        session.execute(update(IngestionRun).where(
            IngestionRun.id.in_([item.run_id for item in items if item.run_id]),
            IngestionRun.status == "queued",
        ).values(current_stage="waiting_index", error_code=None, retryable=False))
        session.commit()
        return {"batch_id": batch.id, "status": "queued", "deferred": True}
