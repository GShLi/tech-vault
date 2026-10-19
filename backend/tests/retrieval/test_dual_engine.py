import asyncio

from backend.app.rag.domain.models import (
    RetrievalFilters,
    RetrievedChunk,
    SearchRequest,
    SearchResult,
)
from backend.app.rag.retrieval.engines import DualEngineRetriever


def _request() -> SearchRequest:
    return SearchRequest(
        query="virtual threads",
        rewritten_query=None,
        query_vector=[1.0, 0.0],
        filters=RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-a",
        ),
        final_top_n=3,
    )


def _chunk(chunk_id: str, rank: int, **kwargs) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_version_id="dv-1",
        content=chunk_id,
        fused_rank=rank,
        **kwargs,
    )


class _FakeRetriever:
    def __init__(self, result: SearchResult) -> None:
        self._result = result

    async def search(self, request):
        return self._result


class _FailingRetriever:
    async def search(self, request):
        raise RuntimeError("qdrant unavailable")


def test_dual_engine_fuses_bm25_and_dense_without_losing_source_ranks():
    lexical = SearchResult(
        chunks=[_chunk("a", 1, bm25_rank=1), _chunk("b", 2, bm25_rank=2)],
        stage_latency={"bm25_ms": 1.0},
        degraded=False,
        trace_id="trace-1",
    )
    dense = SearchResult(
        chunks=[_chunk("b", 1, dense_rank=1), _chunk("c", 2, dense_rank=2)],
        stage_latency={"dense_ms": 2.0},
        degraded=False,
        trace_id="trace-2",
    )

    result = asyncio.run(
        DualEngineRetriever(
            _FakeRetriever(lexical),
            _FakeRetriever(dense),
        ).search(_request())
    )

    assert [chunk.chunk_id for chunk in result.chunks] == ["b", "a", "c"]
    assert result.chunks[0].bm25_rank == 2
    assert result.chunks[0].dense_rank == 1
    assert result.degraded is False
    assert result.trace_id == "trace-1"
    assert result.stage_latency["dense_ms"] == 2.0


def test_dual_engine_degrades_to_bm25_when_dense_engine_fails():
    lexical = SearchResult(
        chunks=[_chunk("a", 1, bm25_rank=1)],
        stage_latency={"bm25_ms": 1.0},
        degraded=False,
        trace_id="trace-1",
    )

    result = asyncio.run(
        DualEngineRetriever(
            _FakeRetriever(lexical),
            _FailingRetriever(),
        ).search(_request())
    )

    assert [chunk.chunk_id for chunk in result.chunks] == ["a"]
    assert result.degraded is True
    assert result.trace_id == "trace-1"
