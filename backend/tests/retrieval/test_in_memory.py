import asyncio

from backend.app.rag.domain.models import (
    Chunk,
    DataClassification,
    RetrievalFilters,
    SearchRequest,
    Visibility,
)
from backend.app.rag.retrieval.in_memory import InMemoryRetriever


def _chunk(
    chunk_id: str,
    owner: str,
    visibility: Visibility,
    content: str,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="doc-" + chunk_id,
        document_version_id="dv-1",
        team_id="team-a",
        knowledge_base_id="kb-a",
        owner_user_id=owner,
        visibility=visibility,
        data_classification=DataClassification.INTERNAL,
        source_path="docs/spring.md",
        heading_path=("Spring", "Virtual Threads"),
        content=content,
        logical_chunk_key="docs/spring.md#spring/virtual-threads",
        content_hash="hash-" + chunk_id,
    )


def test_in_memory_retriever_applies_permission_filters_before_ranking():
    private_chunk = _chunk("private-1", "user-a", Visibility.PRIVATE, "virtual threads private")
    shared_chunk = _chunk("shared-1", "user-a", Visibility.TEAM_SHARED, "virtual threads shared")
    retriever = InMemoryRetriever(chunks=[private_chunk, shared_chunk])
    request = SearchRequest(
        query="virtual threads",
        rewritten_query=None,
        query_vector=[1.0, 0.0],
        filters=RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-b",
        ),
    )

    result = asyncio.run(retriever.search(request))

    assert [chunk.chunk_id for chunk in result.chunks] == ["shared-1"]
    assert result.degraded is False
    assert result.trace_id


def test_in_memory_retriever_honors_explicit_document_grant():
    private_chunk = _chunk("private-1", "user-a", Visibility.PRIVATE, "virtual threads private")
    retriever = InMemoryRetriever(chunks=[private_chunk])
    request = SearchRequest(
        query="virtual threads",
        rewritten_query=None,
        query_vector=[1.0, 0.0],
        filters=RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-b",
            explicit_document_grants=("doc-private-1",),
        ),
    )

    result = asyncio.run(retriever.search(request))

    assert [chunk.chunk_id for chunk in result.chunks] == ["private-1"]


def test_in_memory_retriever_preserves_source_ranks_for_rrf():
    lexical_first = _chunk(
        "lexical-first",
        "user-a",
        Visibility.TEAM_SHARED,
        "virtual threads",
    )
    dense_first = _chunk(
        "dense-first",
        "user-a",
        Visibility.TEAM_SHARED,
        "virtual other",
    )
    retriever = InMemoryRetriever(
        chunks=[lexical_first, dense_first],
        embedding={
            "lexical-first": [0.0, 1.0],
            "dense-first": [1.0, 0.0],
        },
    )
    request = SearchRequest(
        query="virtual threads",
        rewritten_query=None,
        query_vector=[1.0, 0.0],
        filters=RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-a",
        ),
    )

    result = asyncio.run(retriever.search(request))
    dense_first_result = next(
        chunk for chunk in result.chunks if chunk.chunk_id == "dense-first"
    )

    assert dense_first_result.bm25_rank == 2
    assert dense_first_result.dense_rank == 1

