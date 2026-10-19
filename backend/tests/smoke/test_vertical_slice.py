import asyncio

import pytest

from backend.app.rag.chunking.markdown import chunk_markdown
from backend.app.rag.domain.models import (
    DataClassification,
    RetrievalFilters,
    SearchRequest,
    Visibility,
)
from backend.app.rag.evaluation.metrics import mrr, ndcg_at_k, recall_at_k
from backend.app.rag.retrieval.in_memory import InMemoryRetriever


MARKDOWN_FIXTURE = (
    "# JVM\n\n"
    "## Virtual Threads\n\n"
    "Virtual threads\n\n"
    "## Scheduling\n\n"
    "virtual\n\n"
    "## Carrier Pools\n\n"
    "lightweight concurrency\n"
)


def _chunk_for(chunks, heading):
    return next(chunk for chunk in chunks if chunk.heading_path[-1] == heading)


def test_vertical_slice_chunks_filters_fuses_and_scores_retrieval():
    shared_chunks = chunk_markdown(
        document_version_id="dv-shared",
        source_path="docs/jvm.md",
        content=MARKDOWN_FIXTURE,
        team_id="team-a",
        knowledge_base_id="kb-a",
        owner_user_id="user-a",
    )
    private_chunks = chunk_markdown(
        document_version_id="dv-private",
        source_path="docs/private.md",
        content="# Private\n\n## Virtual Threads\n\nVirtual threads\n",
        team_id="team-a",
        knowledge_base_id="kb-a",
        owner_user_id="user-a",
        visibility=Visibility.PRIVATE,
    )
    foreign_chunks = chunk_markdown(
        document_version_id="dv-foreign",
        source_path="docs/foreign.md",
        content="# Foreign\n\n## Virtual Threads\n\nVirtual threads\n",
        team_id="team-b",
        knowledge_base_id="kb-foreign",
        owner_user_id="user-c",
        visibility=Visibility.TEAM_SHARED,
        data_classification=DataClassification.PUBLIC,
    )

    virtual_chunk = _chunk_for(shared_chunks, "Virtual Threads")
    scheduling_chunk = _chunk_for(shared_chunks, "Scheduling")
    carrier_chunk = _chunk_for(shared_chunks, "Carrier Pools")
    embedding = {
        virtual_chunk.chunk_id: [0.6, 0.8],
        scheduling_chunk.chunk_id: [0.0, 1.0],
        carrier_chunk.chunk_id: [1.0, 0.0],
        private_chunks[0].chunk_id: [1.0, 0.0],
        foreign_chunks[0].chunk_id: [1.0, 0.0],
    }
    retriever = InMemoryRetriever(
        chunks=shared_chunks + private_chunks + foreign_chunks,
        embedding=embedding,
    )
    request = SearchRequest(
        query="virtual threads",
        rewritten_query=None,
        query_vector=[1.0, 0.0],
        filters=RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-b",
        ),
        bm25_top_k=10,
        dense_top_k=10,
        final_top_n=10,
    )

    result = asyncio.run(retriever.search(request))

    assert [chunk.content for chunk in result.chunks] == [
        "Virtual threads",
        "lightweight concurrency",
        "virtual",
    ]
    assert [chunk.fused_rank for chunk in result.chunks] == [1, 2, 3]
    assert [
        (chunk.bm25_rank, chunk.dense_rank) for chunk in result.chunks
    ] == [(1, 2), (None, 1), (2, None)]

    ranked_ids = [chunk.chunk_id for chunk in result.chunks]
    relevant_ids = {virtual_chunk.chunk_id, carrier_chunk.chunk_id}
    assert recall_at_k(ranked_ids, relevant_ids, k=1) == 0.5
    assert recall_at_k(ranked_ids, relevant_ids, k=3) == 1.0
    assert mrr(ranked_ids, relevant_ids) == 1.0
    assert ndcg_at_k(ranked_ids, relevant_ids, k=3) == pytest.approx(1.0)

    # One request result owns one trace id; separate requests need not reuse it.
    trace_id = result.trace_id
    assert isinstance(trace_id, str)
    assert trace_id.strip()
    assert result.trace_id == trace_id
