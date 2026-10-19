"""Live verification of the Elasticsearch and Qdrant retrieval adapters.

Requires the Docker Compose stack with ES on :59200 and Qdrant on :56333.
Run: .venv/bin/python scripts/verify_retrieval_stack.py
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace

from backend.app.core.config import Settings
from backend.app.rag.domain.models import (
    Chunk,
    DataClassification,
    DocumentStatus,
    ChunkStatus,
    RetrievalFilters,
    SearchRequest,
    Visibility,
)
from backend.app.rag.indexing.elasticsearch import ElasticsearchIndexWriter
from backend.app.rag.indexing.qdrant import QdrantIndexWriter
from backend.app.rag.retrieval.config import EngineMode
from backend.app.rag.retrieval.factory import build_retriever


def _vector(value: float) -> list:
    return [value] * 1024


def _chunk(chunk_id: str, content: str, owner: str, visibility: Visibility) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc-" + chunk_id,
        document_version_id="dv-live",
        team_id="team-a",
        knowledge_base_id="kb-a",
        owner_user_id=owner,
        visibility=visibility,
        data_classification=DataClassification.INTERNAL,
        source_path="live.md",
        heading_path=("Live",),
        content=content,
        logical_chunk_key="live#" + chunk_id,
        content_hash="hash-" + chunk_id,
        content_vector=_vector(0.0),
        doc_status=DocumentStatus.ACTIVE,
        chunk_status=ChunkStatus.ENABLED,
    )


async def main() -> None:
    settings = Settings(
        environment="development",
        es_url="http://127.0.0.1:59200",
        qdrant_url="http://127.0.0.1:56333",
    )
    generation = "livetest" + str(int(time.time()))
    chunks = [
        _chunk("live-shared", "virtual threads shared", "user-a", Visibility.TEAM_SHARED),
        _chunk("live-private", "virtual threads private", "user-a", Visibility.PRIVATE),
    ]
    chunks[0] = replace(chunks[0], content_vector=_vector(1.0))
    chunks[1] = replace(chunks[1], content_vector=_vector(0.9))

    es_writer = ElasticsearchIndexWriter(settings.es_url)
    qdrant_writer = QdrantIndexWriter(settings.qdrant_url)

    try:
        await es_writer.stage(generation, chunks)
        await qdrant_writer.stage(generation, chunks)
        assert (await es_writer.validate(generation)).passed
        assert (await qdrant_writer.validate(generation)).passed
        await es_writer.activate(generation)
        await qdrant_writer.activate(generation)

        request = SearchRequest(
            query="virtual threads",
            rewritten_query=None,
            query_vector=_vector(1.0),
            filters=RetrievalFilters(
                team_id="team-a",
                knowledge_base_ids=("kb-a",),
                viewer_user_id="user-b",
            ),
            final_top_n=5,
        )

        dual = build_retriever(settings, generation, EngineMode.DUAL_ENGINE)
        dual_result = await dual.search(request)
        dual_ids = [chunk.chunk_id for chunk in dual_result.chunks]
        assert dual_ids == ["live-shared"], dual_ids

        single = build_retriever(settings, generation, EngineMode.ELASTIC_SINGLE)
        single_result = await single.search(request)
        single_ids = [chunk.chunk_id for chunk in single_result.chunks]
        assert single_ids == ["live-shared"], single_ids

        print("dual_engine:", dual_ids, "degraded=", dual_result.degraded)
        print("elastic_single:", single_ids, "degraded=", single_result.degraded)
        print("retrieval stack OK")
    finally:
        es_writer.deactivate()
        qdrant_writer.deactivate()
        await es_writer.cleanup(generation)
        await qdrant_writer.cleanup(generation)


if __name__ == "__main__":
    asyncio.run(main())
