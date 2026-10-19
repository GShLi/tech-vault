import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import AuditLog, ChunkRecord, IndexGenerationRecord, User


router = APIRouter(tags=["audit"])


def _audit_view(record: AuditLog) -> dict:
    return {
        "id": record.id,
        "team_id": record.team_id,
        "actor_id": record.actor_id,
        "action": record.action,
        "resource_type": record.resource_type,
        "resource_id": record.resource_id,
        "details": json.loads(record.details or "{}"),
        "created_at": record.created_at.isoformat(),
    }


def _generation_view(record: IndexGenerationRecord) -> dict:
    return {
        "id": record.id,
        "team_id": record.team_id,
        "status": record.status,
        "chunk_count": record.chunk_count,
        "embedding_model": record.embedding_model,
        "error_message": record.error_message,
        "validation_errors": json.loads(record.validation_errors or "[]"),
        "created_at": record.created_at.isoformat(),
        "validated_at": record.validated_at.isoformat()
        if record.validated_at is not None
        else None,
        "activated_at": record.activated_at.isoformat()
        if record.activated_at is not None
        else None,
    }


def _generation_or_error(
    session: Session, team_id: str, generation_id: str
) -> IndexGenerationRecord:
    generation = session.get(IndexGenerationRecord, generation_id)
    if generation is None or generation.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Index generation was not found.")
    return generation


def _audit(
    session: Session,
    team_id: str,
    actor_id: str,
    action: str,
    generation_id: str,
    details: Optional[dict] = None,
) -> None:
    session.add(
        AuditLog(
            team_id=team_id,
            actor_id=actor_id,
            action=action,
            resource_type="index_generation",
            resource_id=generation_id,
            details=json.dumps(details or {}, separators=(",", ":")),
        )
    )


def _validate_generation(
    session: Session, generation: IndexGenerationRecord
) -> dict:
    chunks = session.scalars(
        select(ChunkRecord).where(
            ChunkRecord.team_id == generation.team_id,
            ChunkRecord.index_generation == generation.id,
        )
    ).all()
    errors = []
    if not chunks:
        errors.append("generation contains no chunks")
    if len(chunks) != generation.chunk_count:
        errors.append(
            "chunk_count mismatch: expected {0}, found {1}".format(
                generation.chunk_count, len(chunks)
            )
        )
    for chunk in chunks:
        if not chunk.content.strip():
            errors.append("empty content: " + chunk.id)
        if (
            chunk.team_id != generation.team_id
            or not chunk.knowledge_base_id
            or not chunk.owner_user_id
        ):
            errors.append("missing authorization scope: " + chunk.id)

    passed = not errors
    now = datetime.now(timezone.utc)
    generation.validated_at = now
    generation.validation_errors = json.dumps(errors, separators=(",", ":"))
    generation.error_message = None if passed else "; ".join(errors)
    generation.status = "validated" if passed else "failed"
    return {
        "generation_id": generation.id,
        "passed": passed,
        "errors": errors,
        "checked_chunks": len(chunks),
        "validated_at": now.isoformat(),
    }


def _cursor_filter(query, model, cursor):
    if cursor is None:
        return query
    after_created, after_id = decode_cursor(cursor)
    return query.where(
        or_(
            model.created_at < after_created,
            and_(model.created_at == after_created, model.id < after_id),
        )
    )


def _page(session: Session, query, model, limit: int, request: Request, view):
    page_limit = max(1, min(limit, 100))
    rows = session.scalars(
        query.order_by(model.created_at.desc(), model.id.desc()).limit(page_limit + 1)
    ).all()
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    next_cursor = (
        encode_cursor(page_rows[-1].created_at, page_rows[-1].id)
        if has_more and page_rows
        else None
    )
    return page_envelope(
        [view(row) for row in page_rows], request.state.request_id, next_cursor
    )


