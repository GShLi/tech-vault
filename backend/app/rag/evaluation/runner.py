from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Tuple, Union

from .metrics import mrr, ndcg_at_k, recall_at_k


@dataclass(frozen=True)
class EvaluationInput:
    query_id: str
    query_type: str
    relevant_chunk_ids: Tuple[str, ...]
    relevance: Mapping[str, float]
    forbidden_chunk_ids: Tuple[str, ...] = ()
    expected_citation_chunk_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationObservation:
    ranked_chunk_ids: Sequence[str]
    citation_chunk_ids: Sequence[str] = ()
    grounded: bool = False
    latency_ms: float = 0.0


@dataclass(frozen=True)
class EvaluationRunResult:
    metrics: Dict[str, float]
    report: Dict[str, object]


def _mean(values: Iterable[float]) -> float:
    rows = list(values)
    return float(sum(rows)) / float(len(rows)) if rows else 0.0


def _unique(values: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(values))


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _observation(value: Union[EvaluationObservation, Sequence[str]]) -> EvaluationObservation:
    if isinstance(value, EvaluationObservation):
        return value
    return EvaluationObservation(ranked_chunk_ids=tuple(value))


def evaluate_ranked_cases(
    cases: Sequence[EvaluationInput],
    retrieve: Callable[
        [EvaluationInput], Union[EvaluationObservation, Sequence[str]]
    ],
    k: int = 10,
) -> EvaluationRunResult:
    case_rows: List[Dict[str, object]] = []
    grouped: Dict[str, List[Dict[str, float]]] = {}
    failed_query_ids: List[str] = []

    for case in cases:
        error = None
        observation = EvaluationObservation(())
        try:
            observation = _observation(retrieve(case))
        except Exception as caught:
            error = str(caught) or caught.__class__.__name__
            failed_query_ids.append(case.query_id)

        ranked_ids = _unique(observation.ranked_chunk_ids)
        citation_ids = _unique(observation.citation_chunk_ids)
        expected_citations = set(
            case.expected_citation_chunk_ids or case.relevant_chunk_ids
        )
        citation_accuracy = (
            float(len(set(citation_ids).intersection(expected_citations)))
            / float(len(citation_ids))
            if citation_ids
            else (1.0 if not expected_citations else 0.0)
        )
        permission_leakage = bool(
            set(ranked_ids + citation_ids).intersection(case.forbidden_chunk_ids)
        )

        relevance = dict(case.relevance) if case.relevance else set(case.relevant_chunk_ids)
        case_metrics = {
            "recall_at_{0}".format(k): recall_at_k(
                ranked_ids, case.relevant_chunk_ids, k
            ),
            "mrr": mrr(ranked_ids, case.relevant_chunk_ids),
            "ndcg_at_{0}".format(k): ndcg_at_k(ranked_ids, relevance, k),
            "ndcg_at_10": ndcg_at_k(ranked_ids, relevance, 10),
            "recall_at_20": recall_at_k(ranked_ids, case.relevant_chunk_ids, 20),
            "citation_accuracy": citation_accuracy,
            "groundedness": 1.0 if observation.grounded else 0.0,
            "permission_leakage": 1.0 if permission_leakage else 0.0,
        }
        grouped.setdefault(case.query_type, []).append(case_metrics)
        row: Dict[str, object] = {
            "query_id": case.query_id,
            "query_type": case.query_type,
            "ranked_chunk_ids": list(ranked_ids),
            **case_metrics,
            "citation_chunk_ids": citation_ids,
            "grounded": bool(observation.grounded),
            "latency_ms": float(observation.latency_ms),
        }
        if error is not None:
            row["error"] = error
        case_rows.append(row)

    recall_key = "recall_at_{0}".format(k)
    ndcg_key = "ndcg_at_{0}".format(k)
    metrics = {
        "case_count": float(len(cases)),
        recall_key: _mean(row[recall_key] for row in case_rows),
        "mrr": _mean(row["mrr"] for row in case_rows),
        ndcg_key: _mean(row[ndcg_key] for row in case_rows),
        "recall_at_20": _mean(row["recall_at_20"] for row in case_rows),
        "ndcg_at_10": _mean(row["ndcg_at_10"] for row in case_rows),
        "citation_accuracy": _mean(
            row["citation_accuracy"] for row in case_rows
        ),
        "groundedness": _mean(row["groundedness"] for row in case_rows),
        "permission_leakage_count": float(
            sum(row["permission_leakage"] for row in case_rows)
        ),
        "latency_p50_ms": _percentile(
            [row["latency_ms"] for row in case_rows], 0.50
        ),
        "latency_p95_ms": _percentile(
            [row["latency_ms"] for row in case_rows], 0.95
        ),
    }
    by_query_type = {
        query_type: {
            "case_count": len(rows),
            recall_key: _mean(row[recall_key] for row in rows),
            "mrr": _mean(row["mrr"] for row in rows),
            ndcg_key: _mean(row[ndcg_key] for row in rows),
            "citation_accuracy": _mean(
                row["citation_accuracy"] for row in rows
            ),
            "groundedness": _mean(row["groundedness"] for row in rows),
            "permission_leakage_count": sum(
                row["permission_leakage"] for row in rows
            ),
        }
        for query_type, rows in grouped.items()
    }
    return EvaluationRunResult(
        metrics=metrics,
        report={
            "k": k,
            "cases": case_rows,
            "by_query_type": by_query_type,
            "failed_query_ids": failed_query_ids,
        },
    )


def evaluate_release_gate(
    metrics: Mapping[str, float],
    baseline_metrics: Mapping[str, float] | None = None,
) -> Dict[str, object]:
    current = {key: float(value) for key, value in metrics.items()}
    baseline = {
        key: float(value)
        for key, value in (baseline_metrics or {}).items()
    }
    checks: List[Dict[str, object]] = []
    failed_checks: List[str] = []

    leakage = current.get("permission_leakage_count", current.get("permission_leakage", 0.0))
    leakage_passed = leakage == 0.0
    checks.append(
        {
            "name": "permission_leakage",
            "actual": leakage,
            "expected": 0.0,
            "passed": leakage_passed,
        }
    )
    if not leakage_passed:
        failed_checks.append("permission_leakage")

    for metric in (
        "recall_at_20",
        "ndcg_at_10",
        "citation_accuracy",
        "groundedness",
    ):
        if metric not in baseline:
            continue
        actual = current.get(metric, 0.0)
        expected = baseline[metric]
        passed = actual >= expected
        checks.append(
            {
                "name": metric,
                "actual": actual,
                "baseline": expected,
                "passed": passed,
            }
        )
        if not passed:
            failed_checks.append(metric)

    if "latency_p95_ms" in baseline:
        actual = current.get("latency_p95_ms", 0.0)
        expected = baseline["latency_p95_ms"]
        passed = actual <= expected
        checks.append(
            {
                "name": "latency_p95_ms",
                "actual": actual,
                "baseline": expected,
                "passed": passed,
            }
        )
        if not passed:
            failed_checks.append("latency_p95_ms")

    return {
        "passed": not failed_checks,
        "failed_checks": failed_checks,
        "checks": checks,
        "baseline_available": bool(baseline),
    }
