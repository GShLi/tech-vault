from __future__ import annotations

import re
from dataclasses import replace
from typing import List, Optional, Sequence

import httpx

from backend.app.rag.domain.models import RetrievedChunk


_TOKEN_RE = re.compile(r"[A-Za-z0-9_.:/#-]+|[\u4e00-\u9fff]")


def _tokens(value: str) -> set:
    return {token.lower() for token in _TOKEN_RE.findall(value)}


def lexical_relevance_score(query: str, document: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    document_tokens = _tokens(document)
    overlap = len(query_tokens.intersection(document_tokens)) / len(query_tokens)
    exact_bonus = 0.25 if query.lower() in document.lower() else 0.0
    return overlap + exact_bonus


class RerankerClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def score(self, query: str, documents: Sequence[str]) -> List[float]:
        if not documents:
            return []
        try:
            with httpx.Client(
                base_url=self._base,
                timeout=self._timeout,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post(
                    "/rerank",
                    json={"query": query, "documents": list(documents)},
                )
                response.raise_for_status()
                scores = response.json()["scores"]
                if len(scores) == len(documents):
                    return [float(score) for score in scores]
        except Exception:
            pass
        return [
            lexical_relevance_score(query, document) for document in documents
        ]

    def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        top_n: int,
    ) -> List[RetrievedChunk]:
        rows = list(chunks)
        scores = self.score(query, [chunk.content for chunk in rows])
        order = sorted(
            range(len(rows)),
            key=lambda index: (-scores[index], rows[index].fused_rank, index),
        )[:top_n]
        return [
            replace(rows[index], fused_rank=rank, rerank_score=scores[index])
            for rank, index in enumerate(order, start=1)
        ]
