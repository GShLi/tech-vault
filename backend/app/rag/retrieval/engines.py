"""Elasticsearch, Qdrant and dual-engine retrievers."""

from __future__ import annotations

import html
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from backend.app.rag.domain.models import (
    RetrievedChunk,
    SearchRequest,
    SearchResult,
)
from backend.app.rag.fusion.rrf import reciprocal_rank_fusion

from .filters import elasticsearch_bool_query, qdrant_filter


_HIGHLIGHT_TERM_RE = re.compile(r"<em>(.*?)</em>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _source(hit: Dict[str, Any]) -> Dict[str, Any]:
    return hit.get("_source", hit)


def _matched_terms(hit: Dict[str, Any]) -> tuple:
    fragments = hit.get("highlight", {}).get("content", [])
    terms = []
    seen = set()
    for fragment in fragments:
        if not isinstance(fragment, str):
            continue
        for raw_term in _HIGHLIGHT_TERM_RE.findall(fragment):
            term = html.unescape(_HTML_TAG_RE.sub("", raw_term)).strip()
            key = term.casefold()
            if term and key not in seen:
                seen.add(key)
                terms.append(term)
    return tuple(terms)


class _BaseEngine:
    def __init__(self, base_url: str, index_name: str = "") -> None:
        self._base = base_url.rstrip("/")
        self._index = index_name

    async def _request(self, method: str, path: str, **kwargs):
        async with httpx.AsyncClient(base_url=self._base, timeout=30.0) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

    @staticmethod
    def _result(
        chunks: List[RetrievedChunk],
        latency: Dict[str, float],
        degraded: bool,
        trace_id: Optional[str] = None,
    ) -> SearchResult:
        return SearchResult(
            chunks=chunks,
            stage_latency=latency,
            degraded=degraded,
            trace_id=trace_id or str(uuid.uuid4()),
        )

    @staticmethod
    def _to_retrieved(
        source: Dict[str, Any],
        rank: int,
        *,
        bm25_rank: Optional[int] = None,
        dense_rank: Optional[int] = None,
        matched_terms: tuple = (),
    ) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=source.get("chunk_id", ""),
            document_version_id=source.get("document_version_id", ""),
            content=source.get("content", ""),
            fused_rank=rank,
            bm25_rank=bm25_rank,
            dense_rank=dense_rank,
            matched_terms=matched_terms,
            source_locator=source.get("source_locator", {}),
        )


class ElasticsearchBM25Retriever(_BaseEngine):
    """Lexical retrieval used by the application-layer dual-engine path."""

    async def search(self, request: SearchRequest) -> SearchResult:
        started = time.perf_counter()
        body = {
            "size": request.bm25_top_k,
            "highlight": {
                "fields": {
                    "content": {
                        "number_of_fragments": 0,
                    }
                }
            },
            "query": {
                "bool": {
                    "must": [
                        elasticsearch_bool_query(request.filters),
                        {"match": {"content": request.rewritten_query or request.query}},
                    ]
                }
            },
        }
        response = await self._request("POST", "/" + self._index + "/_search", json=body)
        hits = response.json().get("hits", {}).get("hits", [])
        chunks = [
            self._to_retrieved(
                _source(hit),
                rank,
                bm25_rank=rank,
                matched_terms=_matched_terms(hit),
            )
            for rank, hit in enumerate(hits, start=1)
        ]
        latency = {"bm25_ms": (time.perf_counter() - started) * 1000.0}
        return self._result(chunks, latency, False)


class ElasticsearchHybridRetriever(_BaseEngine):
    """BM25 plus dense kNN fused with application-layer RRF."""

    async def search(self, request: SearchRequest) -> SearchResult:
        started = time.perf_counter()
        filters = elasticsearch_bool_query(request.filters)
        text = request.rewritten_query or request.query

        lexical = await self._request(
            "POST",
            "/" + self._index + "/_search",
            json={
                "size": request.bm25_top_k,
                "highlight": {
                    "fields": {
                        "content": {
                            "number_of_fragments": 0,
                        }
                    }
                },
                "query": {"bool": {"must": [filters, {"match": {"content": text}}]}},
            },
        )
        bm25_hits = lexical.json().get("hits", {}).get("hits", [])
        bm25_ids = [_source(hit).get("chunk_id", "") for hit in bm25_hits]
        bm25_terms = {
            _source(hit).get("chunk_id", ""): _matched_terms(hit)
            for hit in bm25_hits
        }

        dense_hits: List[Dict[str, Any]] = []
        if request.query_vector:
            knn = await self._request(
                "POST",
                "/" + self._index + "/_search",
                json={
                    "size": request.dense_top_k,
                    "knn": {
                        "field": "content_vector",
                        "query_vector": request.query_vector,
                        "k": request.dense_top_k,
                        "num_candidates": request.dense_top_k * 2,
                        "filter": filters,
                    },
                },
            )
            dense_hits = knn.json().get("hits", {}).get("hits", [])

        dense_ids = [_source(hit).get("chunk_id", "") for hit in dense_hits]
        fused = reciprocal_rank_fusion(bm25_ids, dense_ids, k=request.rrf_k)
        sources: Dict[str, Dict[str, Any]] = {}
        for hit in bm25_hits + dense_hits:
            source = _source(hit)
            sources.setdefault(source.get("chunk_id", ""), source)

        bm25_rank = {chunk_id: rank for rank, chunk_id in enumerate(bm25_ids, start=1)}
        dense_rank = {chunk_id: rank for rank, chunk_id in enumerate(dense_ids, start=1)}
        rrf_candidates = [
            self._to_retrieved(
                sources.get(candidate.chunk_id, {}),
                candidate.fused_rank,
                bm25_rank=bm25_rank.get(candidate.chunk_id),
                dense_rank=dense_rank.get(candidate.chunk_id),
                matched_terms=bm25_terms.get(candidate.chunk_id, ()),
            )
            for candidate in fused[: request.rerank_input_size]
        ]
        chunks = list(rrf_candidates[: request.final_top_n])

        latency = {"retrieval_ms": (time.perf_counter() - started) * 1000.0}
        result = self._result(chunks, latency, False)
        return SearchResult(
            chunks=result.chunks,
            stage_latency=result.stage_latency,
            degraded=result.degraded,
            trace_id=result.trace_id,
            bm25_candidates=tuple(
                self._to_retrieved(
                    _source(hit),
                    rank,
                    bm25_rank=rank,
                    matched_terms=_matched_terms(hit),
                )
                for rank, hit in enumerate(bm25_hits, start=1)
            ),
            dense_candidates=tuple(
                self._to_retrieved(_source(hit), rank, dense_rank=rank)
                for rank, hit in enumerate(dense_hits, start=1)
            ),
            rrf_candidates=tuple(rrf_candidates),
        )


