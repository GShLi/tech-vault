from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from backend.app.rag.domain.models import SearchRequest, SearchResult
from backend.app.rag.domain.ports import Retriever

from .config import EngineMode, RetrievalConfig


class RetrievalRouter:
    """Select a retriever from backend configuration, never from a user request."""

    def __init__(
        self,
        retrievers: Mapping[EngineMode, Retriever],
        config: RetrievalConfig,
    ) -> None:
        self._retrievers = dict(retrievers)
        self._config = config

    async def search(self, request: SearchRequest) -> SearchResult:
        try:
            retriever = self._retrievers[self._config.engine_mode]
        except KeyError as error:
            raise RuntimeError(
                "retriever is not configured for engine mode: {0}".format(
                    self._config.engine_mode.value
                )
            ) from error
        effective_request = replace(
            request,
            bm25_top_k=self._config.bm25_top_k,
            dense_top_k=self._config.dense_top_k,
            rrf_k=self._config.rrf_k,
            rerank_input_size=self._config.rerank_input_size,
            final_top_n=self._config.final_top_n,
        )
        return await retriever.search(effective_request)

