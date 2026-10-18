from backend.app.rag.domain.models import RetrievalFilters, SearchRequest


def test_search_request_defaults_are_stable():
    request = SearchRequest(
        query="Spring Boot 3.2 virtual threads",
        rewritten_query=None,
        query_vector=[0.1, 0.2],
        filters=RetrievalFilters(
            team_id="team-a",
            knowledge_base_ids=("kb-a",),
            viewer_user_id="user-a",
        ),
    )

    assert request.bm25_top_k == 50
    assert request.dense_top_k == 50
    assert request.rrf_k == 60
    assert request.final_top_n == 10
    assert request.engine_mode == "dual_engine"

