import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import ChunkRecord, User


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
    session.execute(
        update(ChunkRecord)
        .where(ChunkRecord.id.in_(tuple(chunk_ids)))
        .values(status="enabled", version=ChunkRecord.version + 1)
    )
    session.commit()
    return envelope({"enabled": len(chunk_ids)}, request.state.request_id)
