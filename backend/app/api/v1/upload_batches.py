"""Upload batches use per-file idempotency and an explicit upload completion step."""
import json
from typing import List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.storage import normalize_file_name
from backend.app.api.v1.kb_access import knowledge_base_or_error
from backend.app.api.v1.teams import _editor_or_error
from backend.app.db.models import UploadBatch, UploadBatchFile, IngestionRun, User, utc_now
from backend.app.modules.audit.service import write_audit
from backend.app.modules.documents.batches import batch_files, batch_view

router = APIRouter(tags=["upload-batches"])
MAX_FILE_BYTES = 50 * 1024 * 1024


@router.get("/upload-batches")
def list_batches(team_id: str, kb_id: str, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    knowledge_base_or_error(session, team_id, kb_id, user.id)
    batches = session.scalars(select(UploadBatch).where(
        UploadBatch.team_id == team_id, UploadBatch.kb_id == kb_id, UploadBatch.created_by == user.id,
    ).order_by(UploadBatch.created_at.desc()).limit(100)).all()
    return envelope([batch_view(session, batch) for batch in batches], request.state.request_id)


class FileManifest(BaseModel):
    client_id: str = Field(min_length=1, max_length=64)
    file_name: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(ge=1, le=MAX_FILE_BYTES)


class BatchCreate(BaseModel):
    team_id: str
    kb_id: str
    client_id: str = Field(min_length=1, max_length=64)
    files: List[FileManifest] = Field(min_length=1, max_length=1000)
    product: str = Field(default="", max_length=120)
    version_values: List[str] = Field(default_factory=list, max_length=100)
    visibility: str = "team_shared"
    data_classification: str = "internal"


class BatchAction(BaseModel):
    team_id: str
    batch_id: str


def authorized_batch(session, team_id, batch_id, user, *, lock=False):
    query = select(UploadBatch).where(UploadBatch.id == batch_id, UploadBatch.team_id == team_id)
    batch = session.scalar(query.with_for_update() if lock else query)
    if batch is None:
        raise ApiError(404, "NOT_FOUND", "Upload batch was not found.")
    knowledge_base_or_error(session, team_id, batch.kb_id, user.id)
    # A batch can contain private files. Only its uploader can inspect or mutate it.
    if batch.created_by != user.id:
        raise ApiError(404, "NOT_FOUND", "Upload batch was not found.")
    return batch


@router.get("/upload-batches/limits")
def limits(request: Request, user: User = Depends(get_current_user)):
    settings = request.app.state.settings
    return envelope({"max_files": settings.upload_batch_max_files,
                     "max_total_bytes": settings.upload_batch_max_bytes,
                     "max_file_bytes": MAX_FILE_BYTES, "upload_concurrency": 3}, request.state.request_id)


@router.post("/upload-batches/create", status_code=201)
def create_batch(body: BatchCreate, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    from backend.app.api.v1.documents import _validate_document_metadata_fields
    _editor_or_error(session, body.team_id, user.id)
    knowledge_base_or_error(session, body.team_id, body.kb_id, user.id)
    _validate_document_metadata_fields(body.visibility, body.data_classification)
    settings = request.app.state.settings
    if len(body.files) > settings.upload_batch_max_files or sum(item.size_bytes for item in body.files) > settings.upload_batch_max_bytes:
        raise ApiError(413, "BATCH_LIMIT_EXCEEDED", "Upload batch exceeds the configured file count or size limit.")
    if len({item.client_id for item in body.files}) != len(body.files):
        raise ApiError(400, "INVALID_ARGUMENT", "File identifiers must be unique within a batch.")
    for item in body.files:
        try:
            item.file_name = normalize_file_name(item.file_name)
        except ValueError as error:
            raise ApiError(400, "INVALID_ARGUMENT", str(error)) from error
        if item.file_name.rsplit(".", 1)[-1].lower() not in {"md", "txt", "pdf", "docx"}:
            raise ApiError(400, "UNSUPPORTED_DOCUMENT_TYPE", "Supported files: Markdown, TXT, PDF and DOCX.")
    metadata = {key: getattr(body, key) for key in ("product", "version_values", "visibility", "data_classification")}
    existing = session.scalar(select(UploadBatch).where(UploadBatch.created_by == user.id, UploadBatch.client_id == body.client_id))

    def replay(batch):
        stored = [(item.client_id, item.file_name, item.size_bytes) for item in batch_files(session, batch.id)]
        supplied = [(item.client_id, item.file_name, item.size_bytes) for item in body.files]
        if batch.team_id != body.team_id or batch.kb_id != body.kb_id or sorted(stored) != sorted(supplied) or json.loads(batch.metadata_json) != metadata:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "This batch identifier was already used with different files or settings.")
        return envelope(batch_view(session, batch), request.state.request_id)

    if existing:
        return replay(existing)
    batch = UploadBatch(team_id=body.team_id, kb_id=body.kb_id, created_by=user.id,
                        client_id=body.client_id, metadata_json=json.dumps(metadata))
    try:
        session.add(batch)
        session.flush()
        session.add_all([UploadBatchFile(batch_id=batch.id, **item.model_dump()) for item in body.files])
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(UploadBatch).where(UploadBatch.created_by == user.id, UploadBatch.client_id == body.client_id))
        if existing is None:
            raise
        return replay(existing)
    return envelope(batch_view(session, batch), request.state.request_id)


@router.get("/upload-batches/detail")
def detail(team_id: str, batch_id: str, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return envelope(batch_view(session, authorized_batch(session, team_id, batch_id, user)), request.state.request_id)


def dispatch_batch(batch, session, settings):
    from backend.app.workers.dispatch import dispatch_upload_batch, TaskDispatchError
    try:
        dispatch_upload_batch(session, batch.id, settings)
    except TaskDispatchError as error:
        raise ApiError(503, "TASK_QUEUE_UNAVAILABLE", "Files are saved. Retry starting this batch when the queue is available.") from error


@router.post("/upload-batches/seal", status_code=202)
def seal(body: BatchAction, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _editor_or_error(session, body.team_id, user.id)
    batch = authorized_batch(session, body.team_id, body.batch_id, user, lock=True)
    batch.sealed_at = batch.sealed_at or utc_now()
    if batch.status == "uploading":
        batch.status = "queued"
    session.commit()
    dispatch_batch(batch, session, request.app.state.settings)
    session.refresh(batch)
    return envelope(batch_view(session, batch), request.state.request_id)


@router.post("/upload-batches/retry", status_code=202)
def retry(body: BatchAction, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _editor_or_error(session, body.team_id, user.id)
    batch = authorized_batch(session, body.team_id, body.batch_id, user, lock=True)
    for item in batch_files(session, batch.id):
        run = session.get(IngestionRun, item.run_id) if item.run_id else None
        if run and run.status == "failed":
            run.status, run.current_stage, run.error_code = "queued", "queued", None
            run.failure_details, run.stage_progress_pct = "{}", 0
            item.processing_retries = 0
    batch.sealed_at = batch.sealed_at or utc_now()
    batch.status = "queued"
    write_audit(session, team_id=body.team_id, actor_id=user.id, action="upload_batch.retry",
                resource_type="upload_batch", resource_id=batch.id, details={})
    session.commit()
    dispatch_batch(batch, session, request.app.state.settings)
    return envelope(batch_view(session, batch), request.state.request_id)
