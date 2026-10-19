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

    async def search(self, request: SearchRequest) -> SearchResult:
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

