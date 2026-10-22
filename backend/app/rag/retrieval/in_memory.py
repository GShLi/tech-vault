from __future__ import annotations

import math
import re
import time
import uuid
from collections import Counter
from typing import Dict, Iterable, List, Sequence

from backend.app.rag.domain.models import (
    Chunk,
    ChunkStatus,
    DocumentStatus,
    RetrievalFilters,
    RetrievedChunk,
    SearchRequest,
    SearchResult,
    Visibility,
)
from backend.app.rag.fusion.rrf import reciprocal_rank_fusion


_TOKEN_RE = re.compile(r"[A-Za-z0-9_.:/#-]+|[\u4e00-\u9fff]+")


def _tokens(text: str) -> List[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


class InMemoryRetriever:
    """A deterministic retriever for tests and local vertical-slice checks.

    It intentionally implements both lexical and vector scoring in-process.
    Production ES and Qdrant adapters must enforce the same filter semantics.
    """

    def __init__(self, chunks: Iterable[Chunk], embedding: Dict[str, Sequence[float]] = None):
        self._chunks = list(chunks)
        self._embedding = dict(embedding or {})

    def _is_visible(self, chunk: Chunk, filters: RetrievalFilters) -> bool:
        if chunk.chunk_level != "child":
            return False
        if chunk.team_id != filters.team_id:
            return False
        if chunk.knowledge_base_id not in filters.knowledge_base_ids:
            return False
        if chunk.doc_status != DocumentStatus.ACTIVE:
            return False
        if chunk.chunk_status != ChunkStatus.ENABLED:
            return False

        if chunk.visibility == Visibility.PRIVATE:
            return (
                filters.include_private_owned_by_viewer
                and chunk.owner_user_id == filters.viewer_user_id
            ) or chunk.document_id in filters.explicit_document_grants

        if chunk.visibility != Visibility.TEAM_SHARED:
            return False

        if filters.product and chunk.product != filters.product:
            return False
        if filters.version_values:
            if not chunk.version_values:
                return False
            if not set(filters.version_values).intersection(chunk.version_values):
                return False
        return True

    @staticmethod
    def _lexical_score(query: str, content: str) -> float:
        query_terms = Counter(_tokens(query))
        content_terms = Counter(_tokens(content))
        if not query_terms or not content_terms:
            return 0.0
        overlap = sum(min(count, content_terms[term]) for term, count in query_terms.items())
        return float(overlap) / float(sum(query_terms.values()))

    async def search(self, request: SearchRequest) -> SearchResult:
        started = time.perf_counter()
        query = request.rewritten_query or request.query
        visible = [chunk for chunk in self._chunks if self._is_visible(chunk, request.filters)]

        bm25_scored = [
            (self._lexical_score(query, chunk.content), chunk.chunk_id)
            for chunk in visible
        ]
        bm25_ids = [
            chunk_id
            for _, chunk_id in sorted(
                (item for item in bm25_scored if item[0] > 0.0),
                key=lambda item: (-item[0], item[1]),
            )[: request.bm25_top_k]
        ]
        bm25_scores = dict(bm25_scored)

        dense_scored = [
            (_cosine(request.query_vector, self._embedding.get(chunk.chunk_id, ())), chunk.chunk_id)
            for chunk in visible
        ]
        dense_ids = [
            chunk_id
            for _, chunk_id in sorted(
                (item for item in dense_scored if item[0] > 0.0),
                key=lambda item: (-item[0], item[1]),
            )[: request.dense_top_k]
        ]
        dense_scores = dict(dense_scored)

        by_id = {chunk.chunk_id: chunk for chunk in visible}
        fused = reciprocal_rank_fusion(bm25_ids, dense_ids, k=request.rrf_k)
        result_chunks = [
            RetrievedChunk(
                chunk_id=candidate.chunk_id,
                document_version_id=by_id[candidate.chunk_id].document_version_id,
                content=by_id[candidate.chunk_id].content,
                fused_rank=candidate.fused_rank,
                bm25_rank=candidate.bm25_rank,
                dense_rank=candidate.dense_rank,
                bm25_score=bm25_scores.get(candidate.chunk_id),
                dense_score=dense_scores.get(candidate.chunk_id),
                rrf_score=candidate.fused_score,
                source_locator=dict(by_id[candidate.chunk_id].source_locator),
                parent_chunk_id=by_id[candidate.chunk_id].parent_chunk_id,
                index_generation=by_id[candidate.chunk_id].index_generation,
            )
            for candidate in fused[: request.final_top_n]
        ]
        bm25_candidates = tuple(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_version_id=by_id[chunk_id].document_version_id,
                content=by_id[chunk_id].content,
                fused_rank=rank,
                bm25_rank=rank,
                bm25_score=bm25_scores.get(chunk_id),
                source_locator=dict(by_id[chunk_id].source_locator),
                parent_chunk_id=by_id[chunk_id].parent_chunk_id,
                index_generation=by_id[chunk_id].index_generation,
            )
            for rank, chunk_id in enumerate(bm25_ids, start=1)
        )
        dense_candidates = tuple(
            RetrievedChunk(
                chunk_id=chunk_id,
                document_version_id=by_id[chunk_id].document_version_id,
                content=by_id[chunk_id].content,
                fused_rank=rank,
                dense_rank=rank,
                dense_score=dense_scores.get(chunk_id),
                source_locator=dict(by_id[chunk_id].source_locator),
                parent_chunk_id=by_id[chunk_id].parent_chunk_id,
                index_generation=by_id[chunk_id].index_generation,
            )
            for rank, chunk_id in enumerate(dense_ids, start=1)
        )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return SearchResult(
            chunks=result_chunks,
            stage_latency={"retrieval_ms": elapsed_ms},
            degraded=False,
            trace_id=str(uuid.uuid4()),
            bm25_candidates=bm25_candidates,
            dense_candidates=dense_candidates,
            rrf_candidates=tuple(result_chunks),
        )

