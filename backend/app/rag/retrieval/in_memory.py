from __future__ import annotations

import math
import re
import time
import uuid
from collections import Counter
from typing import Dict, Iterable, List, Sequence, Set

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

        if filters.product and chunk.product and chunk.product != filters.product:
            return False
        if filters.version_values and chunk.version_values:
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

        ranked = []
        for chunk in visible:
            lexical = self._lexical_score(query, chunk.content)
            dense = _cosine(request.query_vector, self._embedding.get(chunk.chunk_id, ()))
            score = 0.65 * lexical + 0.35 * dense
            if score > 0:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1].chunk_id))

        result_chunks = [
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_version_id=chunk.document_version_id,
                content=chunk.content,
                fused_rank=index,
                bm25_rank=index if self._lexical_score(query, chunk.content) > 0 else None,
                dense_rank=index if self._embedding.get(chunk.chunk_id) else None,
                source_locator=dict(chunk.source_locator),
            )
            for index, (_, chunk) in enumerate(ranked[: request.final_top_n], start=1)
        ]

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return SearchResult(
            chunks=result_chunks,
            stage_latency={"retrieval_ms": elapsed_ms},
            degraded=False,
            trace_id=str(uuid.uuid4()),
        )

