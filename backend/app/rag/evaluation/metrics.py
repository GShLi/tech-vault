from __future__ import annotations

import math
from collections.abc import Mapping as MappingABC
from typing import Collection, List, Mapping, Sequence, Set, Union


def _unique_in_order(chunk_ids: Sequence[str]) -> List[str]:
    seen: Set[str] = set()
    unique: List[str] = []
    for chunk_id in chunk_ids:
        if chunk_id not in seen:
            seen.add(chunk_id)
            unique.append(chunk_id)
    return unique


def recall_at_k(
    ranked_chunk_ids: Sequence[str],
    relevant_chunk_ids: Collection[str],
    k: int,
) -> float:
    """Return the fraction of relevant chunks found in the first k results."""
    relevant = set(relevant_chunk_ids)
    if k <= 0 or not relevant:
        return 0.0
    retrieved = set(_unique_in_order(ranked_chunk_ids)[:k])
    return float(len(retrieved.intersection(relevant))) / float(len(relevant))


def mrr(
    ranked_chunk_ids: Sequence[str],
    relevant_chunk_ids: Collection[str],
) -> float:
    """Return the reciprocal rank of the first relevant retrieval result."""
    relevant = set(relevant_chunk_ids)
    if not relevant:
        return 0.0
    for rank, chunk_id in enumerate(_unique_in_order(ranked_chunk_ids), start=1):
        if chunk_id in relevant:
            return 1.0 / float(rank)
    return 0.0


def ndcg_at_k(
    ranked_chunk_ids: Sequence[str],
    relevance: Union[Mapping[str, float], Collection[str]],
    k: int,
) -> float:
    """Return nDCG@k using graded relevance or binary set membership."""
    if k <= 0:
        return 0.0

    if isinstance(relevance, MappingABC):
        gains = {
            chunk_id: max(float(gain), 0.0)
            for chunk_id, gain in relevance.items()
        }
    else:
        gains = {chunk_id: 1.0 for chunk_id in set(relevance)}

    ideal_gains = sorted(
        (gain for gain in gains.values() if gain > 0.0),
        reverse=True,
    )[:k]
    if not ideal_gains:
        return 0.0

    ranked = _unique_in_order(ranked_chunk_ids)[:k]
    dcg = sum(
        gains.get(chunk_id, 0.0) / math.log2(rank + 1.0)
        for rank, chunk_id in enumerate(ranked, start=1)
    )
    idcg = sum(
        gain / math.log2(rank + 1.0)
        for rank, gain in enumerate(ideal_gains, start=1)
    )
    return dcg / idcg
