import pytest

from backend.app.rag.fusion.rrf import reciprocal_rank_fusion


def test_rrf_deduplicates_and_prefers_candidates_seen_in_both_lists():
    fused = reciprocal_rank_fusion(
        bm25_ids=["a", "b", "c"],
        dense_ids=["b", "a", "d"],
        k=60,
    )

    assert [candidate.chunk_id for candidate in fused[:2]] == ["a", "b"]
    assert len(fused) == 4
    assert fused[0].fused_score == pytest.approx((1.0 / 61.0) + (1.0 / 62.0))
    assert fused[0].bm25_rank == 1
    assert fused[0].dense_rank == 2
    assert fused[0].fused_rank == 1


def test_rrf_applies_source_weights_and_keeps_missing_ranks_empty():
    fused = reciprocal_rank_fusion(
        bm25_ids=["exact-match"],
        dense_ids=["concept-match"],
        k=60,
        bm25_weight=3.0,
        dense_weight=0.5,
    )

    assert [candidate.chunk_id for candidate in fused] == ["exact-match", "concept-match"]
    assert fused[0].fused_score == pytest.approx(3.0 / 61.0)
    assert fused[0].bm25_rank == 1
    assert fused[0].dense_rank is None
    assert fused[1].fused_score == pytest.approx(0.5 / 61.0)
    assert fused[1].bm25_rank is None
    assert fused[1].dense_rank == 1


def test_rrf_counts_each_source_once_while_preserving_retrieval_ranks():
    fused = reciprocal_rank_fusion(
        bm25_ids=["a", "a", "b"],
        dense_ids=[],
        k=60,
    )

    assert [candidate.chunk_id for candidate in fused] == ["a", "b"]
    assert fused[0].fused_score == pytest.approx(1.0 / 61.0)
    assert fused[0].bm25_rank == 1
    assert fused[1].fused_score == pytest.approx(1.0 / 63.0)
    assert fused[1].bm25_rank == 3


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"k": -1}, "k must be non-negative"),
        ({"bm25_weight": -0.1}, "RRF weights must be non-negative"),
        ({"dense_weight": -0.1}, "RRF weights must be non-negative"),
    ],
)
def test_rrf_rejects_invalid_parameters(kwargs, message):
    with pytest.raises(ValueError, match=message):
        reciprocal_rank_fusion(bm25_ids=["a"], dense_ids=["b"], **kwargs)
