import json
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.v1.teams import _membership_or_error
from backend.app.db.models import Chat, Feedback, TraceRecord, User, sanitize_trace_context


router = APIRouter(tags=["traces"])


def _feedback_view(feedback: Feedback) -> dict:
    return {
        "id": feedback.id,
        "feedback_type": feedback.feedback_type,
        "comment": feedback.comment,
        "created_at": feedback.created_at.isoformat(),
    }


def _feedback_by_message(
    session: Session,
    team_id: str,
    message_ids: list[str],
) -> dict[str, list[Feedback]]:
    if not message_ids:
        return {}
    rows = session.scalars(
        select(Feedback)
        .where(
            Feedback.team_id == team_id,
            Feedback.message_id.in_(message_ids),
        )
        .order_by(Feedback.created_at.asc(), Feedback.id.asc())
    ).all()
    by_message: dict[str, list[Feedback]] = {}
    for feedback in rows:
        by_message.setdefault(feedback.message_id, []).append(feedback)
    return by_message


def _trace_view(
    trace: TraceRecord,
    feedback: Optional[List[Feedback]] = None,
) -> dict:
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
        "final_context": json.loads(sanitize_trace_context(trace.final_context)),
        "stage_latency_ms": json.loads(trace.stage_latency_ms or "{}"),
        "degraded": trace.degraded,
        "error_code": trace.error_code,
        "model": json.loads(trace.model or "{}"),
        "feedback": [_feedback_view(item) for item in feedback or []],
        "created_at": trace.created_at.isoformat(),
    }


def _trace_or_error(
    session: Session,
    team_id: str,
    trace_id: str,
    user: User,
) -> TraceRecord:
    membership = None
    if not user.is_super_admin:
        membership = _membership_or_error(session, team_id, user.id)
    trace = session.scalar(
        select(TraceRecord).where(
            TraceRecord.team_id == team_id, TraceRecord.trace_id == trace_id
        )
    )
    if trace is None:
        raise ApiError(404, "NOT_FOUND", "Trace was not found.")
    if user.is_super_admin or (membership is not None and membership.role == "leader"):
        return trace
    chat = session.get(Chat, trace.chat_id) if trace.chat_id else None
    if chat is not None and chat.team_id == team_id and chat.user_id == user.id:
        return trace
    raise ApiError(403, "PERMISSION_DENIED", "Trace is not accessible.")


@router.get("/traces")
def list_traces(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    membership = None
    if not user.is_super_admin:
        membership = _membership_or_error(session, team_id, user.id)
    page_limit = max(1, min(limit, 100))
    query = select(TraceRecord).where(TraceRecord.team_id == team_id)
    if membership is not None and membership.role != "leader":
        query = query.join(Chat, TraceRecord.chat_id == Chat.id).where(
            Chat.team_id == team_id,
            Chat.user_id == user.id,
        )
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
    feedback_by_message = _feedback_by_message(
        session,
        team_id,
        [trace.message_id for trace in page_rows if trace.message_id is not None],
    )
    return page_envelope(
        [
            _trace_view(
                trace,
                feedback_by_message.get(trace.message_id or "", []),
            )
            for trace in page_rows
        ],
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
    trace = _trace_or_error(session, team_id, trace_id, user)
    feedback_by_message = _feedback_by_message(
        session,
        team_id,
        [trace.message_id] if trace.message_id is not None else [],
    )
    return envelope(
        _trace_view(trace, feedback_by_message.get(trace.message_id or "", [])),
        request.state.request_id,
    )


@router.get("/traces/export")
def export_trace(
    request: Request,
    team_id: str,
    trace_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    trace = _trace_or_error(session, team_id, trace_id, user)
    feedback_by_message = _feedback_by_message(
        session,
        team_id,
        [trace.message_id] if trace.message_id is not None else [],
    )
    return envelope(
        _trace_view(trace, feedback_by_message.get(trace.message_id or "", [])),
        request.state.request_id,
    )
