"""Document processing: parse, chunk, embed and index."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import List

from backend.app.core.config import Settings
from backend.app.rag.domain.models import DataClassification, Visibility
from backend.app.rag.embedding.service import EmbeddingClient
from backend.app.rag.retrieval.config import EngineMode
from backend.app.rag.retrieval.factory import build_index_writers
from backend.app.db.models import (
    ChunkRecord,
    Document,
    DocumentVersion,
    IngestionRun,
    KnowledgeBase,
)


def _fail(run: IngestionRun, document: Document, code: str, retryable: bool, session) -> None:
    run.status = "failed"
    run.error_code = code
    run.retryable = retryable
    document.doc_status = "failed"
    session.commit()


def process_document(
    document: Document,
    run: IngestionRun,
    session,
    settings: Settings,
) -> List[str]:
    path = Path(document.source_uri or "")
    if not path.exists():
        _fail(run, document, "SOURCE_MISSING", False, session)
        return []

    suffix = path.suffix.lower()
    if suffix not in {".md", ".txt"}:
        _fail(run, document, "UNSUPPORTED_FILE_TYPE", False, session)
        return []

    knowledge_base = session.get(KnowledgeBase, document.knowledge_base_id)
    if knowledge_base is None:
        _fail(run, document, "KNOWLEDGE_BASE_MISSING", False, session)
        return []

    content = path.read_text(encoding="utf-8")
    run.current_stage = "parsing"
    run.stage_progress_pct = 20
    session.commit()

    from backend.app.rag.chunking.markdown import chunk_markdown

    chunks = chunk_markdown(
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
    )

    run.current_stage = "chunking"
    run.stage_progress_pct = 50
    session.commit()

    embedder = EmbeddingClient(settings.embedding_url)
    vectors = embedder.embed([chunk.content for chunk in chunks])
    chunks = [
        replace(chunk, content_vector=vector)
        for chunk, vector in zip(chunks, vectors)
    ]

    run.current_stage = "indexing"
    run.stage_progress_pct = 75
    session.commit()

    generation = "current"
    if settings.enable_indexing:
        async def index_chunks() -> None:
            writers = build_index_writers(settings, EngineMode.DUAL_ENGINE)
            for writer in writers:
                await writer.stage(generation, chunks)
                validation = await writer.validate(generation)
                if not validation.passed:
                    raise RuntimeError(
                        "index validation failed: " + ", ".join(validation.errors)
                    )
                await writer.activate(generation)

        try:
            asyncio.run(index_chunks())
        except Exception:
            _fail(run, document, "INDEXING_FAILED", True, session)
            return []

    for chunk in chunks:
        record = ChunkRecord(
            id=chunk.chunk_id,
            document_id=document.id,
            team_id=chunk.team_id,
            knowledge_base_id=chunk.knowledge_base_id,
            owner_user_id=chunk.owner_user_id,
            visibility=chunk.visibility.value,
            data_classification=chunk.data_classification.value,
            doc_status="active",
            chunk_status="enabled",
            content=chunk.content,
            heading_path=json.dumps(list(chunk.heading_path)),
            source_locator=json.dumps(dict(chunk.source_locator)),
            version_values=json.dumps(list(chunk.version_values)),
            logical_chunk_key=chunk.logical_chunk_key,
            content_hash=chunk.content_hash,
            source_path=chunk.source_path,
            index_generation=generation if settings.enable_indexing else "",
            status="enabled",
        )
        session.add(record)

    version = session.get(DocumentVersion, run.document_version_id)
    if version is not None:
        version.status = "active"
        version.chunk_count = len(chunks)
        version.index_generation = generation if settings.enable_indexing else None

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
