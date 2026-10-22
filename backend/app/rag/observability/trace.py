"""Pure trace payload and duration helpers shared by all answer paths."""
import json
import math
from typing import Any, Mapping, Optional, Sequence

from backend.app.rag.domain.models import RetrievedChunk, SearchResult
from backend.app.rag.llm_gateway.contracts import RewriteResult


def candidate_rows(chunks: Sequence[RetrievedChunk]) -> list:
    return [
        {
            "chunk_id": chunk.chunk_id,
            **({"evidence_chunk_ids": list(chunk.evidence_chunk_ids)} if chunk.evidence_chunk_ids else {}),
            "rank": chunk.fused_rank,
            "score": chunk.rerank_score,
            "bm25_rank": chunk.bm25_rank,
            "dense_rank": chunk.dense_rank,
            "bm25_score": chunk.bm25_score,
            "dense_score": chunk.dense_score,
            "rrf_score": chunk.rrf_score,
            "rerank_score": chunk.rerank_score,
            "matched_terms": list(chunk.matched_terms),
        }
        for chunk in chunks
    ]


def rewrite_trace_payload(rewrite: Optional[RewriteResult]) -> dict:
    if rewrite is None:
        return {}
    return {
        "original_query": rewrite.original_query,
        "rewritten_query": rewrite.rewritten_query,
        "changed": rewrite.changed,
        "route": rewrite.route,
        "provider_id": rewrite.provider_id,
        "model_id": rewrite.model_id,
        "structured_mode": rewrite.structured_mode,
        "extracted_filters": rewrite.extracted_filters,
        "applied_filters": rewrite.applied_filters,
        "dropped_filters": rewrite.dropped_filters,
        "fallback_reason": rewrite.fallback_reason,
        "validation_error": rewrite.validation_error,
        "latency_ms": rewrite.latency_ms,
        "input_tokens": rewrite.input_tokens,
        "output_tokens": rewrite.output_tokens,
    }


def rewrite_json(rewrite: Optional[RewriteResult]) -> str:
    return json.dumps(
        rewrite_trace_payload(rewrite),
        ensure_ascii=False,
    )


def final_context_rows(chunks: Sequence[RetrievedChunk]) -> list:
    return [
        {
            "chunk_id": chunk.chunk_id,
            **({"evidence_chunk_ids": list(chunk.evidence_chunk_ids)} if chunk.evidence_chunk_ids else {}),
            "document_version_id": chunk.document_version_id,
            "rank": chunk.fused_rank,
            "score": chunk.rerank_score,
        }
        for chunk in chunks
    ]


def effective_stage_latency(
    *,
    result: Optional[SearchResult],
    stage_latency: Optional[Mapping[str, float]],
    gateway_instance: Any,
) -> dict[str, float]:
    latency = dict(result.stage_latency) if result is not None else {}
    latency.update(stage_latency or {})
    # Multiple calls of one purpose belong to the same stage, not just the last call.
    gateway_latency = {}
    for audit in gateway_instance.audits if gateway_instance is not None else ():
        key = "gateway_{0}_ms".format(audit.purpose)
        gateway_latency[key] = gateway_latency.get(key, 0.0) + float(audit.latency_ms)
    latency.update(gateway_latency)
    return latency


_STAGE_PARENTS = {
    "bm25_ms": "retrieval_ms",
    "dense_ms": "retrieval_ms",
    "gateway_query_rewrite_ms": "rewrite_ms",
    "gateway_embedding_ms": "embedding_ms",
    "gateway_rerank_ms": "rerank_ms",
    "gateway_answer_ms": "generation_ms",
}


def total_stage_latency(latencies: Mapping[str, float]) -> float:
    """Sum disjoint measured stages; gateway/engine calls are nested spans."""
    return sum(
        max(0.0, value)
        for key, value in latencies.items()
        if math.isfinite(value)
        and latencies.get(_STAGE_PARENTS.get(key)) is None
    )
