import json
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.storage import remove_file, store_file
from backend.app.api.v1.schemas import DocumentDetailView, DocumentView, IngestionRunView
from backend.app.api.v1.teams import _if_match_version, _leader_or_error, _membership_or_error
from backend.app.core.ids import new_ulid
from backend.app.rag.ingestion.processor import process_markdown
from backend.app.db.models import (
    Document,
    ChunkRecord,
    DocumentVersion,
    IngestionRun,
    KnowledgeBase,
    User,
)


router = APIRouter(tags=["docs"])

_MAX_FILE_BYTES = 50 * 1024 * 1024
_ALLOWED_EXTENSIONS = frozenset({".md", ".txt", ".pdf", ".docx"})


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
        version=document.version,
        created_at=document.created_at,
        updated_at=document.updated_at,
    ).model_dump()


def _kb_or_error(session: Session, team_id: str, kb_id: str) -> KnowledgeBase:
    knowledge_base = session.get(KnowledgeBase, kb_id)
    if knowledge_base is None or knowledge_base.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    return knowledge_base


def _document_or_error(session: Session, team_id: str, document_id: str) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise ApiError(404, "NOT_FOUND", "Document was not found.")
    knowledge_base = session.get(KnowledgeBase, document.knowledge_base_id)
    if knowledge_base is None or knowledge_base.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Document was not found.")
    return document


