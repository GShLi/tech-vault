from __future__ import annotations

from typing import Dict, List, Sequence

from backend.app.rag.domain.models import FusedCandidate


def reciprocal_rank_fusion(
    bm25_ids: Sequence[str],
    dense_ids: Sequence[str],
    k: int = 60,
    bm25_weight: float = 1.0,
    dense_weight: float = 1.0,
) -> List[FusedCandidate]:
    """Fuse ordered retrieval results using weighted reciprocal rank fusion."""
    if k < 0:
        raise ValueError("k must be non-negative")
    if bm25_weight < 0 or dense_weight < 0:
        raise ValueError("RRF weights must be non-negative")

    scores: Dict[str, float] = {}
    bm25_ranks: Dict[str, int] = {}
    dense_ranks: Dict[str, int] = {}

    for rank, chunk_id in enumerate(bm25_ids, start=1):
        if chunk_id in bm25_ranks:
            continue
        bm25_ranks[chunk_id] = rank
        scores[chunk_id] = scores.get(chunk_id, 0.0) + bm25_weight / (k + rank)

    for rank, chunk_id in enumerate(dense_ids, start=1):
        if chunk_id in dense_ranks:
            continue
        dense_ranks[chunk_id] = rank
        scores[chunk_id] = scores.get(chunk_id, 0.0) + dense_weight / (k + rank)

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        FusedCandidate(
            chunk_id=chunk_id,
            fused_score=score,
            fused_rank=fused_rank,
            bm25_rank=bm25_ranks.get(chunk_id),
            dense_rank=dense_ranks.get(chunk_id),
        )
        for fused_rank, (chunk_id, score) in enumerate(ordered, start=1)
    ]
