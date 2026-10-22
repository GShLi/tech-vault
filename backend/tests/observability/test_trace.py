import json
from types import SimpleNamespace

from backend.app.rag.observability.trace import (
    candidate_rows, effective_stage_latency, final_context_rows, total_stage_latency,
)
from backend.app.rag.domain.models import RetrievedChunk


def test_nested_latencies_are_counted_once_and_invalid_values_ignored():
    assert total_stage_latency({
        "retrieval_ms": 10, "bm25_ms": 4, "dense_ms": 5,
        "rerank_ms": 20, "gateway_rerank_ms": 19,
        "gateway_answer_ms": 30, "negative": -10, "invalid": float("nan"),
    }) == 60


def test_multiple_gateway_calls_are_summed_and_measured_stages_preserved():
    result = SimpleNamespace(stage_latency={"retrieval_ms": 7, "gateway_answer_ms": 99})
    gateway = SimpleNamespace(audits=[
        SimpleNamespace(purpose="answer", latency_ms=2),
        SimpleNamespace(purpose="answer", latency_ms=3),
    ])
    values = effective_stage_latency(result=result, stage_latency={"generation_ms": 6}, gateway_instance=gateway)
    assert values == {"retrieval_ms": 7, "gateway_answer_ms": 5, "generation_ms": 6}
    assert total_stage_latency(values) == 13


def test_context_keeps_evidence_ids_but_never_copies_content():
    chunk = RetrievedChunk("parent", "version", "sensitive text", 1, evidence_chunk_ids=("child",))
    for row in (candidate_rows([chunk])[0], final_context_rows([chunk])[0]):
        assert row["evidence_chunk_ids"] == ["child"]
        assert "sensitive text" not in json.dumps(row)


def test_persisted_context_accepts_only_valid_child_ids():
    from backend.app.db.models import sanitize_trace_context

    child_id = "chd_" + "a" * 64
    raw = json.dumps([{"chunk_id": "parent", "content": "secret", "evidence_chunk_ids": [
        child_id, child_id, "secret", {"content": "secret"}, 1,
    ]}])
    assert json.loads(sanitize_trace_context(raw)) == [
        {"chunk_id": "parent", "evidence_chunk_ids": [child_id]},
    ]
