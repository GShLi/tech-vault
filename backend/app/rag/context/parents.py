"""Resolve authorized child evidence to consistent parent context."""
import json
from dataclasses import replace

from sqlalchemy import select

from backend.app.db.models import ChunkRecord, GenerationChunk
from backend.app.rag.parsing.contracts import ParseError


def effective_parent_text(text, children, originals):
    edits = []
    for child in children:
        child_id = getattr(child, "chunk_id", None) or child.id
        start, end = child.parent_start_offset, child.parent_end_offset
        original = originals.get(child_id, "")
        if not 0 <= start < end <= len(text) or text[start:end] != original:
            raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Invalid source span.")
        disabled = child.chunk_status == "disabled"
        if disabled or child.content != original:
            edits.append((start, end, "" if disabled else child.content))
    merged = []
    for start, end, value in sorted(edits):
        if merged and start < merged[-1][1]:
            if value or merged[-1][2]:
                raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Overlapping manual edits require a rebuild.")
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]), "")
        else:
            merged.append((start, end, value))
    for start, end, value in reversed(merged):
        text = text[:start] + value + text[end:]
    return text


def _load_parent_family(session, chunks, parent_ids):
    generation_ids = {chunk.index_generation for chunk in chunks if chunk.index_generation}
    if len(generation_ids) > 1:
        raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Mixed generation evidence.")
    if not generation_ids:
        return session.scalars(select(ChunkRecord).where(
            ChunkRecord.id.in_(parent_ids) | ChunkRecord.parent_chunk_id.in_(parent_ids)
        )).all()

    # The generation snapshot is authoritative: live rows may have since changed.
    # Read membership together with snapshots, avoiding one query per parent.
    snapshots = session.execute(select(GenerationChunk.chunk_id, GenerationChunk.snapshot).where(
        GenerationChunk.generation_id == next(iter(generation_ids))
    ))
    rows = []
    for member_id, raw in snapshots:
        snapshot = json.loads(raw)
        if snapshot.get("id") in parent_ids or snapshot.get("parent_chunk_id") in parent_ids:
            if snapshot.get("id") != member_id:
                raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Parent generation mismatch.")
            rows.append(ChunkRecord(**snapshot))
    return rows


def hydrate_parent_chunks(session, chunks):
    parent_ids = {chunk.parent_chunk_id for chunk in chunks if chunk.parent_chunk_id}
    if not parent_ids:
        return list(chunks)
    rows = _load_parent_family(session, chunks, parent_ids)
    parents = {row.id: row for row in rows if row.id in parent_ids}
    children = {}
    for row in rows:
        if row.parent_chunk_id:
            children.setdefault(row.parent_chunk_id, []).append(row)
    evidence = {}
    for chunk in chunks:
        if chunk.parent_chunk_id:
            evidence.setdefault(chunk.parent_chunk_id, []).append(chunk.chunk_id)
    hydrated, seen = [], set()
    for chunk in chunks:
        parent_id = chunk.parent_chunk_id
        if not parent_id:
            hydrated.append(chunk)
            continue
        if parent_id in seen:
            continue
        parent = parents.get(parent_id)
        family = children.get(parent_id, [])
        matched = next((row for row in family if row.id == chunk.chunk_id), None)
        if parent is None or matched is None or parent.chunk_level != "parent":
            raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Parent evidence is missing.")
        locator = json.loads(parent.source_locator or "{}")
        if locator.get("document_version_id") != chunk.document_version_id:
            raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Parent version mismatch.")
        for child in family:
            if any(getattr(parent, key) != getattr(child, key) for key in (
                "document_id", "team_id", "knowledge_base_id", "owner_user_id", "visibility", "data_classification"
            )) or json.loads(child.source_locator or "{}").get("document_version_id") != chunk.document_version_id:
                raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Parent scope mismatch.")
        if matched.chunk_status != "enabled":
            raise ParseError("PARENT_CHILD_INTEGRITY_FAILED", "Retrieved child is disabled.")
        content = effective_parent_text(parent.content, family, {row.id: row.auto_content for row in family})
        if content.strip():
            hydrated.append(replace(chunk, chunk_id=parent_id, parent_chunk_id=None, content=content,
                evidence_chunk_ids=tuple(evidence[parent_id]), source_locator=locator,
                fused_rank=len(hydrated) + 1))
        seen.add(parent_id)
    return hydrated
