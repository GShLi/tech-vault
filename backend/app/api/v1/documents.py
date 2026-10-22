import asyncio
import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import and_, false, func, or_, select, update
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor, paginate_scalars
from backend.app.api.storage import (
    FileSizeLimitExceeded,
    ObjectStorageUnavailable,
    StoragePresignUnavailable,
    download_s3_object,
    normalize_file_name,
    presign_s3_download_url,
    store_file,
)
from backend.app.api.v1.schemas import DocumentDetailView, DocumentView, IngestionRunView
from backend.app.api.v1.kb_access import (
    knowledge_base_member_ids,
    knowledge_base_or_error,
)
from backend.app.api.v1.teams import (
    _editor_or_error,
    _if_match_version,
    _membership_or_error,
)
from backend.app.core.ids import new_ulid
from backend.app.rag.domain.models import DataClassification, Visibility
from backend.app.rag.indexing.maintenance import (
    delete_document_from_indexes,
    set_chunk_status_in_indexes,
)
from backend.app.modules.audit.service import write_audit
from backend.app.modules.documents.lifecycle import (
    DocumentPurgeError,
    purge_document_record,
    retention_expired,
)
from backend.app.db.models import (
    Document,
    ChunkRecord,
    DocumentGrant,
    DocumentVersion,
    IngestionRun,
    IndexGenerationRecord,
    KnowledgeBase,
    TeamMember,
    User,
    utc_now,
)
from backend.app.workers.dispatch import (
    TaskDispatchError,
    dispatch_document_ingestion,
)


router = APIRouter(tags=["docs"])

_MAX_FILE_BYTES = 50 * 1024 * 1024
_ALLOWED_EXTENSIONS = frozenset({".md", ".txt", ".pdf", ".docx"})


def _validate_document_metadata_fields(
    visibility: object, classification: object
) -> None:
    if not isinstance(visibility, str) or visibility not in {
        item.value for item in Visibility
    }:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid document visibility.")
    if not isinstance(classification, str) or classification not in {
        item.value for item in DataClassification
    }:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid data classification.")


def _upload_metadata(
    *,
    product: Optional[str],
    version_values: Optional[List[str]],
    metadata: Optional[str],
) -> tuple[Optional[str], List[str]]:
    legacy: dict = {}
    if metadata:
        try:
            parsed = json.loads(metadata)
        except json.JSONDecodeError as error:
            raise ApiError(
                400, "INVALID_ARGUMENT", "metadata must be valid JSON"
            ) from error
        if not isinstance(parsed, dict):
            raise ApiError(
                400, "INVALID_ARGUMENT", "metadata must be a JSON object"
            )
        legacy = parsed

    effective_product = product if product is not None else legacy.get("product")
    if effective_product is not None:
        if not isinstance(effective_product, str):
            raise ApiError(400, "INVALID_ARGUMENT", "product must be a string.")
        effective_product = effective_product.strip() or None
        if effective_product is not None and len(effective_product) > 120:
            raise ApiError(
                400, "INVALID_ARGUMENT", "product must not exceed 120 characters."
            )

    effective_versions = (
        version_values if version_values is not None else legacy.get("version_values", [])
    )
    if not isinstance(effective_versions, list) or any(
        not isinstance(item, str) or not item.strip() for item in effective_versions
    ):
        raise ApiError(
            400,
            "INVALID_ARGUMENT",
            "version_values must be an array of non-empty strings.",
        )
    normalized_versions = list(dict.fromkeys(item.strip() for item in effective_versions))
    return effective_product, normalized_versions


def _active_generation_id(session: Session, team_id: str) -> str:
    generation = session.scalar(
        select(IndexGenerationRecord)
        .where(
            IndexGenerationRecord.team_id == team_id,
            IndexGenerationRecord.status == "active",
        )
        .order_by(IndexGenerationRecord.activated_at.desc())
    )
    return generation.id if generation is not None else ""


def _granted_document_ids(
    session: Session, team_id: str, user_id: str
) -> tuple:
    rows = session.scalars(
        select(DocumentGrant.document_id)
        .join(Document, DocumentGrant.document_id == Document.id)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(
            DocumentGrant.user_id == user_id,
            KnowledgeBase.team_id == team_id,
            Document.doc_status != "deleted",
        )
        .order_by(DocumentGrant.created_at.asc())
    ).all()
    return tuple(rows)


def _readable_documents_filter(session: Session, team_id: str, user: User):
    grants = _granted_document_ids(session, team_id, user.id)
    return or_(
        Document.visibility == "team_shared",
        Document.owner_user_id == user.id,
        Document.id.in_(grants) if grants else false(),
    )