@router.get("/audit")
def list_audit(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    query = _cursor_filter(
        select(AuditLog).where(AuditLog.team_id == team_id), AuditLog, cursor
    )
    return _page(session, query, AuditLog, limit, request, _audit_view)


@router.get("/audit/detail")
def get_audit(
    request: Request,
    team_id: str,
    audit_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    record = session.get(AuditLog, audit_id)
    if record is None or record.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Audit record was not found.")
    return envelope(_audit_view(record), request.state.request_id)


@router.get("/generations")
def list_generations(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    query = _cursor_filter(
        select(IndexGenerationRecord).where(
            IndexGenerationRecord.team_id == team_id
        ),
        IndexGenerationRecord,
        cursor,
    )
    return _page(
        session, query, IndexGenerationRecord, limit, request, _generation_view
    )


@router.get("/generations/detail")
def get_generation(
    request: Request,
    team_id: str,
    generation_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    generation = _generation_or_error(session, team_id, generation_id)
    return envelope(_generation_view(generation), request.state.request_id)


@router.get("/generations/validation")
def get_generation_validation(
    request: Request,
    team_id: str,
    generation_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    generation = _generation_or_error(session, team_id, generation_id)
    chunks = session.scalars(
        select(ChunkRecord).where(
            ChunkRecord.team_id == team_id,
            ChunkRecord.index_generation == generation_id,
        )
    ).all()
    return envelope(
        {
            "generation_id": generation.id,
            "passed": generation.status in {"validated", "active"},
            "errors": json.loads(generation.validation_errors or "[]"),
            "checked_chunks": len(chunks),
            "validated_at": generation.validated_at.isoformat()
            if generation.validated_at is not None
            else None,
        },
        request.state.request_id,
    )


@router.post("/generations/validate", status_code=202)
def validate_generation(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    generation = _generation_or_error(session, team_id, body.get("generation_id", ""))
    if generation.status == "active":
        result = {
            "generation_id": generation.id,
            "status": generation.status,
            "passed": True,
            "errors": [],
            "checked_chunks": generation.chunk_count,
            "validated_at": generation.validated_at.isoformat()
            if generation.validated_at is not None
            else None,
        }
    else:
        generation.status = "validating"
        session.commit()
        result = _validate_generation(session, generation)
        result["status"] = generation.status
        _audit(
            session,
            team_id,
            user.id,
            "generation.validate",
            generation.id,
            {"generation_id": generation.id, "passed": result["passed"]},
        )
        session.commit()
    return envelope(result, request.state.request_id)


@router.post("/generations/activate", status_code=202)
def activate_generation(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    generation = _generation_or_error(session, team_id, body.get("generation_id", ""))
    if generation.status != "validated":
        raise ApiError(
            409,
            "GENERATION_NOT_VALIDATED",
            "The index generation must be validated before activation.",
        )

    active_rows = session.scalars(
        select(IndexGenerationRecord).where(
            IndexGenerationRecord.team_id == team_id,
            IndexGenerationRecord.status == "active",
        )
    ).all()
    for active in active_rows:
        active.status = "validated"
    generation.status = "active"
    generation.activated_at = datetime.now(timezone.utc)
    _audit(
        session,
        team_id,
        user.id,
        "generation.activate",
        generation.id,
        {
            "generation_id": generation.id,
            "previous_generation_ids": [row.id for row in active_rows],
        },
    )
    session.commit()
    return envelope(_generation_view(generation), request.state.request_id)


@router.post("/generations/rollback", status_code=202)
def rollback_generation(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    active = session.scalar(
        select(IndexGenerationRecord)
        .where(
            IndexGenerationRecord.team_id == team_id,
            IndexGenerationRecord.status == "active",
        )
        .order_by(IndexGenerationRecord.activated_at.desc())
    )
    if active is None:
        raise ApiError(409, "NO_ACTIVE_GENERATION", "No active generation exists.")
    previous = session.scalar(
        select(IndexGenerationRecord)
        .where(
            IndexGenerationRecord.team_id == team_id,
            IndexGenerationRecord.id != active.id,
            IndexGenerationRecord.status == "validated",
            IndexGenerationRecord.activated_at.is_not(None),
        )
        .order_by(IndexGenerationRecord.activated_at.desc())
    )
    if previous is None:
        raise ApiError(
            409,
            "NO_PREVIOUS_GENERATION",
            "No previous active generation is available for rollback.",
        )

    active.status = "validated"
    previous.status = "active"
    previous.activated_at = datetime.now(timezone.utc)
    _audit(
        session,
        team_id,
        user.id,
        "generation.rollback",
        previous.id,
        {"generation_id": previous.id, "previous_generation_id": active.id},
    )
    session.commit()
    return envelope(_generation_view(previous), request.state.request_id)