@router.post("/docs/upload", status_code=202)
def upload_document(
    request: Request,
    team_id: str = Form(...),
    kb_id: str = Form(...),
    file: UploadFile = Form(...),
    metadata: Optional[str] = Form(None),
    visibility: str = Form("team_shared"),
    data_classification: str = Form("internal"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _kb_or_error(session, team_id, kb_id)

    if file.filename is None or not file.filename.strip():
        raise ApiError(400, "INVALID_ARGUMENT", "A file name is required.")
    ext = "." + file.filename.rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise ApiError(
            400, "INVALID_ARGUMENT",
            "Supported file types are: " + ", ".join(sorted(_ALLOWED_EXTENSIONS))
        )

    meta = {}
    if metadata:
        try:
            meta = json.loads(metadata)
        except json.JSONDecodeError as err:
            raise ApiError(400, "INVALID_ARGUMENT", "metadata must be valid JSON") from err

    document_id = new_ulid()
    version_id = new_ulid()
    run_id = new_ulid()
    document_version_id = str(version_id)
    content_fingerprint = "sync-" + document_id
    stored_file = store_file(file.file, file.filename, document_id)
    if stored_file.size_bytes > _MAX_FILE_BYTES:
        remove_file(stored_file)
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "File exceeds the 50 MB limit.")

    document = Document(
        id=document_id,
        knowledge_base_id=kb_id,
        owner_user_id=user.id,
        file_name=file.filename,
        source_uri=str(stored_file.path),
        product=meta.get("product"),
        version_values=json.dumps(meta.get("version_values", [])),
        visibility=visibility,
        data_classification=data_classification,
        doc_status="building",
        current_version_id=version_id,
    )
    session.add(document)

    version = DocumentVersion(
        id=version_id,
        document_id=document_id,
        content_fingerprint=content_fingerprint,
        file_size_bytes=stored_file.size_bytes,
        status="building",
    )
    session.add(version)

    ingestion_run = IngestionRun(
        id=run_id,
        document_version_id=version_id,
        status="queued",
        current_stage="parsing",
        stage_progress_pct=0,
    )
    session.add(ingestion_run)
    session.commit()

    if ext in {".md", ".txt"}:
        from backend.app.rag.ingestion.processor import process_markdown

        process_markdown(document, ingestion_run, session, request.app.state.settings)

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
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _kb_or_error(session, team_id, kb_id)
    page_limit = max(1, min(limit, 100))

    query = select(Document).where(
        Document.knowledge_base_id == kb_id,
        Document.doc_status != "deleted",
    )
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
    document = _document_or_error(session, team_id, document_id)
    return envelope(
        DocumentDetailView(
            id=document.id,
            knowledge_base_id=document.knowledge_base_id,
            owner_user_id=document.owner_user_id,
            file_name=document.file_name,
            source_type=document.source_type,
            source_uri=document.source_uri,
            product=document.product,
            version_family=document.version_family,
            version_values=json.loads(document.version_values) if document.version_values else [],
            visibility=document.visibility,
            data_classification=document.data_classification,
            doc_status=document.doc_status,
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
    )
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
    return page_envelope(
        [
            IngestionRunView(
                id=run.id,
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
    _membership_or_error(session, team_id, user.id)
    run = session.scalar(
        select(IngestionRun)
        .join(DocumentVersion, IngestionRun.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(IngestionRun.id == run_id, KnowledgeBase.team_id == team_id)
    )
    if run is None:
        raise ApiError(404, "NOT_FOUND", "Ingestion run was not found.")
    return envelope(
        IngestionRunView(
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
    _leader_or_error(session, team_id, user.id)
    doc = _document_or_error(session, team_id, document_id)
    expected_version = _if_match_version(request)
    if doc.version != expected_version:
        raise ApiError(409, "VERSION_CONFLICT", "Resource version has changed.")

    for field in ("file_name", "product", "visibility", "data_classification"):
        value = body.get(field)
        if value is not None:
            setattr(doc, field, value)
    version_values = body.get("version_values")
    if version_values is not None:
        doc.version_values = json.dumps(version_values)
    doc.version += 1
    session.commit()
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
    _leader_or_error(session, team_id, user.id)
    doc = _document_or_error(session, team_id, document_id)
    if doc.doc_status == "deleting":
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Document is already being deleted.")
    doc.doc_status = "deleting"
    doc.version += 1
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
    _leader_or_error(session, team_id, user.id)
    doc = _document_or_error(session, team_id, document_id)
    doc.doc_status = "building"
    doc.version += 1
    session.commit()
    return envelope(_document_view(doc), request.state.request_id)


@router.get("/docs/versions")
def list_document_versions(
    request: Request,
    team_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _document_or_error(session, team_id, document_id)
    versions = session.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == document_id).order_by(DocumentVersion.created_at.desc()).limit(50)
    ).all()
    return envelope(
        [{"id": v.id, "content_fingerprint": v.content_fingerprint, "file_size_bytes": v.file_size_bytes, "status": v.status, "index_generation": v.index_generation, "chunk_count": v.chunk_count, "created_at": v.created_at.isoformat()} for v in versions],
        request.state.request_id,
    )


@router.get("/docs/grants")
def list_document_grants(
    request: Request,
    team_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _document_or_error(session, team_id, document_id)
    grants = session.scalars(select(DocumentGrant).where(DocumentGrant.document_id == document_id)).all()
    return envelope([{"id": g.id, "user_id": g.user_id, "granted_by": g.granted_by, "created_at": g.created_at.isoformat()} for g in grants], request.state.request_id)


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
    _leader_or_error(session, team_id, user.id)
    _document_or_error(session, team_id, document_id)
    grant = DocumentGrant(document_id=document_id, user_id=grant_user_id, granted_by=user.id)
    session.add(grant)
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
    _leader_or_error(session, team_id, user.id)
    grant = session.get(DocumentGrant, grant_id)
    if grant is None:
        raise ApiError(404, "NOT_FOUND", "Grant was not found.")
    _document_or_error(session, team_id, grant.document_id)
    session.delete(grant)
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
    _document_or_error(session, team_id, document_id)
    return envelope(
        {
            "url": "/api/v1/docs/download?team_id={0}&document_id={1}".format(
                team_id, document_id
            ),
            "expires_in": 300,
        },
        request.state.request_id,
    )


@router.get("/docs/download")
def download_document(
    team_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    document = _document_or_error(session, team_id, document_id)
    if not document.source_uri:
        raise ApiError(404, "NOT_FOUND", "Document source is unavailable.")
    return FileResponse(document.source_uri, filename=document.file_name)


@router.post("/docs/rebuild", status_code=202)
def rebuild_document(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    document_id = body.get("document_id", "")
    _leader_or_error(session, team_id, user.id)
    document = _document_or_error(session, team_id, document_id)
    run = IngestionRun(
        id=new_ulid(),
        document_version_id=document.current_version_id or "",
        status="queued",
        current_stage="parsing",
        stage_progress_pct=0,
    )
    document.doc_status = "building"
    session.add(run)
    session.commit()
    process_markdown(document, run, session, request.app.state.settings)
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
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    document = _document_or_error(session, team_id, document_id)
    runs = session.scalars(
        select(IngestionRun)
        .join(DocumentVersion, IngestionRun.document_version_id == DocumentVersion.id)
        .where(DocumentVersion.document_id == document.id)
        .order_by(IngestionRun.created_at.desc())
        .limit(50)
    ).all()
    return envelope(
        [
            {
                "id": run.id,
                "status": run.status,
                "current_stage": run.current_stage,
                "stage_progress_pct": run.stage_progress_pct,
                "error_code": run.error_code,
                "created_at": run.created_at.isoformat(),
            }
            for run in runs
        ],
        request.state.request_id,
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
    _document_or_error(session, team_id, document_id)
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
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _document_or_error(session, team_id, document_id)
    chunks = session.scalars(
        select(ChunkRecord)
        .where(ChunkRecord.document_id == document_id)
        .order_by(ChunkRecord.created_at.asc())
    ).all()
    return envelope(
        [
            {
                "id": chunk.id,
                "document_id": chunk.document_id,
                "content": chunk.content,
                "heading_path": json.loads(chunk.heading_path or "[]"),
                "status": chunk.status,
                "version": chunk.version,
            }
            for chunk in chunks
        ],
        request.state.request_id,
    )


def _run_or_error(session: Session, team_id: str, run_id: str) -> IngestionRun:
    run = session.scalar(
        select(IngestionRun)
        .join(DocumentVersion, IngestionRun.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(IngestionRun.id == run_id, KnowledgeBase.team_id == team_id)
    )
    if run is None:
        raise ApiError(404, "NOT_FOUND", "Ingestion run was not found.")
    return run


@router.get("/ingestions/events")
def ingestion_events(
    request: Request,
    team_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    run = _run_or_error(session, team_id, run_id)
    payload = {
        "run_id": run.id,
        "status": run.status,
        "stage": run.current_stage,
        "percent": run.stage_progress_pct,
        "error_code": run.error_code,
        "retryable": run.retryable,
    }
    async def events():
        import json as _json
        yield "event: progress\ndata: {0}\n\n".format(
            _json.dumps(payload, ensure_ascii=False)
        )
        event = "completed" if run.status == "completed" else "failed"
        yield "event: {0}\ndata: {1}\n\n".format(
            event, _json.dumps(payload, ensure_ascii=False)
        )
    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/ingestions/retry", status_code=202)
def retry_ingestion(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    run_id = body.get("run_id", "")
    _leader_or_error(session, team_id, user.id)
    run = _run_or_error(session, team_id, run_id)
    version = session.get(DocumentVersion, run.document_version_id)
    if version is None:
        raise ApiError(404, "NOT_FOUND", "Document version was not found.")
    document = _document_or_error(session, team_id, version.document_id)
    run.status = "queued"
    run.current_stage = "parsing"
    run.stage_progress_pct = 0
    run.error_code = None
    document.doc_status = "building"
    session.commit()
    process_markdown(document, run, session, request.app.state.settings)
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
    _leader_or_error(session, team_id, user.id)
    run = _run_or_error(session, team_id, run_id)
    if run.status in {"completed", "failed"}:
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Run is already finished.")
    run.status = "cancelled"
    run.current_stage = "cancelled"
    run.retryable = True
    session.commit()
    return envelope(
        {"run_id": run.id, "status": run.status}, request.state.request_id
    )
