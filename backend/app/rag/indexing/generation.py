from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.db.models import (
    ChunkRecord,
    Document,
    IndexGenerationRecord,
    GenerationChunk,
)
from backend.app.rag.domain.models import (
    Chunk,
    ChunkStatus,
    DataClassification,
    DocumentStatus,
    ValidationResult,
    Visibility,
)
from backend.app.rag.embedding.service import EmbeddingClient
from backend.app.rag.ingestion.processor import apply_chunk_overrides, record_to_chunk
from backend.app.rag.chunking.semantic import embedding_input
from backend.app.rag.embedding.service import validate_vectors
from backend.app.rag.retrieval.config import EngineMode
from backend.app.rag.retrieval.factory import build_index_writers


class InMemoryIndexWriter:
    """Generation-aware index writer used by tests and the first vertical slice."""

    def __init__(self) -> None:
        self._staged: Dict[str, List[Chunk]] = {}
        self._validated: Set[str] = set()
        self._active_generation: str = ""

    async def stage(self, generation_id: str, chunks: Iterable[Chunk]) -> None:
        if generation_id == self._active_generation:
            raise ValueError("cannot stage into the active generation")
        self._staged[generation_id] = list(chunks)
        self._validated.discard(generation_id)

    async def delete_chunks(self, generation_id: str, chunk_ids: Iterable[str]) -> None:
        ids = set(chunk_ids)
        if not ids or generation_id not in self._staged:
            return
        self._staged[generation_id] = [
            chunk for chunk in self._staged[generation_id] if chunk.chunk_id not in ids
        ]
        self._validated.discard(generation_id)

    async def set_document_status(
        self,
        generation_id: str,
        document_id: str,
        status: str,
    ) -> None:
        if generation_id not in self._staged:
            return
        self._staged[generation_id] = [
            replace(chunk, doc_status=DocumentStatus(status))
            if chunk.document_id == document_id
            else chunk
            for chunk in self._staged[generation_id]
        ]
        self._validated.discard(generation_id)

    async def validate(self, generation_id: str) -> ValidationResult:
        chunks = self._staged.get(generation_id)
        if chunks is None:
            return ValidationResult(False, ("generation not staged",), 0)

        errors = []
        seen = set()
        for chunk in chunks:
            if not chunk.chunk_id:
                errors.append("chunk_id is empty")
            if chunk.chunk_id in seen:
                errors.append("duplicate chunk_id: " + chunk.chunk_id)
            seen.add(chunk.chunk_id)
            if not chunk.content.strip():
                errors.append("empty content: " + chunk.chunk_id)
            if not chunk.team_id or not chunk.knowledge_base_id:
                errors.append("missing authorization scope: " + chunk.chunk_id)
            if chunk.index_generation and chunk.index_generation != generation_id:
                errors.append("generation mismatch: " + chunk.chunk_id)

        result = ValidationResult(not errors, tuple(errors), len(chunks))
        if result.passed:
            self._validated.add(generation_id)
        return result

    async def activate(self, generation_id: str) -> None:
        if generation_id not in self._validated:
            raise ValueError("cannot activate an unvalidated generation")
        self._active_generation = generation_id

    async def cleanup(self, generation_id: str) -> None:
        if generation_id == self._active_generation:
            raise ValueError("cannot cleanup the active generation")
        self._staged.pop(generation_id, None)
        self._validated.discard(generation_id)

    def active_chunks(self) -> List[Chunk]:
        return list(self._staged.get(self._active_generation, ()))

    @property
    def active_generation(self) -> str:
        return self._active_generation


def _decode_json(value: str, default):
    try:
        decoded = json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default
    return decoded if isinstance(decoded, type(default)) else default


