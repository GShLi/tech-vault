import math

import pytest

from backend.app.rag.evaluation.runner import EvaluationInput, evaluate_ranked_cases


def test_evaluate_ranked_cases_aggregates_metrics_and_query_types():
    cases = [
        EvaluationInput("q1", "concept", ["a", "b"], {"a": 2.0, "b": 1.0}),
        EvaluationInput("q2", "exact_identifier", ["c"], {}),
    ]
    rankings = {"q1": ["x", "a", "b"], "q2": ["c"]}

    result = evaluate_ranked_cases(cases, lambda case: rankings[case.query_id], k=3)

    assert result.metrics["case_count"] == 2
    assert result.metrics["recall_at_3"] == pytest.approx(1.0)
    assert result.metrics["mrr"] == pytest.approx(0.75)
    first_ndcg = (2.0 / math.log2(3.0) + 0.5) / (
        2.0 + 1.0 / math.log2(3.0)
    )
    assert result.metrics["ndcg_at_3"] == pytest.approx((first_ndcg + 1.0) / 2.0)
    assert result.report["by_query_type"]["concept"]["recall_at_3"] == pytest.approx(1.0)
    assert result.report["cases"][0]["query_id"] == "q1"


def test_evaluate_ranked_cases_records_retrieval_failure_without_losing_other_cases():
    cases = [
        EvaluationInput("q1", "concept", ["a"], {}),
        EvaluationInput("q2", "concept", ["b"], {}),
    ]

    def retrieve(case):
        if case.query_id == "q1":
            raise RuntimeError("index unavailable")
        return ["b"]

    result = evaluate_ranked_cases(cases, retrieve, k=5)

    assert result.metrics["case_count"] == 2
    assert result.metrics["mrr"] == 0.5
    assert result.report["failed_query_ids"] == ["q1"]
    assert result.report["cases"][0]["error"] == "index unavailable"


def test_evaluation_observations_aggregate_permission_citation_and_grounding_metrics():
    from backend.app.rag.evaluation.runner import EvaluationObservation

    cases = [
        EvaluationInput(
            "q1",
            "concept",
            ["a"],
            {"a": 1.0},
            forbidden_chunk_ids=("secret",),
        ),
        EvaluationInput(
            "q2",
            "concept",
            ["b"],
            {"b": 1.0},
            forbidden_chunk_ids=("secret-2",),
        ),
    ]
    observations = {
        "q1": EvaluationObservation(
            ranked_chunk_ids=("a", "secret"),
            citation_chunk_ids=("a",),
            grounded=True,
            latency_ms=10.0,
        ),
        "q2": EvaluationObservation(
            ranked_chunk_ids=("b",),
            citation_chunk_ids=("b", "secret-2"),
            grounded=False,
            latency_ms=30.0,
        ),
    }

    result = evaluate_ranked_cases(
        cases,
        lambda case: observations[case.query_id],
        k=10,
    )

    assert result.metrics["permission_leakage_count"] == 2
    assert result.metrics["citation_accuracy"] == pytest.approx(0.75)
    assert result.metrics["groundedness"] == pytest.approx(0.5)
    assert result.metrics["latency_p50_ms"] == pytest.approx(20.0)
    assert result.metrics["latency_p95_ms"] >= 29.0


def test_release_gate_blocks_permission_leakage_and_metric_regression():
    from backend.app.rag.evaluation.runner import evaluate_release_gate

    gate = evaluate_release_gate(
        metrics={
            "permission_leakage_count": 1,
            "recall_at_20": 0.7,
            "ndcg_at_10": 0.8,
            "citation_accuracy": 0.85,
            "groundedness": 0.9,
            "latency_p95_ms": 500.0,
        },
        baseline_metrics={
            "recall_at_20": 0.8,
            "ndcg_at_10": 0.8,
            "citation_accuracy": 0.9,
            "groundedness": 0.9,
            "latency_p95_ms": 400.0,
        },
    )

    assert gate["passed"] is False
    assert "permission_leakage" in gate["failed_checks"]
    assert "recall_at_20" in gate["failed_checks"]
    assert "citation_accuracy" in gate["failed_checks"]
    assert "latency_p95_ms" in gate["failed_checks"]
