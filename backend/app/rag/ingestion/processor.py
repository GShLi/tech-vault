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


def _chunk_fields():
    return ("parent_chunk_id", "chunk_level", "child_order", "node_type", "token_count", "page_no",
            "parse_version", "chunking_version", "embedding_model", "tokenizer_model",
            "parent_start_offset", "parent_end_offset", "overlap_before_tokens", "unsafe_split")


def record_to_chunk(record, document, generation_id=""):
    locator = json.loads(record.source_locator or "{}")
    return Chunk(
        chunk_id=record.id, document_id=record.document_id,
        document_version_id=locator.get("document_version_id") or document.current_version_id or document.id,
        team_id=record.team_id, knowledge_base_id=record.knowledge_base_id,
        owner_user_id=record.owner_user_id, visibility=Visibility(record.visibility),
        data_classification=DataClassification(record.data_classification), source_path=record.source_path,
        heading_path=tuple(json.loads(record.heading_path or "[]")), content=record.content,
        logical_chunk_key=record.logical_chunk_key, content_hash=record.content_hash,
        source_locator=locator, product=document.product,
        version_values=tuple(json.loads(record.version_values or "[]")),
        index_generation=generation_id or record.index_generation,
        doc_status=DocumentStatus.ACTIVE, chunk_status=ChunkStatus(record.chunk_status),
        **{name: getattr(record, name) for name in _chunk_fields()},
    )


