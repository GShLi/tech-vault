"""Document processing: parse, chunk, embed and index."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from urllib.parse import urlencode

from backend.app.core.config import Settings
from backend.app.rag.domain.models import (
    Chunk,
    ChunkStatus,
    DataClassification,
    DocumentStatus,
    Visibility,
)
from backend.app.rag.chunking.identity import content_fingerprint
from backend.app.rag.embedding.service import EmbeddingClient
from backend.app.rag.parsing.documents import UnsupportedDocumentType, parse_document_text
from backend.app.rag.retrieval.config import EngineMode
from backend.app.rag.retrieval.factory import build_index_writers
from backend.app.db.models import (
    ChunkRecord,
    ChunkOverride,
    Document,
    DocumentVersion,
    IngestionRun,
    IndexGenerationRecord,
    KnowledgeBase,
)
from sqlalchemy import func, select, update


def _override_key(chunk: Chunk) -> str:
    return chunk.logical_chunk_key or "{0}#chunk-{1}".format(
        chunk.source_path,
        chunk.chunk_id,
    )


def apply_chunk_overrides(
    session,
    document: Document,
    chunks: List[Chunk],
    generation_id: str = "",
) -> List[Chunk]:
    """Overlay manual edits and status decisions without replacing auto text."""

    overrides = session.scalars(
        select(ChunkOverride).where(ChunkOverride.document_id == document.id)
    ).all()
    by_key = {override.logical_chunk_key: override for override in overrides}
    matched_keys = set()
    effective_chunks = []

    for chunk in chunks:
        key = _override_key(chunk)
        override = by_key.get(key)
        if override is None:
            effective_chunks.append(chunk)
            continue

        matched_keys.add(key)
        effective_content = (
            override.content
            if override.content is not None and override.content.strip()
            else chunk.content
        )
        chunk_status = (
            ChunkStatus.DISABLED
            if override.manual_status == "disabled"
            else ChunkStatus.ENABLED
        )
        effective_chunks.append(
            replace(
                chunk,
                content=effective_content,
                content_hash=content_fingerprint(effective_content),
                chunk_status=chunk_status,
                index_generation=generation_id or chunk.index_generation,
            )
        )
        override.status = "active"
        override.pending_reason = None
        override.applied_chunk_id = chunk.chunk_id
        override.index_generation = generation_id or override.index_generation

    for override in overrides:
        if override.logical_chunk_key in matched_keys:
            continue
        override.status = "pending"
        override.pending_reason = "logical_chunk_key was not found in the rebuilt document"
        override.applied_chunk_id = None

    return effective_chunks


def _fail(run: IngestionRun, document: Document, code: str, retryable: bool, session) -> None:
    if run.status == "cancelled":
        return
    run.status = "failed"
    run.error_code = code
    run.retryable = retryable
    document.doc_status = "failed"
    session.commit()


def _cancelled(session, run: IngestionRun) -> bool:
    session.refresh(run, attribute_names=["status", "current_stage", "retryable"])
    return run.status == "cancelled"


def _document_index_chunks(
    session,
    document: Document,
    knowledge_base: KnowledgeBase,
    generation_id: str,
):
    rows = session.scalars(
        select(ChunkRecord)
        .where(
            ChunkRecord.document_id == document.id,
            ChunkRecord.doc_status == "active",
        )
        .order_by(ChunkRecord.created_at.asc(), ChunkRecord.id.asc())
    ).all()
    return [
        Chunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document_version_id=document.current_version_id or document.id,
            team_id=row.team_id,
            knowledge_base_id=row.knowledge_base_id,
            owner_user_id=row.owner_user_id,
            visibility=Visibility(row.visibility),
            data_classification=DataClassification(row.data_classification),
            source_path=row.source_path,
            heading_path=tuple(json.loads(row.heading_path or "[]")),
            content=row.content,
            logical_chunk_key=row.logical_chunk_key,
            content_hash=row.content_hash,
            source_locator=json.loads(row.source_locator or "{}"),
            product=document.product,
            version_values=tuple(json.loads(row.version_values or "[]")),
            doc_status=DocumentStatus.ACTIVE,
            chunk_status=ChunkStatus(row.chunk_status),
            index_generation=generation_id,
        )
        for row in rows
    ]


async def _rollback_document_index(
    writers,
    settings: Settings,
    generation_id: str,
    document_id: str,
    previous_chunks: List[Chunk],
    new_only_ids,
) -> None:
    if not writers:
        return
    previous_vectors = EmbeddingClient(settings.embedding_url).embed(
        [chunk.content for chunk in previous_chunks]
    ) if previous_chunks else []
    previous_chunks = [
        replace(chunk, content_vector=vector)
        for chunk, vector in zip(previous_chunks, previous_vectors)
    ]
    for writer in writers:
        try:
            if previous_chunks:
                await writer.stage(generation_id, previous_chunks)
            await writer.delete_chunks(generation_id, new_only_ids)
            await writer.set_document_status(generation_id, document_id, "active")
        except Exception:  # noqa: BLE001
            continue


def process_document(
    document: Document,
    run: IngestionRun,
    session,
    settings: Settings,
) -> List[str]:
    if _cancelled(session, run):
        return []

    path = Path(document.source_uri or "")
    if not path.exists() and document.object_uri:
        from backend.app.api.storage import (
            ObjectStorageUnavailable,
            download_s3_object,
        )

        destination = Path(settings.upload_dir) / "cache" / (
            document.id + "-" + document.file_name
        )
        try:
            path = download_s3_object(document.object_uri, destination, settings)
        except ObjectStorageUnavailable:
            _fail(run, document, "SOURCE_STORAGE_UNAVAILABLE", True, session)
            return []
        document.source_uri = str(path)
        session.commit()
    if not path.exists():
        _fail(run, document, "SOURCE_MISSING", False, session)
        return []

    knowledge_base = session.get(KnowledgeBase, document.knowledge_base_id)
    if knowledge_base is None:
        _fail(run, document, "KNOWLEDGE_BASE_MISSING", False, session)
        return []

    run.current_stage = "parsing"
    run.stage_progress_pct = 20
    session.commit()

    try:
        content = parse_document_text(path)
    except UnsupportedDocumentType:
        _fail(run, document, "UNSUPPORTED_FILE_TYPE", False, session)
        return []
    except Exception:
        _fail(run, document, "DOCUMENT_PARSE_FAILED", False, session)
        return []

    if not content.strip():
        _fail(run, document, "EMPTY_DOCUMENT", False, session)
        return []

    if _cancelled(session, run):
        return []

    from backend.app.rag.chunking.markdown import chunk_markdown

    automatic_chunks = chunk_markdown(
        document_version_id=document.current_version_id or document.id,
        source_path=document.file_name,
        content=content,
        document_id=document.id,
        team_id=knowledge_base.team_id,
        knowledge_base_id=document.knowledge_base_id,
        owner_user_id=document.owner_user_id,
        visibility=Visibility(document.visibility),
        data_classification=DataClassification(document.data_classification),
        product=document.product,
        version_values=tuple(json.loads(document.version_values or "[]")),
        document_file_name=document.file_name,
        source_url="/api/v1/docs/download?{0}".format(
            urlencode(
                {
                    "team_id": knowledge_base.team_id,
                    "document_id": document.id,
                }
            )
        ),
    )

    run.current_stage = "chunking"
    run.stage_progress_pct = 50
    session.commit()

    if _cancelled(session, run):
        return []

    generation = ""
    generation_record = None
    if settings.enable_indexing:
        generation_record = session.scalar(
            select(IndexGenerationRecord)
            .where(
                IndexGenerationRecord.team_id == knowledge_base.team_id,
                IndexGenerationRecord.status == "active",
            )
            .order_by(IndexGenerationRecord.activated_at.desc())
        )
        if generation_record is None:
            generation_record = IndexGenerationRecord(
                team_id=knowledge_base.team_id,
                status="staging",
                chunk_count=0,
            )
            session.add(generation_record)
            session.flush()
        generation = generation_record.id

    chunks = apply_chunk_overrides(
        session,
        document,
        automatic_chunks,
        generation_id=generation,
    )
    automatic_content = {
        chunk.chunk_id: chunk.content for chunk in automatic_chunks
    }
    indexable_chunks = [
        chunk for chunk in chunks if chunk.chunk_status == ChunkStatus.ENABLED
    ]

    embedder = EmbeddingClient(settings.embedding_url)
    vectors = embedder.embed([chunk.content for chunk in indexable_chunks])
    vectors_by_id = {
        chunk.chunk_id: vector
        for chunk, vector in zip(indexable_chunks, vectors)
    }
    chunks = [
        replace(chunk, content_vector=vectors_by_id.get(chunk.chunk_id, []))
        for chunk in chunks
    ]
    indexable_chunks = [
        chunk for chunk in chunks if chunk.chunk_status == ChunkStatus.ENABLED
    ]

    if _cancelled(session, run):
        return []

    run.current_stage = "indexing"
    run.stage_progress_pct = 75
    session.commit()

    if settings.enable_indexing:
        staged_chunks = [
            replace(chunk, doc_status=DocumentStatus.BUILDING)
            for chunk in indexable_chunks
        ]
        previous_chunks = _document_index_chunks(
            session,
            document,
            knowledge_base,
            generation,
        )
        previous_ids = {chunk.chunk_id for chunk in previous_chunks}
        new_ids = {chunk.chunk_id for chunk in staged_chunks}
        stale_ids = previous_ids - new_ids
        new_only_ids = new_ids - previous_ids

        async def index_chunks() -> List[object]:
            writers = build_index_writers(settings, EngineMode(settings.engine_mode))
            try:
                for writer in writers:
                    await writer.stage(generation, staged_chunks)
                for writer in writers:
                    await writer.delete_chunks(generation, stale_ids)
                    await writer.set_document_status(
                        generation,
                        document.id,
                        "active",
                    )
                for writer in writers:
                    validation = await writer.validate(generation)
                    if not validation.passed:
                        raise RuntimeError(
                            "index validation failed: "
                            + ", ".join(validation.errors)
                        )
                for writer in writers:
                    await writer.activate(generation)
            except Exception:
                await _rollback_document_index(
                    writers,
                    settings,
                    generation,
                    document.id,
                    previous_chunks,
                    new_only_ids,
                )
                raise
            return writers

        try:
            asyncio.run(index_chunks())
        except Exception as error:
            if generation_record.status != "active":
                generation_record.status = "failed"
                generation_record.error_message = str(error)
                generation_record.validation_errors = json.dumps([str(error)])
            _fail(run, document, "INDEXING_FAILED", True, session)
            return []
        generation_record.status = "active"
        generation_record.error_message = None
        generation_record.validation_errors = "[]"
        generation_record.validated_at = datetime.now(timezone.utc)
        generation_record.activated_at = generation_record.activated_at or datetime.now(
            timezone.utc
        )

    new_chunk_ids = tuple(chunk.chunk_id for chunk in chunks)
    session.execute(
        update(ChunkRecord)
        .where(
            ChunkRecord.document_id == document.id,
            ChunkRecord.id.not_in(new_chunk_ids),
        )
        .values(
            doc_status="superseded",
            status="disabled",
            chunk_status="disabled",
            version=ChunkRecord.version + 1,
        )
    )

    for chunk in chunks:
        record = session.get(ChunkRecord, chunk.chunk_id)
        if record is None:
            record = ChunkRecord(id=chunk.chunk_id)
            session.add(record)
        record.document_id = document.id
        record.team_id = chunk.team_id
        record.knowledge_base_id = chunk.knowledge_base_id
        record.owner_user_id = chunk.owner_user_id
        record.visibility = chunk.visibility.value
        record.data_classification = chunk.data_classification.value
        record.doc_status = "active"
        record.chunk_status = chunk.chunk_status.value
        record.content = chunk.content
        record.auto_content = automatic_content[chunk.chunk_id]
        record.heading_path = json.dumps(list(chunk.heading_path))
        record.source_locator = json.dumps(
            {
                **dict(chunk.source_locator),
                "document_version_id": chunk.document_version_id,
            }
        )
        record.version_values = json.dumps(list(chunk.version_values))
        record.logical_chunk_key = chunk.logical_chunk_key
        record.content_hash = chunk.content_hash
        record.source_path = chunk.source_path
        record.index_generation = generation
        record.status = chunk.chunk_status.value

    session.flush()
    if generation_record is not None:
        generation_record.chunk_count = int(
            session.scalar(
                select(func.count())
                .select_from(ChunkRecord)
                .where(
                    ChunkRecord.index_generation == generation_record.id,
                    ChunkRecord.status == "enabled",
                )
            )
            or 0
        )

    version = session.get(DocumentVersion, run.document_version_id)
    if version is not None:
        version.status = "active"
        version.chunk_count = len(chunks)
        version.index_generation = generation or None

    run.current_stage = "completed"
    run.stage_progress_pct = 100
    run.status = "completed"
    run.retryable = False
    document.doc_status = "active"
    session.commit()

    return [chunk.chunk_id for chunk in chunks]


def process_markdown(document: Document, run: IngestionRun, session, settings=None) -> List[str]:
    """Compatibility wrapper used by the upload endpoint and worker."""
    if settings is None:
        settings = Settings.from_env()
    return process_document(document, run, session, settings)