def _load_enabled_chunks(
    session: Session,
    team_id: str,
    generation_id: str,
    settings: Settings,
) -> List[Chunk]:
    rows = session.execute(
        select(ChunkRecord, Document)
        .join(Document, ChunkRecord.document_id == Document.id)
        .where(
            ChunkRecord.team_id == team_id,
            ChunkRecord.status == "enabled",
            ChunkRecord.chunk_status == "enabled",
            ChunkRecord.doc_status == "active",
            Document.doc_status == "active",
        )
        .order_by(ChunkRecord.created_at.asc(), ChunkRecord.id.asc())
    ).all()
    if not rows:
        return []

    chunks = [record_to_chunk(record, document, generation_id) for record, document in rows
              if record.chunk_level == "child"]
    grouped = {}
    documents = {document.id: document for _, document in rows}
    for chunk in chunks:
        grouped.setdefault(chunk.document_id, []).append(chunk)
    chunks = [chunk for document_id, group in grouped.items()
              for chunk in apply_chunk_overrides(session, documents[document_id], group, generation_id)
              if chunk.chunk_status == ChunkStatus.ENABLED]
    client = EmbeddingClient(settings.embedding_url, dimension=settings.embedding_dimension,
        allow_hash_fallback=False, model=settings.embedding_model, batch_size=settings.embedding_batch_size)
    inputs = [embedding_input(chunk.source_path, chunk.heading_path, chunk.content,
                             chunk.source_locator.get("table_header", "")) for chunk in chunks]
    counts = client.tokenize(inputs)
    if any(count > (160 if chunk.node_type == "code" else settings.chunk_child_max_tokens)
           for chunk, count in zip(chunks, counts)):
        raise ValueError("CHUNK_QUALITY_FAILED")
    vectors = client.embed(inputs)
    validate_vectors(vectors, len(chunks), settings.embedding_dimension)
    from dataclasses import replace
    return [replace(chunk, content_vector=vector, token_count=count) for chunk, vector, count in zip(chunks, vectors, counts)]


def _generation_chunks(
    session: Session,
    generation: IndexGenerationRecord,
) -> List[ChunkRecord]:
    members = session.scalars(select(GenerationChunk).where(GenerationChunk.generation_id == generation.id)).all()
    return [ChunkRecord(**json.loads(member.snapshot)) for member in members
            if json.loads(member.snapshot).get("chunk_level") == "child"
            and json.loads(member.snapshot).get("chunk_status") == "enabled"]


def save_generation_members(session, generation_id, rows):
    for row in rows:
        snapshot = {column.name: getattr(row, column.name) for column in ChunkRecord.__table__.columns
                    if column.name not in {"created_at", "updated_at"}}
        member = session.get(GenerationChunk, (generation_id, row.id))
        if member is None:
            member = GenerationChunk(generation_id=generation_id, chunk_id=row.id)
            session.add(member)
        member.snapshot = json.dumps(snapshot)


def _writer_name(writer) -> str:
    return writer.__class__.__name__


def _apply_validation_result(
    generation: IndexGenerationRecord,
    errors: List[str],
    checked_chunks: int,
) -> dict:
    now = datetime.now(timezone.utc)
    passed = not errors
    generation.validated_at = now
    generation.validation_errors = json.dumps(errors, separators=(",", ":"))
    generation.error_message = None if passed else "; ".join(errors)
    generation.status = "validated" if passed else "failed"
    if passed:
        generation.chunk_count = checked_chunks
    return {
        "generation_id": generation.id,
        "passed": passed,
        "status": generation.status,
        "errors": errors,
        "checked_chunks": checked_chunks,
        "validated_at": now.isoformat(),
    }


async def _validate_existing_generation(
    session: Session,
    generation: IndexGenerationRecord,
    settings: Settings,
) -> Tuple[dict, List[object]]:
    records = _generation_chunks(session, generation)
    errors: List[str] = []
    if not records:
        errors.append("generation contains no enabled chunks")
    if len(records) != generation.chunk_count:
        errors.append(
            "chunk_count mismatch: expected {0}, found {1}".format(
                generation.chunk_count, len(records)
            )
        )
    for record in records:
        if not record.content.strip():
            errors.append("empty content: " + record.id)
        if not record.knowledge_base_id or not record.owner_user_id:
            errors.append("missing authorization scope: " + record.id)

    writers: List[object] = []
    if settings.enable_indexing:
        writers = build_index_writers(settings, EngineMode(settings.engine_mode))
        if not writers:
            errors.append("no index writers are configured")
        for writer in writers:
            name = _writer_name(writer)
            try:
                await writer.stage(generation.id, [])
                result = await writer.validate(generation.id)
            except Exception as error:  # noqa: BLE001
                errors.append("{0} validation failed: {1}".format(name, error))
                continue
            errors.extend("{0}: {1}".format(name, error) for error in result.errors)
            if result.checked_chunks != len(records):
                errors.append(
                    "{0} index count mismatch: expected {1}, found {2}".format(
                        name,
                        len(records),
                        result.checked_chunks,
                    )
                )

    return _apply_validation_result(generation, errors, len(records)), writers


