import httpx

from backend.app.rag.domain.models import RetrievedChunk
from backend.app.rag.rerank.service import RerankerClient


def _chunk(chunk_id: str, content: str, rank: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_version_id="dv-1",
        content=content,
        fused_rank=rank,
    )


def test_reranker_uses_service_scores_and_stable_tie_break():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"scores": [0.1, 0.9, 0.9]})
    )
    client = RerankerClient("http://reranker", transport=transport)

    reranked = client.rerank(
        "virtual threads",
        [_chunk("a", "A", 1), _chunk("b", "B", 2), _chunk("c", "C", 3)],
        top_n=3,
    )

    assert [chunk.chunk_id for chunk in reranked] == ["b", "c", "a"]
    assert [chunk.fused_rank for chunk in reranked] == [1, 2, 3]
    assert reranked[0].rerank_score == 0.9


def test_reranker_falls_back_to_local_lexical_scores_when_service_is_down():
    def unavailable(request):
        raise httpx.ConnectError("offline", request=request)

    client = RerankerClient("http://reranker", transport=httpx.MockTransport(unavailable))
    reranked = client.rerank(
        "virtual threads",
        [
            _chunk("unrelated", "garbage collection tuning", 1),
            _chunk("relevant", "Virtual threads reduce thread cost", 2),
        ],
        top_n=2,
    )

    assert reranked[0].chunk_id == "relevant"
    assert reranked[0].rerank_score > reranked[1].rerank_score
