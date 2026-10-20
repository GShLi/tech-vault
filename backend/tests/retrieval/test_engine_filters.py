from dataclasses import replace

from backend.app.rag.domain.models import RetrievalFilters
from backend.app.rag.retrieval.filters import (
    elasticsearch_bool_query,
    qdrant_filter,
)


def _filters() -> RetrievalFilters:
    return RetrievalFilters(
        team_id="team-a",
        knowledge_base_ids=("kb-a",),
        viewer_user_id="user-a",
        product="spring-boot",
        version_values=("3.2",),
        explicit_document_grants=("doc-grant",),
    )


def test_elasticsearch_filter_is_default_deny_and_scope_bound():
    query = elasticsearch_bool_query(_filters())
    text = str(query)

    assert "team-a" in text
    assert "kb-a" in text
    assert "doc_status" in text
    assert "chunk_status" in text
    assert "doc-grant" in text
    assert "visibility" in text


def test_qdrant_filter_carries_the_same_authorization_scope():
    query = qdrant_filter(_filters())
    text = str(query)

    assert "team-a" in text
    assert "kb-a" in text
    assert "doc_status" in text
    assert "chunk_status" in text
    assert "doc-grant" in text
    assert "visibility" in text


def test_product_filter_is_exact_in_both_engines():
    elastic = elasticsearch_bool_query(_filters())
    qdrant = qdrant_filter(_filters())

    assert {"term": {"product": "spring-boot"}} in elastic["bool"]["must"]
    assert "must_not" not in str(elastic)
    assert {"key": "product", "match": {"value": "spring-boot"}} in qdrant["must"]


def test_none_product_does_not_add_product_filter_to_either_engine():
    filters = replace(_filters(), product=None)

    elastic = elasticsearch_bool_query(filters)
    qdrant = qdrant_filter(filters)

    assert "product" not in str(elastic)
    assert not any(condition.get("key") == "product" for condition in qdrant["must"])
