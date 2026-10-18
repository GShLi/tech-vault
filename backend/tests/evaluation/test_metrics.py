import math

import pytest

from backend.app.rag.evaluation.metrics import mrr, ndcg_at_k, recall_at_k


def test_recall_at_k_counts_relevant_documents_in_the_top_k():
    assert recall_at_k(["a", "b", "c"], {"b", "z"}, k=2) == 0.5


def test_mrr_uses_reciprocal_rank_of_the_first_relevant_result():
    assert mrr(["x", "a", "b"], {"a", "b"}) == 0.5


def test_ndcg_uses_graded_relevance_and_truncates_to_k():
    actual = ndcg_at_k(
        ["b", "x", "a"],
        {"a": 3.0, "b": 2.0},
        k=3,
    )

    expected = (2.0 + 3.0 / math.log2(4.0)) / (
        3.0 + 2.0 / math.log2(3.0)
    )
    assert actual == pytest.approx(expected)


def test_ndcg_accepts_binary_relevance_sets():
    actual = ndcg_at_k(["x", "a", "b"], {"a", "b"}, k=2)

    expected = (1.0 / math.log2(3.0)) / (
        1.0 + 1.0 / math.log2(3.0)
    )
    assert actual == pytest.approx(expected)


def test_metrics_ignore_duplicate_chunk_ids_in_ranked_results():
    ranked = ["x", "a", "a", "b"]

    assert recall_at_k(ranked, {"a", "b"}, k=3) == 1.0
    assert mrr(ranked, {"a"}) == 0.5
    assert ndcg_at_k(ranked, {"a"}, k=3) == pytest.approx(1.0 / math.log2(3.0))


@pytest.mark.parametrize(
    "metric",
    [
        lambda: recall_at_k(["a"], set(), k=1),
        lambda: recall_at_k(["a"], {"a"}, k=0),
        lambda: mrr(["a"], set()),
        lambda: ndcg_at_k(["a"], set(), k=1),
        lambda: ndcg_at_k(["a"], {"a": 0.0}, k=1),
    ],
)
def test_metrics_return_zero_when_no_relevant_results_can_be_scored(metric):
    assert metric() == 0.0
