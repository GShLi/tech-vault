import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.v1.teams import _membership_or_error
from backend.app.db.models import TraceRecord, User


router = APIRouter(tags=["traces"])


def _trace_view(trace: TraceRecord) -> dict:
    return {
        "id": trace.id,
        "trace_id": trace.trace_id,
        "team_id": trace.team_id,
        "chat_id": trace.chat_id,
        "message_id": trace.message_id,
        "engine_mode": trace.engine_mode,
        "original_query": trace.original_query,
        "rewritten_query": trace.rewritten_query,
        "filters": json.loads(trace.filters or "{}"),
        "bm25_candidates": json.loads(trace.bm25_candidates or "[]"),
        "dense_candidates": json.loads(trace.dense_candidates or "[]"),
        "rrf_candidates": json.loads(trace.rrf_candidates or "[]"),
        "rerank_candidates": json.loads(trace.rerank_candidates or "[]"),
        "final_context": json.loads(trace.final_context or "[]"),
        "stage_latency_ms": json.loads(trace.stage_latency_ms or "{}"),
        "degraded": trace.degraded,
        "error_code": trace.error_code,
        "model": json.loads(trace.model or "{}"),
        "created_at": trace.created_at.isoformat(),
    }


@router.get("/traces")
def list_traces(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    page_limit = max(1, min(limit, 100))
    query = select(TraceRecord).where(TraceRecord.team_id == team_id)
    if cursor is not None:
        after_created, after_id = decode_cursor(cursor)
        query = query.where(
            or_(
                TraceRecord.created_at < after_created,
                and_(
                    TraceRecord.created_at == after_created,
                    TraceRecord.id < after_id,
                ),
            )
        )
    rows = session.scalars(
        query.order_by(TraceRecord.created_at.desc(), TraceRecord.id.desc()).limit(
            page_limit + 1
        )
    ).all()
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    next_cursor = (
        encode_cursor(page_rows[-1].created_at, page_rows[-1].id)
        if has_more and page_rows
        else None
    )
    return page_envelope(
        [_trace_view(trace) for trace in page_rows],
        request.state.request_id,
        next_cursor,
    )


@router.get("/traces/detail")
def get_trace(
    request: Request,
    team_id: str,
    trace_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    trace = session.scalar(
        select(TraceRecord).where(
            TraceRecord.team_id == team_id, TraceRecord.trace_id == trace_id
        )
    )
    if trace is None:
        raise ApiError(404, "NOT_FOUND", "Trace was not found.")
    return envelope(_trace_view(trace), request.state.request_id)


@router.get("/traces/export")
def export_trace(
    request: Request,
    team_id: str,
    trace_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    trace = session.scalar(
        select(TraceRecord).where(
            TraceRecord.team_id == team_id, TraceRecord.trace_id == trace_id
        )
    )
    if trace is None:
        raise ApiError(404, "NOT_FOUND", "Trace was not found.")
    return envelope(_trace_view(trace), request.state.request_id)
