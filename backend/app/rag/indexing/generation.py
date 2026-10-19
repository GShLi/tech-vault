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
from backend.app.rag.ingestion.processor import apply_chunk_overrides
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

    chunks_by_document: Dict[str, List[Chunk]] = {}
    documents: Dict[str, Document] = {}
    for record, document in rows:
        source_locator = _decode_json(record.source_locator, {})
        chunk = Chunk(
            chunk_id=record.id,
            document_id=record.document_id,
            document_version_id=str(
                source_locator.get("document_version_id")
                or document.current_version_id
                or ""
            ),
            team_id=record.team_id,
            knowledge_base_id=record.knowledge_base_id,
            owner_user_id=record.owner_user_id,
            visibility=Visibility(record.visibility),
            data_classification=DataClassification(record.data_classification),
            source_path=record.source_path,
            heading_path=tuple(_decode_json(record.heading_path, [])),
            content=record.auto_content or record.content,
            logical_chunk_key=record.logical_chunk_key,
            content_hash=record.content_hash,
            source_locator=source_locator,
            product=document.product,
            version_values=tuple(_decode_json(record.version_values, [])),
            doc_status=DocumentStatus(record.doc_status),
            chunk_status=ChunkStatus(record.chunk_status),
            index_generation=generation_id,
        )
        chunks_by_document.setdefault(record.document_id, []).append(chunk)
        documents[record.document_id] = document

    effective_chunks: List[Chunk] = []
    for document_id, document_chunks in chunks_by_document.items():
        effective_chunks.extend(
            apply_chunk_overrides(
                session,
                documents[document_id],
                document_chunks,
                generation_id=generation_id,
            )
        )
    effective_chunks = [
        chunk
        for chunk in effective_chunks
        if chunk.chunk_status == ChunkStatus.ENABLED
    ]

    vectors = EmbeddingClient(settings.embedding_url).embed(
        [chunk.content for chunk in effective_chunks]
    )
    if len(vectors) != len(effective_chunks):
        raise ValueError("embedding count does not match enabled chunk count")

    return [
        Chunk(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            document_version_id=chunk.document_version_id,
            team_id=chunk.team_id,
            knowledge_base_id=chunk.knowledge_base_id,
            owner_user_id=chunk.owner_user_id,
            visibility=chunk.visibility,
            data_classification=chunk.data_classification,
            source_path=chunk.source_path,
            heading_path=chunk.heading_path,
            content=chunk.content,
            logical_chunk_key=chunk.logical_chunk_key,
            content_hash=chunk.content_hash,
            source_locator=chunk.source_locator,
            content_vector=list(vector),
            product=chunk.product,
            version_values=chunk.version_values,
            doc_status=chunk.doc_status,
            chunk_status=chunk.chunk_status,
            index_generation=chunk.index_generation,
        )
        for chunk, vector in zip(effective_chunks, vectors)
    ]


def _generation_chunks(
    session: Session,
    generation: IndexGenerationRecord,
) -> List[ChunkRecord]:
    return list(
        session.scalars(
            select(ChunkRecord).where(
                ChunkRecord.team_id == generation.team_id,
                ChunkRecord.index_generation == generation.id,
                ChunkRecord.status == "enabled",
                ChunkRecord.chunk_status == "enabled",
                ChunkRecord.doc_status == "active",
            )
        ).all()
    )


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


async def activate_existing_generation(
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


async def rebuild_generation(
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

    for chunk_id in (chunk.chunk_id for chunk in chunks):
        record = session.get(ChunkRecord, chunk_id)
        if record is not None:
            record.index_generation = generation.id
    _activate_database_generation(session, generation)
    session.commit()
    validation["status"] = generation.status
    return validation