def _prepare_document(document, run, session, settings):
    from dataclasses import asdict
    from backend.app.db.models import GenerationChunk
    from backend.app.rag.parsing.router import parse_document
    from backend.app.rag.parsing.contracts import ParseError
    from backend.app.rag.chunking.semantic import SemanticChunker, ChunkBudget, embedding_input
    from backend.app.rag.chunking.quality import chunk_quality_report
    from backend.app.rag.embedding.service import validate_vectors

    if _cancelled(session, run) or run.status == "completed":
        return []
    if run.document_version_id != document.current_version_id:
        raise ParseError("DOCUMENT_VERSION_CHANGED")
    version = session.get(DocumentVersion, run.document_version_id)
    path = Path(document.source_uri or "")
    if not path.is_file() and document.object_uri:
        from backend.app.api.storage import download_s3_object
        path = download_s3_object(document.object_uri, Path(settings.upload_dir) / "cache" / (document.id + "-" + document.file_name), settings)
    if not path.is_file():
        raise ParseError("SOURCE_MISSING")
    kb = session.get(KnowledgeBase, document.knowledge_base_id)
    run.current_stage = "parsing"
    run.stage_progress_pct = 20
    run.status = "running"
    session.commit()
    parsed = parse_document(path, file_name=document.file_name, mime_type=document.mime_type,
                            max_pages=settings.document_max_pages)
    version.parse_metadata = json.dumps({"parser_name": parsed.parser_name, "parser_version": parsed.parser_version,
        "pdf_kind": parsed.pdf_kind, "mime_type": document.mime_type, "warnings": list(parsed.warnings),
        "quality": asdict(parsed.quality), **parsed.metadata}, ensure_ascii=False)
    if parsed.quality.garbled_ratio > .05:
        raise ParseError("CHUNK_QUALITY_FAILED", "Extracted text has too many replacement characters.")
    client = EmbeddingClient(settings.embedding_url, dimension=settings.embedding_dimension,
        allow_hash_fallback=False, model=settings.embedding_model, batch_size=settings.embedding_batch_size)
    run.current_stage = "chunking"
    run.stage_progress_pct = 40
    session.commit()
    result = SemanticChunker(tokenize=client.tokenize, budget=ChunkBudget(
        child_target=settings.chunk_child_target_tokens, child_max=settings.chunk_child_max_tokens,
        child_overlap=settings.chunk_child_overlap_tokens, parent_target=settings.chunk_parent_target_tokens,
        parent_max=settings.chunk_parent_max_tokens,
    )).chunk(parsed.nodes, document_version_id=version.id, source_path=document.file_name,
             tokenizer_model=settings.embedding_model, chunking_version=settings.chunking_version)
    quality = chunk_quality_report(result)
    version.chunking_metadata = json.dumps({**quality, "chunking_version": settings.chunking_version,
        "tokenizer_model": settings.embedding_model, "embedding_model": settings.embedding_model})
    run.quality_metrics = json.dumps(quality)
    common = dict(document_id=document.id, document_version_id=version.id, team_id=kb.team_id,
        knowledge_base_id=kb.id, owner_user_id=document.owner_user_id, visibility=Visibility(document.visibility),
        data_classification=DataClassification(document.data_classification), source_path=document.file_name,
        product=document.product, version_values=tuple(json.loads(document.version_values or "[]")),
        parse_version=settings.parse_version, chunking_version=settings.chunking_version,
        tokenizer_model=settings.embedding_model, embedding_model=settings.embedding_model)
    def locator(draft):
        return {**draft.source_locator, "document_id": document.id, "document_version_id": version.id,
            "file_name": document.file_name, "source_path": document.file_name,
            "heading_path": list(draft.heading_path), "page_no": getattr(draft, "page_no", getattr(draft, "page_start", None)),
            "source_url": "/api/v1/docs/download?" + urlencode({"team_id": kb.team_id, "document_id": document.id})}
    parents = [Chunk(**common, chunk_id=p.parent_id, content=p.content, heading_path=p.heading_path,
        logical_chunk_key=p.logical_key, content_hash=content_fingerprint(p.content), source_locator=locator(p),
        chunk_level="parent", child_order=0, token_count=p.token_count, page_no=p.page_start) for p in result.parents]
    automatic = [Chunk(**common, chunk_id=c.child_id, content=c.content, heading_path=c.heading_path,
        logical_chunk_key=c.logical_key, content_hash=content_fingerprint(c.content), source_locator=locator(c),
        parent_chunk_id=c.parent_chunk_id, child_order=c.child_order, node_type=c.node_type,
        token_count=c.token_count, page_no=c.page_no, parent_start_offset=c.parent_start_offset,
        parent_end_offset=c.parent_end_offset, overlap_before_tokens=c.overlap_before_tokens,
        unsafe_split=c.unsafe_split) for c in result.children]
    children = apply_chunk_overrides(session, document, automatic)
    auto_content = {chunk.chunk_id: chunk.content for chunk in parents + automatic}
    chunks = parents + children
    # Validate overlays before publication, including overlapping edits and disabled evidence.
    from backend.app.rag.context.parents import effective_parent_text
    for parent in parents:
        effective = effective_parent_text(parent.content, [child for child in children if child.parent_chunk_id == parent.chunk_id],
                                         {child.chunk_id: auto_content[child.chunk_id] for child in children})
        if client.tokenize([effective])[0] > settings.chunk_parent_max_tokens:
            raise ParseError("CHUNK_QUALITY_FAILED", "Edited parent exceeds its token budget.")
    if _cancelled(session, run):
        return []
    from backend.app.rag.embedding.cache import embed_chunks
    from backend.app.db.models import PreparedIngestion
    run.current_stage, run.stage_progress_pct = "embedding", 60
    session.commit()
    vectorized = {chunk.chunk_id: chunk for chunk in embed_chunks(
        session, [child for child in children if child.chunk_status == ChunkStatus.ENABLED], settings,
    )}
    if _cancelled(session, run):
        return None
    chunks = [vectorized.get(chunk.chunk_id, chunk) for chunk in chunks]
    payload = {"chunks": [asdict(chunk) for chunk in chunks], "auto_content": auto_content}
    prepared = session.get(PreparedIngestion, run.id)
    if prepared is None:
        prepared = PreparedIngestion(run_id=run.id)
        session.add(prepared)
    prepared.payload = json.dumps(payload)
    run.status, run.current_stage, run.stage_progress_pct = "prepared", "waiting_publish", 70
    run.error_code, run.failure_details = None, "{}"
    session.commit()
    return payload


def _decode_chunk(value):
    return Chunk(**{**value, "visibility": Visibility(value["visibility"]),
        "data_classification": DataClassification(value["data_classification"]),
        "doc_status": DocumentStatus(value["doc_status"]), "chunk_status": ChunkStatus(value["chunk_status"]),
        "heading_path": tuple(value["heading_path"]), "version_values": tuple(value["version_values"])})