def _set_document_chunk_state(
    session: Session,
    document_id: str,
    *,
    document_status: str,
    chunk_status: str,
) -> None:
    session.execute(
        update(ChunkRecord)
        .where(ChunkRecord.document_id == document_id)
        .values(
            doc_status=document_status,
            chunk_status=chunk_status,
            status=chunk_status,
            version=ChunkRecord.version + 1,
        )
    )


def _refresh_generation_count(session: Session, generation_id: str) -> None:
    if not generation_id:
        return
    generation = session.get(IndexGenerationRecord, generation_id)
    if generation is None:
        return
    generation.chunk_count = int(
        session.scalar(
            select(func.count())
            .select_from(ChunkRecord)
            .where(
                ChunkRecord.index_generation == generation_id,
                ChunkRecord.status == "enabled",
            )
        )
        or 0
    )


def _new_ingestion_run(session: Session, document: Document) -> IngestionRun:
    run = IngestionRun(
        id=new_ulid(),
        document_version_id=document.current_version_id or "",
        status="queued",
        current_stage="queued",
        stage_progress_pct=0,
    )
    if document.doc_status != "active":
        document.doc_status = "building"
    session.add(run)
    session.commit()
    return run


def _prepare_rebuild_document(
    document: Document,
    session: Session,
    settings,
) -> tuple[IngestionRun, str]:
    generation_id = _active_generation_id(
        session,
        session.get(KnowledgeBase, document.knowledge_base_id).team_id,
    )
    run = _new_ingestion_run(session, document)
    return run, generation_id


def _dispatch_ingestion(
    document: Document,
    run: IngestionRun,
    session: Session,
    settings,
    *,
    generation_id: str = "",
) -> dict:
    try:
        result = dispatch_document_ingestion(
            session,
            document.id,
            settings,
            run_id=run.id,
        )
    except TaskDispatchError as error:
        run.status = "failed"
        run.current_stage = "failed"
        run.error_code = "TASK_QUEUE_UNAVAILABLE"
        run.retryable = True
        document.doc_status = "failed"
        session.commit()
        raise ApiError(
            503,
            "TASK_QUEUE_UNAVAILABLE",
            "The ingestion task queue is unavailable.",
        ) from error
    if settings.task_execution_mode == "inline" and generation_id:
        _refresh_generation_count(session, generation_id)
        session.commit()
    return result


def _document_view(document: Document) -> dict:
    return DocumentView(
        id=document.id,
        knowledge_base_id=document.knowledge_base_id,
        file_name=document.file_name,
        source_type=document.source_type,
        product=document.product,
        version_values=json.loads(document.version_values)
        if document.version_values else [],
        visibility=document.visibility,
        data_classification=document.data_classification,
        doc_status=document.doc_status,
        deleted_at=document.deleted_at,
        purged_at=document.purged_at,
        version=document.version,
        created_at=document.created_at,
        updated_at=document.updated_at,
    ).model_dump()


def _kb_or_error(
    session: Session,
    team_id: str,
    kb_id: str,
    user_id: str,
) -> KnowledgeBase:
    return knowledge_base_or_error(session, team_id, kb_id, user_id)


def _document_or_error(
    session: Session,
    team_id: str,
    document_id: str,
    user: User,
    *,
    manage: bool = False,
) -> Document:
    membership = _membership_or_error(session, team_id, user.id)
    document = session.get(Document, document_id)
    if document is None:
        raise ApiError(404, "NOT_FOUND", "Document was not found.")
    knowledge_base = session.get(KnowledgeBase, document.knowledge_base_id)
    if knowledge_base is None or knowledge_base.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Document was not found.")
    knowledge_base_or_error(
        session,
        team_id,
        document.knowledge_base_id,
        user.id,
    )

    if (
        document.visibility == "private"
        and document.owner_user_id != user.id
        and document.id not in _granted_document_ids(session, team_id, user.id)
    ):
        raise ApiError(404, "NOT_FOUND", "Document was not found.")

    if manage:
        if membership.role == "viewer":
            raise ApiError(
                403, "PERMISSION_DENIED", "Document edit permission is required."
            )
        if document.owner_user_id == user.id:
            return document
        if membership.role == "leader" and document.visibility == "team_shared":
            return document
        raise ApiError(
            403, "PERMISSION_DENIED", "Document edit permission is required."
        )

    return document


def _manage_document_or_error(
    session: Session,
    team_id: str,
    document_id: str,
    user: User,
) -> Document:
    return _document_or_error(
        session, team_id, document_id, user, manage=True
    )


