import asyncio
import json
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import paginate_scalars
from backend.app.api.v1.documents import (
    _active_generation_id,
    _dispatch_ingestion,
    _document_or_error,
    _manage_document_or_error,
    _prepare_rebuild_document,
    _refresh_generation_count,
)
from backend.app.api.v1.teams import _membership_or_error
from backend.app.modules.audit.service import write_audit
from backend.app.rag.chunking.identity import content_fingerprint
from backend.app.rag.embedding.service import EmbeddingClient
from backend.app.rag.indexing.maintenance import (
    IndexMaintenanceError,
    set_chunk_status_in_indexes,
    update_chunk_in_indexes,
)
from backend.app.db.models import (
    ChunkHistory,
    ChunkOverride,
    ChunkRecord,
    Document,
    DocumentVersion,
    KnowledgeBase,
    User,
)
router = APIRouter(tags=["chunks"])

Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=26)
]
ChunkIdentifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=68)
]
ChunkContent = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ChunkUpdateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: Identifier
    chunk_id: ChunkIdentifier
    content: ChunkContent


class ChunkBulkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: Identifier
    chunk_ids: list[Identifier] = Field(min_length=1)
    action: Literal["enable", "disable"]

    @field_validator("chunk_ids")
    @classmethod
    def chunk_ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("chunk_ids must be unique")
        return value


def _upsert_chunk_override(
    session: Session,
    chunk: ChunkRecord,
    user: User,
    *,
    generation_id: str,
    manual_status: Optional[str] = None,
    content: Optional[str] = None,
    update_content: bool = False,
) -> ChunkOverride:
    override = session.scalar(
        select(ChunkOverride).where(
            ChunkOverride.document_id == chunk.document_id,
            ChunkOverride.logical_chunk_key == chunk.logical_chunk_key,
        )
    )
    if override is None:
        current_status = (
            "disabled"
            if "disabled" in {chunk.chunk_status, chunk.status}
            else "enabled"
        )
        override = ChunkOverride(
            team_id=chunk.team_id,
            document_id=chunk.document_id,
            source_path=chunk.source_path,
            logical_chunk_key=chunk.logical_chunk_key,
            content=content if update_content else None,
            manual_status=manual_status or current_status,
            source_chunk_id=chunk.id,
            created_by=user.id,
            updated_by=user.id,
        )
        session.add(override)
    elif update_content:
        override.content = content

    if manual_status is not None:
        override.manual_status = manual_status
    override.source_path = chunk.source_path
    override.status = "active"
    override.pending_reason = None
    override.applied_chunk_id = chunk.id
    override.index_generation = generation_id or chunk.index_generation or None
    override.updated_by = user.id
    return override


def _chunk_view(chunk: ChunkRecord) -> dict:
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "document_version_id": chunk.source_locator and json.loads(
            chunk.source_locator
        ).get("document_version_id"),
        "content": chunk.content,
        "heading_path": json.loads(chunk.heading_path) if chunk.heading_path else [],
        "source_locator": json.loads(chunk.source_locator) if chunk.source_locator else {},
        "status": chunk.status,
        "index_generation": chunk.index_generation,
        "quality_flags": [],
        "version": chunk.version,
        "created_at": chunk.created_at.isoformat(),
        "updated_at": chunk.updated_at.isoformat(),
    }


def _chunks_or_error(
    session: Session,
    team_id: str,
    chunk_ids,
    user: User,
    *,
    manage: bool = False,
):
    ids = set(chunk_ids)
    rows = session.scalars(
        select(ChunkRecord)
        .join(Document, ChunkRecord.document_id == Document.id)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(ChunkRecord.id.in_(tuple(ids)), KnowledgeBase.team_id == team_id)
    ).all()
    if len(rows) != len(ids):
        raise ApiError(404, "NOT_FOUND", "Chunk was not found.")
    for chunk in rows:
        _document_or_error(
            session,
            team_id,
            chunk.document_id,
            user,
            manage=manage,
        )
    return rows


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
    _document_or_error(session, team_id, document_id, user)
    return paginate_scalars(
        session,
        select(ChunkRecord).where(ChunkRecord.document_id == document_id),
        timestamp_column=ChunkRecord.created_at,
        id_column=ChunkRecord.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=_chunk_view,
    )


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
    _document_or_error(session, team_id, chunk.document_id, user)
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
    chunks = _chunks_or_error(session, team_id, chunk_ids, user, manage=True)
    generation_id = _active_generation_id(session, team_id)
    if request.app.state.settings.enable_indexing and generation_id:
        try:
            for chunk in chunks:
                asyncio.run(
                    set_chunk_status_in_indexes(
                        request.app.state.settings,
                        generation_id,
                        chunk.id,
                        "disabled",
                        previous_status=(
                            "enabled"
                            if "enabled" in {chunk.chunk_status, chunk.status}
                            else "disabled"
                        ),
                    )
                )
        except (Exception, IndexMaintenanceError) as error:
            raise ApiError(
                503,
                "INDEX_MAINTENANCE_UNAVAILABLE",
                "Chunk status could not be synchronized to every index.",
            ) from error
    for chunk in chunks:
        _upsert_chunk_override(
            session,
            chunk,
            user,
            generation_id=generation_id,
            manual_status="disabled",
        )
    session.execute(
        update(ChunkRecord)
        .where(ChunkRecord.id.in_(tuple(chunk_ids)))
        .values(
            status="disabled",
            chunk_status="disabled",
            version=ChunkRecord.version + 1,
        )
    )
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="chunk.disable",
        resource_type="chunk",
        details={"chunk_count": len(chunk_ids), "chunk_ids": chunk_ids},
    )
    _refresh_generation_count(session, generation_id)
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
    chunks = _chunks_or_error(session, team_id, chunk_ids, user, manage=True)
    generation_id = _active_generation_id(session, team_id)
    if request.app.state.settings.enable_indexing and generation_id:
        try:
            for chunk in chunks:
                asyncio.run(
                    set_chunk_status_in_indexes(
                        request.app.state.settings,
                        generation_id,
                        chunk.id,
                        "enabled",
                        previous_status=(
                            "enabled"
                            if "enabled" in {chunk.chunk_status, chunk.status}
                            else "disabled"
                        ),
                    )
                )
        except (Exception, IndexMaintenanceError) as error:
            raise ApiError(
                503,
                "INDEX_MAINTENANCE_UNAVAILABLE",
                "Chunk status could not be synchronized to every index.",
            ) from error
    for chunk in chunks:
        _upsert_chunk_override(
            session,
            chunk,
            user,
            generation_id=generation_id,
            manual_status="enabled",
        )
    session.execute(
        update(ChunkRecord)
        .where(ChunkRecord.id.in_(tuple(chunk_ids)))
        .values(
            status="enabled",
            chunk_status="enabled",
            version=ChunkRecord.version + 1,
        )
    )
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="chunk.enable",
        resource_type="chunk",
        details={"chunk_count": len(chunk_ids), "chunk_ids": chunk_ids},
    )
    _refresh_generation_count(session, generation_id)
    session.commit()
    return envelope({"enabled": len(chunk_ids)}, request.state.request_id)


