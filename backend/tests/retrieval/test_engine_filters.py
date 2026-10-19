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