def publish_prepared(session, pairs, settings):
    """Publish several prepared documents in one team snapshot under its lease."""
    from backend.app.db.models import PreparedIngestion
    from backend.app.rag.embedding.cache import embed_chunks
    from backend.app.rag.parsing.contracts import ParseError
    from backend.app.rag.indexing.generation import save_generation_members

    prepared_rows = []
    all_chunks, auto_content = [], {}
    for document, run in pairs:
        session.refresh(run)
        session.refresh(document)
        if run.status in {"cancelled", "completed"}:
            continue
        if document.doc_status in {"deleted", "deleting"}:
            run.status = run.current_stage = "cancelled"
            session.commit()
            continue
        if run.document_version_id != document.current_version_id:
            run.status, run.current_stage, run.error_code, run.retryable = "failed", "failed", "DOCUMENT_VERSION_CHANGED", False
            session.commit()
            continue
        payload = session.get(PreparedIngestion, run.id)
        if payload is None:
            raise ParseError("PREPARED_DOCUMENT_MISSING")
        data = json.loads(payload.payload)
        chunks = [replace(_decode_chunk(value), visibility=Visibility(document.visibility),
            data_classification=DataClassification(document.data_classification), owner_user_id=document.owner_user_id,
            product=document.product, version_values=tuple(json.loads(document.version_values or "[]")))
            for value in data["chunks"]]
        prepared_rows.append((document, run, chunks, payload))
        all_chunks.extend(chunks)
        auto_content.update(data["auto_content"])
    if not prepared_rows:
        return []
    team_id = all_chunks[0].team_id
    if any(chunk.team_id != team_id for chunk in all_chunks):
        raise ParseError("BATCH_TEAM_MISMATCH")
    active = session.scalar(select(IndexGenerationRecord).where(
        IndexGenerationRecord.team_id == team_id, IndexGenerationRecord.status == "active"))
    generation = IndexGenerationRecord(team_id=team_id, status="staging") if settings.enable_indexing else None
    if generation:
        session.add(generation)
        session.flush()
    generation_id = generation.id if generation else ""
    all_chunks = [replace(chunk, index_generation=generation_id) for chunk in all_chunks]
    retained = []
    if generation:
        document_ids = [document.id for document, _run, _chunks, _payload in prepared_rows]
        rows = session.execute(select(ChunkRecord, Document).join(Document, ChunkRecord.document_id == Document.id)
            .where(ChunkRecord.team_id == team_id, ChunkRecord.document_id.not_in(document_ids),
                   ChunkRecord.doc_status == "active", Document.doc_status == "active")).all()
        retained = [record_to_chunk(row, doc, generation_id) for row, doc in rows]
    for _document, run, _chunks, _payload in prepared_rows:
        run.current_stage, run.stage_progress_pct = "indexing", 80
        run.failure_details = json.dumps({"staging_generation_id": generation_id})
    session.commit()
    indexable = [chunk for chunk in all_chunks + retained
                 if chunk.chunk_level == "child" and chunk.chunk_status == ChunkStatus.ENABLED]
    # New vectors and retained vectors are cached by the complete model input.
    indexable = embed_chunks(session, indexable, settings)
    if generation:
        async def publish():
            writers = build_index_writers(settings, EngineMode(settings.engine_mode))
            if not writers:
                raise ParseError("INDEXING_FAILED", "No index writers configured.")
            for writer in writers:
                await writer.stage(generation.id, indexable)
                validation = await writer.validate(generation.id)
                if not validation.passed or validation.checked_chunks != len(indexable):
                    raise ParseError("INDEXING_FAILED", "Index validation/count mismatch.")
            for writer in writers:
                await writer.activate(generation.id)
        asyncio.run(publish())
    vectorized = {chunk.chunk_id: chunk for chunk in indexable}
    for document, run, chunks, payload in prepared_rows:
        session.execute(update(ChunkRecord).where(ChunkRecord.document_id == document.id,
            ChunkRecord.id.not_in([chunk.chunk_id for chunk in chunks])).values(
                doc_status="superseded", status="disabled", chunk_status="disabled"))
        for original in chunks:
            chunk = vectorized.get(original.chunk_id, replace(original, index_generation=generation_id))
            row = session.get(ChunkRecord, chunk.chunk_id)
            if row is None:
                row = ChunkRecord(id=chunk.chunk_id)
                session.add(row)
            for name in _chunk_fields():
                setattr(row, name, getattr(chunk, name))
            for name in ("document_id", "team_id", "knowledge_base_id", "owner_user_id", "content", "logical_chunk_key", "content_hash", "source_path", "index_generation"):
                setattr(row, name, getattr(chunk, name))
            row.visibility, row.data_classification = chunk.visibility.value, chunk.data_classification.value
            row.doc_status, row.chunk_status, row.status = "active", chunk.chunk_status.value, chunk.chunk_status.value
            row.auto_content = auto_content[chunk.chunk_id]
            row.heading_path = json.dumps(list(chunk.heading_path))
            row.source_locator = json.dumps(dict(chunk.source_locator))
            row.version_values = json.dumps(list(chunk.version_values))
        version = session.get(DocumentVersion, run.document_version_id)
        version.status, version.chunk_count, version.index_generation = "active", sum(c.chunk_level == "child" for c in chunks), generation_id or None
        run.status, run.current_stage, run.stage_progress_pct = "completed", "completed", 100
        run.error_code, run.retryable, run.failure_details = None, False, "{}"
        document.doc_status = "active"
        session.delete(payload)
    session.flush()
    if generation:
        rows = session.scalars(select(ChunkRecord).where(ChunkRecord.id.in_([chunk.chunk_id for chunk in all_chunks + retained]))).all()
        save_generation_members(session, generation.id, rows)
        if active:
            active.status = "validated"
        generation.status, generation.chunk_count = "active", len(indexable)
        generation.activated_at = generation.validated_at = datetime.now(timezone.utc)
    session.commit()
    return [chunk.chunk_id for chunk in all_chunks if chunk.chunk_level == "child"]


