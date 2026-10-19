"""Factories that bind retrieval and indexing adapters to runtime settings."""

from __future__ import annotations

from typing import List

from backend.app.core.config import Settings
from backend.app.rag.indexing.elasticsearch import (
    ElasticsearchIndexWriter,
    index_name_for_generation,
)
from backend.app.rag.indexing.qdrant import (
    QdrantIndexWriter,
    collection_name_for_generation,
)

from .config import EngineMode
from .engines import (
    DualEngineRetriever,
    ElasticsearchBM25Retriever,
    ElasticsearchHybridRetriever,
    QdrantDenseRetriever,
)


def build_retriever(
    settings: Settings,
    generation_id: str,
    mode: EngineMode = EngineMode.DUAL_ENGINE,
):
    """Build the configured retriever. Engine selection is backend-owned."""
    if mode is EngineMode.ELASTIC_SINGLE:
        return ElasticsearchHybridRetriever(
            settings.es_url,
            index_name_for_generation(generation_id),
        )

    return DualEngineRetriever(
        ElasticsearchBM25Retriever(
            settings.es_url,
            index_name_for_generation(generation_id),
        ),
        QdrantDenseRetriever(
            settings.qdrant_url,
            collection_name_for_generation(generation_id),
        ),
    )


def build_index_writers(
    settings: Settings,
    mode: EngineMode = EngineMode.DUAL_ENGINE,
) -> List[object]:
    """Build the writers that must receive the same staged chunks."""
    writers: List[object] = [ElasticsearchIndexWriter(settings.es_url)]
    if mode is EngineMode.DUAL_ENGINE:
        writers.append(QdrantIndexWriter(settings.qdrant_url))
    return writers
