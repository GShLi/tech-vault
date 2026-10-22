"""Persistent upload manifests and batch progress, independent of a browser tab."""
import json
from collections import Counter

from sqlalchemy import select

from backend.app.db.models import IngestionRun, UploadBatchFile


def batch_files(session, batch_id):
    return session.scalars(select(UploadBatchFile).where(
        UploadBatchFile.batch_id == batch_id,
    ).order_by(UploadBatchFile.id)).all()


def batch_view(session, batch):
    rows = session.execute(select(UploadBatchFile, IngestionRun).outerjoin(
        IngestionRun, UploadBatchFile.run_id == IngestionRun.id,
    ).where(UploadBatchFile.batch_id == batch.id).order_by(UploadBatchFile.id)).all()
    files = []
    for item, run in rows:
        status = run.status if run else ("upload_failed" if batch.sealed_at else "pending_upload")
        files.append({
            "id": item.id, "client_id": item.client_id, "file_name": item.file_name,
            "size_bytes": item.size_bytes, "document_id": item.document_id,
            "run_id": item.run_id, "status": status,
            "stage": run.current_stage if run else status,
            "progress": run.stage_progress_pct if run else 0,
            "error_code": run.error_code if run else None,
            "failure_details": json.loads(run.failure_details or "{}") if run else {},
        })
    return {
        "id": batch.id, "team_id": batch.team_id, "kb_id": batch.kb_id,
        "status": batch.status, "sealed": batch.sealed_at is not None,
        "metadata": json.loads(batch.metadata_json),
        "created_at": batch.created_at.isoformat(), "files": files,
        "counts": dict(Counter(item["status"] for item in files)),
        "total": len(files),
    }
