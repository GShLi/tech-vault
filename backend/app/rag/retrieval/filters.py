"""Shared authorization filter builders for retrieval engines.

Filters must be applied at recall time in both Elasticsearch and Qdrant,
never as a post-filter in the application layer.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.app.rag.domain.models import RetrievalFilters


def _value(field) -> str:
    return field.value if hasattr(field, "value") else str(field)


def base_conditions(filters: RetrievalFilters) -> Dict[str, Any]:
    """Authorization and status conditions shared by every engine."""
    visibility_should: List[Dict[str, Any]] = [
        {"term": {"visibility": "team_shared"}},
        {"term": {"owner_user_id": filters.viewer_user_id}},
    ]
    for grant in filters.explicit_document_grants:
        visibility_should.append({"term": {"document_id": grant}})

    return {
        "team_id": filters.team_id,
        "knowledge_base_ids": list(filters.knowledge_base_ids),
        "visibility_should": visibility_should,
        "product": filters.product,
        "version_values": list(filters.version_values),
    }


def elasticsearch_bool_query(filters: RetrievalFilters) -> Dict[str, Any]:
    """Elasticsearch bool query with authorization filters."""
    conditions = base_conditions(filters)
    must: List[Dict[str, Any]] = [
        {"term": {"team_id": conditions["team_id"]}},
        {"terms": {"knowledge_base_id": conditions["knowledge_base_ids"]}},
        {"term": {"doc_status": "active"}},
        {"term": {"chunk_status": "enabled"}},
        {"bool": {"should": conditions["visibility_should"], "minimum_should_match": 1}},
    ]
    if conditions["product"]:
        must.append({"term": {"product": conditions["product"]}})
    if conditions["version_values"]:
        must.append(
            {"terms": {"version_values": conditions["version_values"]}}
        )
    return {"bool": {"must": must}}


def qdrant_filter(filters: RetrievalFilters) -> Dict[str, Any]:
    """Qdrant filter with the same authorization semantics."""
    conditions = base_conditions(filters)
    must: List[Dict[str, Any]] = [
        {"key": "team_id", "match": {"value": conditions["team_id"]}},
        {"key": "knowledge_base_id", "match": {"any": conditions["knowledge_base_ids"]}},
        {"key": "doc_status", "match": {"value": "active"}},
        {"key": "chunk_status", "match": {"value": "enabled"}},
    ]
    if conditions["product"]:
        must.append({"key": "product", "match": {"value": conditions["product"]}})
    if conditions["version_values"]:
        must.append(
            {
                "key": "version_values",
                "match": {"any": conditions["version_values"]},
            }
        )
    return {
        "must": must,
        "should": conditions_to_qdrant_should(filters),
    }


def conditions_to_qdrant_should(filters: RetrievalFilters) -> List[Dict[str, Any]]:
    should: List[Dict[str, Any]] = [
        {"key": "visibility", "match": {"value": "team_shared"}},
        {"key": "owner_user_id", "match": {"value": filters.viewer_user_id}},
    ]
    for grant in filters.explicit_document_grants:
        should.append({"key": "document_id", "match": {"value": grant}})
    return should