async def validate_existing_generation(
    session: Session,
    generation: IndexGenerationRecord,
    settings: Settings,
) -> dict:
    """Validate PostgreSQL rows and every configured persisted index."""

    try:
        result, _writers = await _validate_existing_generation(
            session,
            generation,
            settings,
        )
    except Exception as error:  # noqa: BLE001
        result = _apply_validation_result(
            generation,
            ["generation validation failed: " + str(error)],
            generation.chunk_count,
        )
    session.commit()
    return result


def _activate_database_generation(
    session: Session,
    generation: IndexGenerationRecord,
) -> None:
    active_rows = session.scalars(
        select(IndexGenerationRecord).where(
            IndexGenerationRecord.team_id == generation.team_id,
            IndexGenerationRecord.id != generation.id,
            IndexGenerationRecord.status == "active",
        )
    ).all()
    for active in active_rows:
        active.status = "validated"
    generation.status = "active"
    generation.activated_at = datetime.now(timezone.utc)


async def _activate_existing_generation(
    session: Session,
    generation: IndexGenerationRecord,
    settings: Settings,
) -> dict:
    """Revalidate persisted indexes before switching the active generation."""

    result, writers = await _validate_existing_generation(
        session,
        generation,
        settings,
    )
    if not result["passed"]:
        session.commit()
        return result

    try:
        for writer in writers:
            await writer.activate(generation.id)
    except Exception as error:  # noqa: BLE001
        result = _apply_validation_result(
            generation,
            ["generation activation failed: " + str(error)],
            result["checked_chunks"],
        )
        session.commit()
        return result

    _activate_database_generation(session, generation)
    session.commit()
    result["status"] = generation.status
    return result


async def _rebuild_generation(
    session: Session,
    generation: IndexGenerationRecord,
    settings: Settings,
) -> dict:
    """Build a staging generation from enabled PostgreSQL chunks."""

    if generation.status == "active":
        return {
            "generation_id": generation.id,
            "passed": False,
            "status": generation.status,
            "errors": ["an active generation cannot be rebuilt in place"],
            "checked_chunks": generation.chunk_count,
            "validated_at": generation.validated_at.isoformat()
            if generation.validated_at is not None
            else None,
        }

    try:
        chunks = _load_enabled_chunks(
            session,
            generation.team_id,
            generation.id,
            settings,
        )
    except Exception as error:  # noqa: BLE001
        result = _apply_validation_result(
            generation,
            ["generation rebuild failed: " + str(error)],
            0,
        )
        session.commit()
        return result

    errors: List[str] = []
    if not chunks:
        errors.append("generation contains no enabled chunks")
    if not settings.enable_indexing:
        errors.append("indexing is disabled")
    if errors:
        result = _apply_validation_result(generation, errors, len(chunks))
        session.commit()
        return result

    generation.status = "staging"
    generation.chunk_count = len(chunks)
    generation.validation_errors = "[]"
    generation.error_message = None
    session.commit()

    writers = build_index_writers(settings, EngineMode(settings.engine_mode))
    if not writers:
        errors.append("no index writers are configured")
    for writer in writers:
        name = _writer_name(writer)
        try:
            await writer.stage(generation.id, chunks)
            result = await writer.validate(generation.id)
        except Exception as error:  # noqa: BLE001
            errors.append("{0} staging failed: {1}".format(name, error))
            continue
        errors.extend("{0}: {1}".format(name, error) for error in result.errors)
        if result.checked_chunks != len(chunks):
            errors.append(
                "{0} index count mismatch: expected {1}, found {2}".format(
                    name,
                    len(chunks),
                    result.checked_chunks,
                )
            )

    validation = _apply_validation_result(generation, errors, len(chunks))
    if not validation["passed"]:
        session.commit()
        return validation

    try:
        for writer in writers:
            await writer.activate(generation.id)
    except Exception as error:  # noqa: BLE001
        validation = _apply_validation_result(
            generation,
            ["generation activation failed: " + str(error)],
            len(chunks),
        )
        session.commit()
        return validation

    rows = session.scalars(select(ChunkRecord).where(ChunkRecord.team_id == generation.team_id,
        ChunkRecord.doc_status == "active")).all()
    save_generation_members(session, generation.id, rows)
    _activate_database_generation(session, generation)
    session.commit()
    validation["status"] = generation.status
    return validation



async def rebuild_generation(session, generation, settings):
    from backend.app.rag.ingestion.leases import team_lease
    with team_lease(session, generation.team_id):
        return await _rebuild_generation(session, generation, settings)


async def activate_existing_generation(session, generation, settings):
    from backend.app.rag.ingestion.leases import team_lease
    with team_lease(session, generation.team_id):
        return await _activate_existing_generation(session, generation, settings)
