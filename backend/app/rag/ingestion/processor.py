"""Synchronous document processing for the first vertical slice.

Parses Markdown and plain-text files into chunks and stores them as
ChunkRecord rows. PDF and DOCX parsing will be added with the worker runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from backend.app.core.ids import new_ulid
from backend.app.db.models import ChunkRecord, Document, IngestionRun


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def process_markdown(document: Document, run: IngestionRun, session) -> List[str]:
    path = Path(document.source_uri or "")
    if not path.exists():
        run.status = "failed"
        run.error_code = "SOURCE_MISSING"
        run.retryable = False
        session.commit()
        return []

    content = _read_text(path)
    run.current_stage = "parsing"
    run.stage_progress_pct = 20
    session.commit()

    from backend.app.rag.chunking.markdown import chunk_markdown

    chunks = chunk_markdown(
        document_version_id=document.current_version_id or document.id,
        source_path=document.file_name,
        content=content,
        document_id=document.id,
        team_id="",
        knowledge_base_id=document.knowledge_base_id,
        owner_user_id=document.owner_user_id,
        visibility=document.visibility,
        data_classification=document.data_classification,
    )

    run.current_stage = "chunking"
    run.stage_progress_pct = 60
    session.commit()

    chunk_ids = []
    for chunk in chunks:
        record = ChunkRecord(
            id=new_ulid(),
            document_id=document.id,
            content=chunk.content,
            heading_path=json.dumps(list(chunk.heading_path)),
            source_locator=json.dumps(chunk.source_locator),
            status="enabled",
        )
        session.add(record)
        chunk_ids.append(record.id)

    run.current_stage = "indexing"
    run.stage_progress_pct = 90
    run.status = "completed"
    run.retryable = False
    document.doc_status = "active"
    session.commit()

    return chunk_ids