@router.post("/docs/upload", status_code=202)
def upload_document(
    request: Request,
    team_id: str = Form(...),
    kb_id: str = Form(...),
    file: UploadFile = Form(...),
    metadata: Optional[str] = Form(None),
    product: Optional[str] = Form(None),
    version_values: Optional[List[str]] = Form(None),
    visibility: str = Form("team_shared"),
    data_classification: str = Form("internal"),
    batch_id: Optional[str] = Form(None),
    batch_file_id: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _editor_or_error(session, team_id, user.id)
    _kb_or_error(session, team_id, kb_id, user.id)
    _validate_document_metadata_fields(visibility, data_classification)

    try:
        safe_file_name = normalize_file_name(file.filename or "")
    except ValueError as error:
        raise ApiError(400, "INVALID_ARGUMENT", str(error)) from error
    from backend.app.rag.parsing.router import validate_document_type
    from backend.app.rag.parsing.contracts import ParseError
    try:
        mime_type = validate_document_type(safe_file_name, file.content_type or "")
    except ParseError as error:
        raise ApiError(400, error.code, str(error)) from error
    ext = "." + safe_file_name.rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise ApiError(
            400, "INVALID_ARGUMENT",
            "Supported file types are: " + ", ".join(sorted(_ALLOWED_EXTENSIONS))
        )

    effective_product, effective_versions = _upload_metadata(
        product=product,
        version_values=version_values,
        metadata=metadata,
    )

    batch = batch_item = None
    if bool(batch_id) != bool(batch_file_id):
        raise ApiError(400, "INVALID_ARGUMENT", "Both batch_id and batch_file_id are required.")
    if batch_id:
        from backend.app.api.v1.upload_batches import authorized_batch
        from backend.app.db.models import UploadBatchFile
        batch = authorized_batch(session, team_id, batch_id, user, lock=True)
        batch_item = session.scalar(select(UploadBatchFile).where(
            UploadBatchFile.batch_id == batch.id, UploadBatchFile.client_id == batch_file_id,
        ).with_for_update())
        if batch.kb_id != kb_id or batch_item is None or batch_item.file_name != safe_file_name:
            raise ApiError(409, "BATCH_FILE_MISMATCH", "File does not match the upload manifest.")
        if file.size is not None and file.size != batch_item.size_bytes:
            raise ApiError(409, "BATCH_FILE_MISMATCH", "File size does not match the upload manifest.")
        if batch_item.document_id:
            existing = _document_or_error(session, team_id, batch_item.document_id, user)
            return envelope({"document": _document_view(existing),
                             "document_version_id": existing.current_version_id,
                             "ingestion_run_id": batch_item.run_id}, request.state.request_id)
        shared = json.loads(batch.metadata_json)
        effective_product, effective_versions = shared["product"] or None, shared["version_values"]
        visibility, data_classification = shared["visibility"], shared["data_classification"]

    document_id = new_ulid()
    version_id = new_ulid()
    run_id = new_ulid()
    document_version_id = str(version_id)
    try:
        stored_file = store_file(
            file.file,
            safe_file_name,
            document_id,
            request.app.state.settings,
            max_bytes=_MAX_FILE_BYTES,
        )
    except FileSizeLimitExceeded as error:
        raise ApiError(
            413,
            "PAYLOAD_TOO_LARGE",
            "File exceeds the 50 MB limit.",
        ) from error
    except ValueError as error:
        raise ApiError(400, "INVALID_ARGUMENT", str(error)) from error
    except ObjectStorageUnavailable as error:
        raise ApiError(
            503,
            "OBJECT_STORAGE_UNAVAILABLE",
            "The document could not be stored.",
        ) from error

    document = Document(
        id=document_id,
        knowledge_base_id=kb_id,
        owner_user_id=user.id,
        file_name=safe_file_name,
        mime_type=mime_type,
        source_uri=str(stored_file.path),
        object_uri=stored_file.object_uri,
        product=effective_product,
        version_values=json.dumps(effective_versions),
        visibility=visibility,
        data_classification=data_classification,
        doc_status="building",
        current_version_id=version_id,
    )
    session.add(document)

    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        content_fingerprint=stored_file.content_sha256,
        file_size_bytes=stored_file.size_bytes,
        status="building",
    )
    session.add(version)

    ingestion_run = IngestionRun(
        id=run_id,
        document_version_id=version_id,
        status="queued",
        current_stage="queued",
        stage_progress_pct=0,
    )
    session.add(ingestion_run)
    if batch_item:
        if stored_file.size_bytes != batch_item.size_bytes:
            raise ApiError(409, "BATCH_FILE_MISMATCH", "File size does not match the upload manifest.")
        session.flush()
        batch_item.document_id, batch_item.run_id = document.id, ingestion_run.id
        batch.updated_at = utc_now()
        if batch.sealed_at:
            batch.status = "queued"
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="document.upload",
        resource_type="document",
        resource_id=document.id,
        details={
            "kb_id": kb_id,
            "file_name": safe_file_name,
            "visibility": visibility,
            "data_classification": data_classification,
            "run_id": run_id,
        },
    )
    session.commit()

    if batch is None:
        _dispatch_ingestion(document, ingestion_run, session, request.app.state.settings)

    return envelope(
        {
            "document": _document_view(document),
            "document_version_id": version_id,
            "ingestion_run_id": run_id,
        },
        request.state.request_id,
    )