def _process_document(document, run, session, settings, prepare_only=False):
    from backend.app.db.models import PreparedIngestion
    if _cancelled(session, run) or run.status == "completed":
        return []
    prepared = session.get(PreparedIngestion, run.id)
    if prepared is None:
        if not _prepare_document(document, run, session, settings):
            return []
    if prepare_only:
        run.status, run.current_stage = "prepared", "waiting_publish"
        session.commit()
        return []
    return publish_prepared(session, [(document, run)], settings)


def process_document(document, run, session, settings, *, prepare_only=False):
    from backend.app.rag.ingestion.leases import IngestionBusy, team_lease
    from backend.app.rag.embedding.service import EmbeddingError
    from backend.app.rag.parsing.contracts import ParseError
    kb = session.get(KnowledgeBase, document.knowledge_base_id)
    if kb is None:
        _fail(run, document, "KNOWLEDGE_BASE_MISSING", False, session)
        return []
    try:
        from contextlib import nullcontext
        with (nullcontext() if prepare_only else team_lease(session, kb.team_id)):
            session.refresh(run)
            session.refresh(document)
            return _process_document(document, run, session, settings, prepare_only)
    except IngestionBusy:
        # The worker reschedules contention without marking the document failed.
        raise
    except Exception as error:
        fail_ingestion(document, run, session, error)
        return []


def fail_ingestion(document, run, session, error):
    from backend.app.rag.embedding.service import EmbeddingError
    from backend.app.rag.parsing.contracts import ParseError
    session.rollback()
    session.refresh(run)
    if run.status == "cancelled":
        return []
    code = getattr(error, "code", "INDEXING_FAILED")
    retryable = getattr(error, "retryable", code in {"INDEXING_FAILED", "SOURCE_STORAGE_UNAVAILABLE"})
    staging_id = json.loads(run.failure_details or "{}").get("staging_generation_id")
    if staging_id:
        staging = session.get(IndexGenerationRecord, staging_id)
        if staging and staging.status == "staging":
            staging.status = "failed"
            staging.error_message = code
    version = session.get(DocumentVersion, run.document_version_id)
    details = getattr(error, "details", {})
    if version and details.get("pdf_kind"):
        version.parse_metadata = json.dumps(details)
    failure = {"code": code, "retryable": retryable,
               "stage": run.current_stage, "details": details}
    # Known pipeline errors carry safe explanations; arbitrary exceptions may
    # include SQL, credentials or source text and must not be exposed to clients.
    if isinstance(error, (ParseError, EmbeddingError)):
        failure["message"] = str(error)
    run.failure_details = json.dumps(failure)
    # Existing published data stays queryable when a replacement fails.
    run.status, run.error_code, run.retryable, run.current_stage = "failed", code, retryable, "failed"
    existing = session.scalar(select(ChunkRecord.id).where(ChunkRecord.document_id == document.id, ChunkRecord.doc_status == "active"))
    document.doc_status = "active" if existing else "failed"
    session.commit()
    return []

def process_markdown(document: Document, run: IngestionRun, session, settings=None) -> List[str]:
    """Compatibility wrapper used by the upload endpoint and worker."""
    if settings is None:
        settings = Settings.from_env()
    return process_document(document, run, session, settings)
