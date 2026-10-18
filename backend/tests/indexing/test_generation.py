import asyncio

from backend.app.rag.domain.models import (
    Chunk,
    ChunkStatus,
    DataClassification,
    DocumentStatus,
    Visibility,
)
from backend.app.rag.indexing.generation import InMemoryIndexWriter


def _chunk(chunk_id: str = "chunk-1") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        document_version_id="dv-1",
        team_id="team-a",
        knowledge_base_id="kb-a",
        owner_user_id="user-a",
        visibility=Visibility.TEAM_SHARED,
        data_classification=DataClassification.INTERNAL,
        source_path="docs/a.md",
        heading_path=("A",),
        content="content",
        logical_chunk_key="docs/a.md#a",
        content_hash="hash",
        doc_status=DocumentStatus.ACTIVE,
        chunk_status=ChunkStatus.ENABLED,
        index_generation="gen-1",
    )


def test_generation_must_be_validated_before_activation():
    writer = InMemoryIndexWriter()
    asyncio.run(writer.stage("gen-1", [_chunk()]))

    try:
        asyncio.run(writer.activate("gen-1"))
    except ValueError as exc:
        assert "unvalidated" in str(exc)
    else:
        raise AssertionError("activation should fail")

    result = asyncio.run(writer.validate("gen-1"))
    assert result.passed is True
    asyncio.run(writer.activate("gen-1"))
    assert writer.active_generation == "gen-1"
    assert [chunk.chunk_id for chunk in writer.active_chunks()] == ["chunk-1"]


def test_generation_validation_rejects_duplicate_chunks():
    writer = InMemoryIndexWriter()
    asyncio.run(writer.stage("gen-1", [_chunk(), _chunk()]))

    result = asyncio.run(writer.validate("gen-1"))

    assert result.passed is False
    assert any("duplicate chunk_id" in error for error in result.errors)