@router.get("/docs")
def list_documents(
    request: Request,
    team_id: str,
    kb_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    q: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _kb_or_error(session, team_id, kb_id, user.id)
    page_limit = max(1, min(limit, 100))

    query = select(Document).where(
        Document.knowledge_base_id == kb_id,
        Document.doc_status != "deleted",
    )
    query = query.where(_readable_documents_filter(session, team_id, user))
    if q and q.strip():
        query = query.where(Document.file_name.icontains(q.strip(), autoescape=True))
    if cursor is not None:
        after_created, after_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Document.created_at < after_created,
                and_(Document.created_at == after_created, Document.id < after_id),
            )
        )
    rows = session.scalars(
        query.order_by(Document.created_at.desc(), Document.id.desc()).limit(page_limit + 1)
    ).all()
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    next_cursor = (
        encode_cursor(page_rows[-1].created_at, page_rows[-1].id)
        if has_more and page_rows else None
    )
    return page_envelope(
        [_document_view(doc) for doc in page_rows],
        request.state.request_id,
        next_cursor,
    )


@router.get("/docs/detail")
def get_document(
    request: Request,
    team_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    document = _document_or_error(session, team_id, document_id, user)
    version = session.get(DocumentVersion, document.current_version_id) if document.current_version_id else None
    run = session.scalar(select(IngestionRun).where(IngestionRun.document_version_id == document.current_version_id)
                         .order_by(IngestionRun.created_at.desc(), IngestionRun.id.desc()))
    return envelope(
        DocumentDetailView(
            parse_metadata=json.loads(version.parse_metadata or "{}") if version else {},
            chunking_metadata=json.loads(version.chunking_metadata or "{}") if version else {},
            quality_metrics=json.loads(run.quality_metrics or "{}") if run else {},
            failure_details=json.loads(run.failure_details or "{}") if run else {},
            id=document.id,
            knowledge_base_id=document.knowledge_base_id,
            owner_user_id=document.owner_user_id,
            file_name=document.file_name,
            source_type=document.source_type,
            source_uri=document.file_name,
            product=document.product,
            version_family=document.version_family,
            version_values=json.loads(document.version_values) if document.version_values else [],
            visibility=document.visibility,
            data_classification=document.data_classification,
            doc_status=document.doc_status,
            deleted_at=document.deleted_at,
            purged_at=document.purged_at,
            current_version_id=document.current_version_id,
            version=document.version,
            created_at=document.created_at,
            updated_at=document.updated_at,
        ).model_dump(),
        request.state.request_id,
    )


@router.get("/ingestions")
def list_ingestion_runs(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    kb_id: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    page_limit = max(1, min(limit, 100))

    query = select(IngestionRun).join(
        DocumentVersion, IngestionRun.document_version_id == DocumentVersion.id,
    ).join(
        Document, DocumentVersion.document_id == Document.id,
    ).join(
        KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id,
    ).where(
        KnowledgeBase.team_id == team_id,
        Document.doc_status != "deleted",
        KnowledgeBase.id.in_(
            knowledge_base_member_ids(session, team_id, user.id)
        ),
        _readable_documents_filter(session, team_id, user),
    )
    if kb_id:
        _kb_or_error(session, team_id, kb_id, user.id)
        query = query.where(Document.knowledge_base_id == kb_id)
    if cursor is not None:
        after_created, after_id = decode_cursor(cursor)
        query = query.where(
            or_(
                IngestionRun.created_at < after_created,
                and_(IngestionRun.created_at == after_created, IngestionRun.id < after_id),
            )
        )
    rows = session.scalars(
        query.order_by(IngestionRun.created_at.desc(), IngestionRun.id.desc()).limit(page_limit + 1)
    ).all()
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    next_cursor = (
        encode_cursor(page_rows[-1].created_at, page_rows[-1].id)
        if has_more and page_rows else None
    )
    names = dict(session.execute(select(DocumentVersion.id, Document.file_name).join(
        Document, DocumentVersion.document_id == Document.id,
    ).where(DocumentVersion.id.in_([run.document_version_id for run in page_rows]))).all())
    return page_envelope(
        [
            IngestionRunView(
                quality_metrics=json.loads(run.quality_metrics or "{}"),
                failure_details=json.loads(run.failure_details or "{}"),
                id=run.id,
                file_name=names.get(run.document_version_id),
                document_version_id=run.document_version_id,
                status=run.status,
                current_stage=run.current_stage,
                stage_progress_pct=run.stage_progress_pct,
                error_code=run.error_code,
                retryable=run.retryable,
                created_at=run.created_at,
                updated_at=run.updated_at,
            ).model_dump()
            for run in page_rows
        ],
        request.state.request_id,
        next_cursor,
    )


@router.get("/ingestions/detail")
def get_ingestion_run(
    request: Request,
    team_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    run = _run_or_error(session, team_id, run_id, user)
    return envelope(
        IngestionRunView(
                quality_metrics=json.loads(run.quality_metrics or "{}"),
                failure_details=json.loads(run.failure_details or "{}"),
            id=run.id,
            document_version_id=run.document_version_id,
            status=run.status,
            current_stage=run.current_stage,
            stage_progress_pct=run.stage_progress_pct,
            error_code=run.error_code,
            retryable=run.retryable,
            created_at=run.created_at,
            updated_at=run.updated_at,
        ).model_dump(),
        request.state.request_id,
    )


@router.post("/docs/update")
def update_document(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    document_id = body.get("document_id", "")
    doc = _manage_document_or_error(session, team_id, document_id, user)
    expected_version = _if_match_version(request)
    if doc.version != expected_version:
        raise ApiError(409, "VERSION_CONFLICT", "Resource version has changed.")

    updates = {}
    if body.get("file_name") is not None:
        try:
            updates["file_name"] = normalize_file_name(body["file_name"])
        except ValueError as error:
            raise ApiError(400, "INVALID_ARGUMENT", str(error)) from error

    for field in ("owner_user_id", "visibility", "data_classification"):
        value = body.get(field)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise ApiError(
                    400,
                    "INVALID_ARGUMENT",
                    "{0} must be a non-empty string.".format(field),
                )
            updates[field] = value

    if body.get("product") is not None:
        product = body["product"]
        if not isinstance(product, str):
            raise ApiError(400, "INVALID_ARGUMENT", "product must be a string.")
        product = product.strip() or None
        if product is not None and len(product) > 120:
            raise ApiError(
                400,
                "INVALID_ARGUMENT",
                "product must not exceed 120 characters.",
            )
        updates["product"] = product

    next_visibility = updates.get("visibility", doc.visibility)
    next_classification = updates.get("data_classification", doc.data_classification)
    next_owner_id = updates.get("owner_user_id", doc.owner_user_id)
    _validate_document_metadata_fields(next_visibility, next_classification)
    if next_owner_id:
        owner_membership = session.get(TeamMember, (team_id, next_owner_id))
        if owner_membership is None or owner_membership.status != "active":
            raise ApiError(400, "INVALID_ARGUMENT", "Document owner is not a team member.")
    for field, value in updates.items():
        setattr(doc, field, value)
    version_values = body.get("version_values")
    if version_values is not None:
        if not isinstance(version_values, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in version_values
        ):
            raise ApiError(
                400,
                "INVALID_ARGUMENT",
                "version_values must be an array of non-empty strings.",
            )
        doc.version_values = json.dumps(
            list(dict.fromkeys(item.strip() for item in version_values))
        )
    doc.version += 1
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="document.update",
        resource_type="document",
        resource_id=doc.id,
        details={
            "kb_id": doc.knowledge_base_id,
            "visibility": doc.visibility,
            "data_classification": doc.data_classification,
            "owner_user_id": doc.owner_user_id,
        },
    )
    session.commit()
    run, generation_id = _prepare_rebuild_document(
        doc,
        session,
        request.app.state.settings,
    )
    _dispatch_ingestion(
        doc,
        run,
        session,
        request.app.state.settings,
        generation_id=generation_id,
    )
    return envelope(_document_view(doc), request.state.request_id)


@router.post("/docs/delete", status_code=202)
def delete_document(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    document_id = body.get("document_id", "")
    doc = _manage_document_or_error(session, team_id, document_id, user)
    if doc.doc_status == "deleting":
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Document is already being deleted.")
    if doc.doc_status == "deleted" and doc.deleted_at is not None:
        return envelope(_document_view(doc), request.state.request_id)
    doc.doc_status = "deleting"
    doc.deleted_at = utc_now()
    doc.version += 1
    session.commit()
    generation_id = _active_generation_id(session, team_id)
    chunks = session.scalars(
        select(ChunkRecord).where(ChunkRecord.document_id == document_id)
    ).all()
    if request.app.state.settings.enable_indexing and generation_id:
        try:
            for chunk in chunks:
                asyncio.run(
                    set_chunk_status_in_indexes(
                        request.app.state.settings,
                        generation_id,
                        chunk.id,
                        "disabled",
                    )
                )
            asyncio.run(
                delete_document_from_indexes(
                    request.app.state.settings, generation_id, document_id
                )
            )
        except Exception as error:
            _set_document_chunk_state(
                session,
                document_id,
                document_status="deleting",
                chunk_status="disabled",
            )
            session.commit()
            raise ApiError(
                503,
                "INDEX_MAINTENANCE_UNAVAILABLE",
                "The document could not be removed from every index.",
            ) from error
    _set_document_chunk_state(
        session,
        document_id,
        document_status="deleted",
        chunk_status="disabled",
    )
    doc.doc_status = "deleted"
    _refresh_generation_count(session, generation_id)
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="document.delete",
        resource_type="document",
        resource_id=doc.id,
        details={
            "kb_id": doc.knowledge_base_id,
            "status": "deleted",
            "deleted_at": doc.deleted_at,
            "retention_days": request.app.state.settings.document_retention_days,
        },
    )
    session.commit()
    return envelope(_document_view(doc), request.state.request_id)


@router.post("/docs/restore", status_code=202)
def restore_document(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    document_id = body.get("document_id", "")
    doc = _manage_document_or_error(session, team_id, document_id, user)
    if retention_expired(doc, request.app.state.settings):
        try:
            purge_document_record(
                session,
                doc,
                request.app.state.settings,
            )
            write_audit(
                session,
                team_id=team_id,
                actor_id=user.id,
                action="document.restore.rejected",
                resource_type="document",
                resource_id=doc.id,
                details={"reason": "retention_expired"},
            )
            session.commit()
        except DocumentPurgeError:
            session.rollback()
        raise ApiError(
            409,
            "RETENTION_EXPIRED",
            "The document restore window has expired.",
        )
    if doc.doc_status not in {"deleted", "deleting", "failed"}:
        raise ApiError(
            409,
            "RESOURCE_STATE_CONFLICT",
            "Only a deleted or failed document can be restored.",
        )
    doc.deleted_at = None
    doc.purged_at = None
    doc.version += 1
    run, generation_id = _prepare_rebuild_document(
        doc,
        session,
        request.app.state.settings,
    )
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="document.restore",
        resource_type="document",
        resource_id=doc.id,
        details={"kb_id": doc.knowledge_base_id, "run_id": run.id},
    )
    session.commit()
    _dispatch_ingestion(
        doc,
        run,
        session,
        request.app.state.settings,
        generation_id=generation_id,
    )
    return envelope(_document_view(doc), request.state.request_id)


@router.get("/docs/versions")
def list_document_versions(
    request: Request,
    team_id: str,
    document_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _document_or_error(session, team_id, document_id, user)
    return paginate_scalars(
        session,
        select(DocumentVersion).where(DocumentVersion.document_id == document_id),
        timestamp_column=DocumentVersion.created_at,
        id_column=DocumentVersion.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda row: {
            "id": row.id,
            "content_fingerprint": row.content_fingerprint,
            "file_size_bytes": row.file_size_bytes,
            "status": row.status,
            "index_generation": row.index_generation,
            "chunk_count": row.chunk_count,
            "created_at": row.created_at.isoformat(),
        },
    )


@router.get("/docs/grants")
def list_document_grants(
    request: Request,
    team_id: str,
    document_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _manage_document_or_error(session, team_id, document_id, user)
    return paginate_scalars(
        session,
        select(DocumentGrant).where(DocumentGrant.document_id == document_id),
        timestamp_column=DocumentGrant.created_at,
        id_column=DocumentGrant.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda row: {
            "id": row.id,
            "user_id": row.user_id,
            "granted_by": row.granted_by,
            "created_at": row.created_at.isoformat(),
        },
    )


@router.post("/docs/grants/create", status_code=201)
def create_document_grant(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    document_id = body.get("document_id", "")
    grant_user_id = body.get("user_id", "")
    _manage_document_or_error(session, team_id, document_id, user)
    grantee = session.get(TeamMember, (team_id, grant_user_id))
    if grantee is None or grantee.status != "active":
        raise ApiError(404, "NOT_FOUND", "Team member was not found.")
    existing = session.scalar(
        select(DocumentGrant).where(
            DocumentGrant.document_id == document_id,
            DocumentGrant.user_id == grant_user_id,
        )
    )
    if existing is not None:
        raise ApiError(409, "DUPLICATE_RESOURCE", "Document grant already exists.")
    grant = DocumentGrant(document_id=document_id, user_id=grant_user_id, granted_by=user.id)
    session.add(grant)
    session.flush()
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="document.grant.create",
        resource_type="document",
        resource_id=document_id,
        details={"user_id": grant_user_id, "grant_id": grant.id},
    )
    session.commit()
    return envelope({"id": grant.id, "user_id": grant.user_id}, request.state.request_id)


@router.post("/docs/grants/revoke")
def revoke_document_grant(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    grant_id = body.get("grant_id", "")
    grant = session.get(DocumentGrant, grant_id)
    if grant is None:
        raise ApiError(404, "NOT_FOUND", "Grant was not found.")
    _manage_document_or_error(session, team_id, grant.document_id, user)
    session.delete(grant)
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="document.grant.revoke",
        resource_type="document",
        resource_id=grant.document_id,
        details={"user_id": grant.user_id, "grant_id": grant.id},
    )
    session.commit()
    return envelope({"revoked": grant_id}, request.state.request_id)


@router.get("/docs/download-url")
def document_download_url(
    request: Request,
    team_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    document = _document_or_error(session, team_id, document_id, user)
    if document.doc_status in {"deleted", "deleting"}:
        raise ApiError(404, "NOT_FOUND", "Document was not found.")
    try:
        url = presign_s3_download_url(
            document.object_uri
            or (
                document.source_uri
                if (document.source_uri or "").startswith("s3://")
                else ""
            ),
            request.app.state.settings,
        )
    except StoragePresignUnavailable as error:
        raise ApiError(
            503,
            "STORAGE_PRESIGN_UNAVAILABLE",
            "Signed download URLs are unavailable.",
        ) from error
    return envelope(
        {
            "url": url,
            "expires_in": request.app.state.settings.download_url_ttl_seconds,
        },
        request.state.request_id,
    )


@router.get("/docs/download")
def download_document(
    request: Request,
    team_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    document = _document_or_error(session, team_id, document_id, user)
    if document.doc_status in {"deleted", "deleting"}:
        raise ApiError(404, "NOT_FOUND", "Document was not found.")
    local_path = Path(document.source_uri) if document.source_uri else None
    if (local_path is None or not local_path.exists()) and document.object_uri:
        destination = (
            Path(request.app.state.settings.upload_dir)
            / "cache"
            / (document.id + ".download")
        )
        try:
            local_path = download_s3_object(
                document.object_uri,
                destination,
                request.app.state.settings,
            )
        except ObjectStorageUnavailable as error:
            raise ApiError(
                404,
                "NOT_FOUND",
                "Document source is unavailable.",
            ) from error
    if local_path is None or not local_path.exists():
        raise ApiError(404, "NOT_FOUND", "Document source is unavailable.")
    return FileResponse(local_path, filename=document.file_name)


@router.post("/docs/rebuild", status_code=202)
def rebuild_document(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    document_id = body.get("document_id", "")
    document = _manage_document_or_error(session, team_id, document_id, user)
    run, generation_id = _prepare_rebuild_document(
        document,
        session,
        request.app.state.settings,
    )
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="document.rebuild",
        resource_type="document",
        resource_id=document.id,
        details={"kb_id": document.knowledge_base_id, "run_id": run.id},
    )
    session.commit()
    _dispatch_ingestion(
        document,
        run,
        session,
        request.app.state.settings,
        generation_id=generation_id,
    )
    return envelope(
        {
            "document_id": document.id,
            "ingestion_run_id": run.id,
            "status": run.status,
        },
        request.state.request_id,
    )


@router.get("/docs/tasks")
def document_tasks(
    request: Request,
    team_id: str,
    document_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    document = _document_or_error(session, team_id, document_id, user)
    query = (
        select(IngestionRun)
        .join(DocumentVersion, IngestionRun.document_version_id == DocumentVersion.id)
        .where(DocumentVersion.document_id == document.id)
    )
    return paginate_scalars(
        session,
        query,
        timestamp_column=IngestionRun.created_at,
        id_column=IngestionRun.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda run: {
            "id": run.id,
            "status": run.status,
            "current_stage": run.current_stage,
            "stage_progress_pct": run.stage_progress_pct,
            "error_code": run.error_code,
            "created_at": run.created_at.isoformat(),
        },
    )


@router.get("/docs/version")
def document_version_detail(
    request: Request,
    team_id: str,
    document_id: str,
    version_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _document_or_error(session, team_id, document_id, user)
    version = session.get(DocumentVersion, version_id)
    if version is None or version.document_id != document_id:
        raise ApiError(404, "NOT_FOUND", "Document version was not found.")
    return envelope(
        {
            "id": version.id,
            "document_id": version.document_id,
            "content_fingerprint": version.content_fingerprint,
            "file_size_bytes": version.file_size_bytes,
            "status": version.status,
            "index_generation": version.index_generation,
            "chunk_count": version.chunk_count,
            "created_at": version.created_at.isoformat(),
        },
        request.state.request_id,
    )


@router.get("/docs/chunks")
def document_chunks(
    request: Request,
    team_id: str,
    document_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _document_or_error(session, team_id, document_id, user)
    return paginate_scalars(
        session,
        select(ChunkRecord).where(ChunkRecord.document_id == document_id),
        timestamp_column=ChunkRecord.created_at,
        id_column=ChunkRecord.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda chunk: {
            "id": chunk.id,
            "document_id": chunk.document_id,
            "content": chunk.content,
            "heading_path": json.loads(chunk.heading_path or "[]"),
            "status": chunk.status,
            "version": chunk.version,
        },
        descending=False,
    )


def _run_or_error(
    session: Session,
    team_id: str,
    run_id: str,
    user: User,
    *,
    manage: bool = False,
) -> IngestionRun:
    row = session.execute(
        select(IngestionRun, Document)
        .join(DocumentVersion, IngestionRun.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(IngestionRun.id == run_id, KnowledgeBase.team_id == team_id)
    ).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Ingestion run was not found.")
    run, document = row
    _document_or_error(session, team_id, document.id, user, manage=manage)
    return run


@router.get("/ingestions/events")
def ingestion_events(
    request: Request,
    team_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    run = _run_or_error(session, team_id, run_id, user)
    session_factory = request.app.state.session_factory

    async def events():
        previous = None
        while True:
            with session_factory() as event_session:
                current = event_session.get(IngestionRun, run_id)
                if current is None:
                    return
                payload = {
                    "run_id": current.id,
                    "status": current.status,
                    "stage": current.current_stage,
                    "percent": current.stage_progress_pct,
                    "error_code": current.error_code,
                    "retryable": current.retryable,
                }
                status = current.status

            if payload != previous:
                event = {
                    "completed": "completed",
                    "failed": "failed",
                    "cancelled": "cancelled",
                }.get(status, "progress")
                yield "event: {0}\ndata: {1}\n\n".format(
                    event,
                    json.dumps(payload, ensure_ascii=False),
                )
                previous = payload
            if status in {"completed", "failed", "cancelled"}:
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/ingestions/retry", status_code=202)
def retry_ingestion(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    run_id = body.get("run_id", "")
    run = _run_or_error(session, team_id, run_id, user, manage=True)
    if run.status not in {"failed", "cancelled"}:
        raise ApiError(
            409,
            "RESOURCE_STATE_CONFLICT",
            "Only failed or cancelled runs can be retried.",
        )
    version = session.get(DocumentVersion, run.document_version_id)
    if version is None:
        raise ApiError(404, "NOT_FOUND", "Document version was not found.")
    document = _manage_document_or_error(session, team_id, version.document_id, user)
    run.status = "queued"
    run.current_stage = "queued"
    run.stage_progress_pct = 0
    run.error_code = None
    document.doc_status = "building"
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="ingestion.retry",
        resource_type="ingestion_run",
        resource_id=run.id,
        details={"document_id": document.id},
    )
    session.commit()
    _dispatch_ingestion(
        document,
        run,
        session,
        request.app.state.settings,
        generation_id=_active_generation_id(session, team_id),
    )
    return envelope(
        {"run_id": run.id, "status": run.status, "stage": run.current_stage},
        request.state.request_id,
    )


@router.post("/ingestions/cancel", status_code=202)
def cancel_ingestion(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    run_id = body.get("run_id", "")
    run = _run_or_error(session, team_id, run_id, user, manage=True)
    if run.status in {"completed", "failed"}:
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Run is already finished.")
    if run.current_stage in {"indexing", "validating"}:
        raise ApiError(
            409,
            "RESOURCE_STATE_CONFLICT",
            "Indexing has started and the run can no longer be cancelled.",
        )
    run.status = "cancelled"
    run.current_stage = "cancelled"
    run.retryable = True
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="ingestion.cancel",
        resource_type="ingestion_run",
        resource_id=run.id,
        details={"status": "cancelled"},
    )
    session.commit()
    return envelope(
        {"run_id": run.id, "status": run.status}, request.state.request_id
    )
