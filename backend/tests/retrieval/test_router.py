import asyncio

from backend.app.rag.domain.models import (
    RetrievalFilters,
    SearchRequest,
    SearchResult,
)
from backend.app.rag.retrieval.config import EngineMode, RetrievalConfig
from backend.app.rag.retrieval.router import RetrievalRouter


class _StubRetriever:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self.requests = []

    async def search(self, request: SearchRequest) -> SearchResult:
        self.requests.append(request)
        return SearchResult(
            chunks=[],
            stage_latency={},
            degraded=False,
            trace_id=self.trace_id,
        )


def test_router_uses_backend_configured_engine_mode():
    config = RetrievalConfig(engine_mode=EngineMode.ELASTIC_SINGLE)
    router = RetrievalRouter(
        retrievers={
            EngineMode.DUAL_ENGINE: _StubRetriever("dual"),
            EngineMode.ELASTIC_SINGLE: _StubRetriever("single"),
        },
        config=config,
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

    result = asyncio.run(router.search(request))

    assert result.trace_id == "single"


def test_router_applies_retrieval_config_to_internal_request():
    config = RetrievalConfig(
        engine_mode=EngineMode.DUAL_ENGINE,
        bm25_top_k=7,
        dense_top_k=8,
        rrf_k=22,
        rerank_input_size=9,
        final_top_n=3,
        answer_context_top_n=2,
    )
    retriever = _StubRetriever("dual")
    router = RetrievalRouter(
        retrievers={EngineMode.DUAL_ENGINE: retriever},
        config=config,
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

    asyncio.run(router.search(request))

    effective = retriever.requests[0]
    assert effective.bm25_top_k == 7
    assert effective.dense_top_k == 8
    assert effective.rrf_k == 22
    assert effective.rerank_input_size == 9
    assert effective.final_top_n == 3