class QdrantDenseRetriever(_BaseEngine):
    """Dense retrieval against a Qdrant collection."""

    def __init__(self, base_url: str, collection_name: str) -> None:
        super().__init__(base_url)
        self._collection = collection_name

    async def search(self, request: SearchRequest) -> SearchResult:
        started = time.perf_counter()
        if not request.query_vector:
            return self._result([], {"dense_ms": 0.0}, True)

        response = await self._request(
            "POST",
            "/collections/{0}/points/search".format(self._collection),
            json={
                "vector": request.query_vector,
                "limit": request.dense_top_k,
                "filter": qdrant_filter(request.filters),
                "with_payload": True,
            },
        )
        points = response.json().get("result", [])
        chunks = [
            self._to_retrieved(point.get("payload", {}), rank, dense_rank=rank)
            for rank, point in enumerate(points, start=1)
        ]
        latency = {"dense_ms": (time.perf_counter() - started) * 1000.0}
        return self._result(chunks, latency, False)


class DualEngineRetriever:
    """ES BM25 plus Qdrant Dense, fused in the application layer."""

    def __init__(self, lexical: Any, dense: Any) -> None:
        self._lexical = lexical
        self._dense = dense

    async def search(self, request: SearchRequest) -> SearchResult:
        started = time.perf_counter()
        lexical = await self._lexical.search(request)

        try:
            dense = await self._dense.search(request)
        except Exception:
            return self._degraded(lexical, started)

        if dense.degraded and not dense.chunks:
            return self._degraded(lexical, started)

        bm25_ids = [chunk.chunk_id for chunk in lexical.chunks]
        dense_ids = [chunk.chunk_id for chunk in dense.chunks]
        fused = reciprocal_rank_fusion(bm25_ids, dense_ids, k=request.rrf_k)
        sources: Dict[str, RetrievedChunk] = {
            chunk.chunk_id: chunk for chunk in lexical.chunks + dense.chunks
        }
        bm25_rank = {chunk.chunk_id: chunk.bm25_rank for chunk in lexical.chunks}
        dense_rank = {chunk.chunk_id: chunk.dense_rank for chunk in dense.chunks}

        rrf_candidates = [
            RetrievedChunk(
                chunk_id=candidate.chunk_id,
                document_version_id=sources[candidate.chunk_id].document_version_id,
                content=sources[candidate.chunk_id].content,
                fused_rank=candidate.fused_rank,
                bm25_rank=bm25_rank.get(candidate.chunk_id),
                dense_rank=dense_rank.get(candidate.chunk_id),
                source_locator=sources[candidate.chunk_id].source_locator,
            )
            for candidate in fused[: request.rerank_input_size]
            if candidate.chunk_id in sources
        ]
        chunks = list(rrf_candidates[: request.final_top_n])

        latency = {
            **lexical.stage_latency,
            **dense.stage_latency,
            "retrieval_ms": (time.perf_counter() - started) * 1000.0,
        }
        return SearchResult(
            chunks=chunks,
            stage_latency=latency,
            degraded=dense.degraded,
            trace_id=lexical.trace_id,
            bm25_candidates=tuple(lexical.chunks),
            dense_candidates=tuple(dense.chunks),
            rrf_candidates=tuple(rrf_candidates),
        )

    @staticmethod
    def _degraded(lexical: SearchResult, started: float) -> SearchResult:
        return SearchResult(
            chunks=lexical.chunks,
            stage_latency={
                **lexical.stage_latency,
                "retrieval_ms": (time.perf_counter() - started) * 1000.0,
            },
            degraded=True,
            trace_id=lexical.trace_id,
            bm25_candidates=tuple(lexical.chunks),
            rrf_candidates=tuple(lexical.chunks),
        )