@router.post("/chunks/update")
def update_chunk(
    body: ChunkUpdateBody,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.team_id
    chunk_id = body.chunk_id
    content = body.content
    chunk = session.get(ChunkRecord, chunk_id)
    if chunk is None:
        raise ApiError(404, "NOT_FOUND", "Chunk was not found.")
    _manage_document_or_error(session, team_id, chunk.document_id, user)
    raw_version = request.headers.get("If-Match")
    if raw_version is None:
        raise ApiError(400, "INVALID_ARGUMENT", "If-Match header is required.")
    try:
        expected_version = int(raw_version.strip().strip('"'))
    except (TypeError, ValueError) as error:
        raise ApiError(
            400,
            "INVALID_ARGUMENT",
            "If-Match must be an integer resource version.",
        ) from error
    if expected_version < 1:
        raise ApiError(
            400,
            "INVALID_ARGUMENT",
            "If-Match must be an integer resource version.",
        )
    if expected_version != chunk.version:
        raise ApiError(409, "VERSION_CONFLICT", "Resource version has changed.")
    generation_id = chunk.index_generation or _active_generation_id(session, team_id)
    current_manual_status = (
        "disabled"
        if "disabled" in {chunk.chunk_status, chunk.status}
        else "enabled"
    )
    _upsert_chunk_override(
        session,
        chunk,
        user,
        generation_id=generation_id,
        manual_status=current_manual_status,
        content=content,
        update_content=True,
    )
    session.add(
        ChunkHistory(
            chunk_id=chunk.id,
            action="update",
            old_content=chunk.content,
            new_content=content,
            actor_id=user.id,
        )
    )
    if (
        request.app.state.settings.enable_indexing
        and generation_id
        and current_manual_status == "enabled"
    ):
        vector = EmbeddingClient(
            request.app.state.settings.embedding_url
        ).embed([content])[0]
        try:
            previous_vector = EmbeddingClient(
                request.app.state.settings.embedding_url
            ).embed([chunk.content])[0]
            asyncio.run(
                update_chunk_in_indexes(
                    request.app.state.settings,
                    generation_id,
                    chunk.id,
                    content,
                    vector,
                    previous_content=chunk.content,
                    previous_vector=previous_vector,
                )
            )
        except (Exception, IndexMaintenanceError) as error:
            raise ApiError(
                503,
                "INDEX_MAINTENANCE_UNAVAILABLE",
                "The edited chunk could not be synchronized to every index.",
            ) from error
    chunk.content = content
    chunk.content_hash = content_fingerprint(content)
    chunk.version += 1
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="chunk.update",
        resource_type="chunk",
        resource_id=chunk.id,
        details={
            "document_id": chunk.document_id,
            "previous_version": expected_version,
            "version": chunk.version,
            "content_changed": True,
        },
    )
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
        action="chunk.regenerate",
        resource_type="document",
        resource_id=document.id,
        details={"run_id": run.id},
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
        {"document_id": document.id, "run_id": run.id, "status": run.status},
        request.state.request_id,
    )


@router.get("/chunks/history")
def chunk_history(
    request: Request,
    team_id: str,
    chunk_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    chunk = session.get(ChunkRecord, chunk_id)
    if chunk is None:
        raise ApiError(404, "NOT_FOUND", "Chunk was not found.")
    _document_or_error(session, team_id, chunk.document_id, user)
    return paginate_scalars(
        session,
        select(ChunkHistory).where(ChunkHistory.chunk_id == chunk_id),
        timestamp_column=ChunkHistory.created_at,
        id_column=ChunkHistory.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda row: {
            "id": row.id,
            "action": row.action,
            "old_content": row.old_content,
            "new_content": row.new_content,
            "actor_id": row.actor_id,
            "created_at": row.created_at.isoformat(),
        },
    )


@router.post("/chunks/bulk")
def bulk_chunks(
    body: ChunkBulkBody,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    payload = body.model_dump()
    if body.action == "enable":
        return enable_chunks(payload, request, user, session)
    return disable_chunks(payload, request, user, session)
