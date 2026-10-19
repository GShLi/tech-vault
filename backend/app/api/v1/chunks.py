import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.v1.documents import _document_or_error
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.core.ids import new_ulid
from backend.app.db.models import (
    ChunkHistory,
    ChunkRecord,
    Document,
    DocumentVersion,
    IngestionRun,
    KnowledgeBase,
    User,
)
from backend.app.rag.ingestion.processor import process_markdown


router = APIRouter(tags=["chunks"])


def _chunk_view(chunk: ChunkRecord) -> dict:
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "content": chunk.content,
        "heading_path": json.loads(chunk.heading_path) if chunk.heading_path else [],
        "source_locator": json.loads(chunk.source_locator) if chunk.source_locator else {},
        "status": chunk.status,
        "version": chunk.version,
        "created_at": chunk.created_at.isoformat(),
        "updated_at": chunk.updated_at.isoformat(),
    }


def _assert_chunks_in_team(session: Session, team_id: str, chunk_ids) -> None:
    ids = set(chunk_ids)
    rows = session.scalars(
        select(ChunkRecord)
        .join(Document, ChunkRecord.document_id == Document.id)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(ChunkRecord.id.in_(tuple(ids)), KnowledgeBase.team_id == team_id)
    ).all()
    if len(rows) != len(ids):
        raise ApiError(403, "PERMISSION_DENIED", "Chunk is not accessible.")


@router.get("/chunks")
def list_chunks(
    request: Request,
    team_id: str,
    document_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _document_or_error(session, team_id, document_id)
    page_limit = max(1, min(limit, 100))
    query = select(ChunkRecord).where(ChunkRecord.document_id == document_id)
    if cursor is not None:
        after_created, after_id = decode_cursor(cursor)
        query = query.where(
            or_(ChunkRecord.created_at < after_created,
                and_(ChunkRecord.created_at == after_created, ChunkRecord.id < after_id))
        )
    rows = session.scalars(query.order_by(ChunkRecord.created_at.desc(), ChunkRecord.id.desc()).limit(page_limit + 1)).all()
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    next_cursor = encode_cursor(page_rows[-1].created_at, page_rows[-1].id) if has_more and page_rows else None
    return page_envelope([_chunk_view(c) for c in page_rows], request.state.request_id, next_cursor)


@router.get("/chunks/detail")
def get_chunk(
    request: Request,
    team_id: str,
    chunk_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    chunk = session.get(ChunkRecord, chunk_id)
    if chunk is None:
        raise ApiError(404, "NOT_FOUND", "Chunk was not found.")
    _document_or_error(session, team_id, chunk.document_id)
    return envelope(_chunk_view(chunk), request.state.request_id)


@router.post("/chunks/disable")
def disable_chunks(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    chunk_ids = body.get("chunk_ids", [])
    if not chunk_ids:
        raise ApiError(400, "INVALID_ARGUMENT", "chunk_ids is required.")
    _leader_or_error(session, team_id, user.id)
    _assert_chunks_in_team(session, team_id, chunk_ids)
    session.execute(
        update(ChunkRecord)
        .where(ChunkRecord.id.in_(tuple(chunk_ids)))
        .values(status="disabled", version=ChunkRecord.version + 1)
    )
    session.commit()
    return envelope({"disabled": len(chunk_ids)}, request.state.request_id)


@router.post("/chunks/enable")
def enable_chunks(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    chunk_ids = body.get("chunk_ids", [])
    if not chunk_ids:
        raise ApiError(400, "INVALID_ARGUMENT", "chunk_ids is required.")
    _leader_or_error(session, team_id, user.id)
    _assert_chunks_in_team(session, team_id, chunk_ids)
    session.execute(
        update(ChunkRecord)
        .where(ChunkRecord.id.in_(tuple(chunk_ids)))
        .values(status="enabled", version=ChunkRecord.version + 1)
    )
    session.commit()
    return envelope({"enabled": len(chunk_ids)}, request.state.request_id)


@router.post("/chunks/update")
def update_chunk(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    chunk_id = body.get("chunk_id", "")
    content = body.get("content", "").strip()
    if not content:
        raise ApiError(400, "INVALID_ARGUMENT", "Chunk content is required.")
    _leader_or_error(session, team_id, user.id)
    chunk = session.get(ChunkRecord, chunk_id)
    if chunk is None:
        raise ApiError(404, "NOT_FOUND", "Chunk was not found.")
    _document_or_error(session, team_id, chunk.document_id)
    expected_version = int(
        request.headers.get("If-Match", "0").strip().strip('"')
    )
    if expected_version != chunk.version:
        raise ApiError(409, "VERSION_CONFLICT", "Resource version has changed.")
    session.add(
        ChunkHistory(
            chunk_id=chunk.id,
            action="update",
            old_content=chunk.content,
            new_content=content,
            actor_id=user.id,
        )
    )
    chunk.content = content
    chunk.version += 1
    session.commit()
    return envelope(_chunk_view(chunk), request.state.request_id)


@router.post("/chunks/regenerate", status_code=202)
def regenerate_chunks(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    document_id = body.get("document_id", "")
    _leader_or_error(session, team_id, user.id)
    document = _document_or_error(session, team_id, document_id)
    session.execute(delete(ChunkRecord).where(ChunkRecord.document_id == document.id))
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
        {"document_id": document.id, "run_id": run.id, "status": run.status},
        request.state.request_id,
    )


@router.get("/chunks/history")
def chunk_history(
    request: Request,
    team_id: str,
    chunk_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    chunk = session.get(ChunkRecord, chunk_id)
    if chunk is None:
        raise ApiError(404, "NOT_FOUND", "Chunk was not found.")
    _document_or_error(session, team_id, chunk.document_id)
    rows = session.scalars(
        select(ChunkHistory)
        .where(ChunkHistory.chunk_id == chunk_id)
        .order_by(ChunkHistory.created_at.desc())
    ).all()
    return envelope(
        [
            {
                "id": row.id,
                "action": row.action,
                "old_content": row.old_content,
                "new_content": row.new_content,
                "actor_id": row.actor_id,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        request.state.request_id,
    )


@router.post("/chunks/bulk")
def bulk_chunks(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    action = body.get("action", "disable")
    if action not in {"enable", "disable"}:
        raise ApiError(400, "INVALID_ARGUMENT", "action must be enable or disable.")
    if action == "enable":
        return enable_chunks(body, request, user, session)
    return disable_chunks(body, request, user, session)
