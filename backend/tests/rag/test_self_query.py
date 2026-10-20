from backend.app.rag.llm_gateway.self_query import apply_self_query_filters


def test_self_query_canonicalizes_facet_values():
    result = apply_self_query_filters(
        extracted_filters={
            "product": " Spring Boot ",
            "version_values": ["3.2", "3.2"],
        },
        explicit_product=None,
        explicit_versions=(),
        allowed_products=("spring-boot",),
        allowed_versions=("3.2",),
    )

    assert result.applied_filters == {
        "product": "spring-boot",
        "version_values": ["3.2"],
    }
    assert result.dropped_filters == []


def test_self_query_keeps_user_values_and_drops_llm_conflicts():
    result = apply_self_query_filters(
        extracted_filters={
            "product": "elasticsearch",
            "version_values": ["8.13"],
        },
        explicit_product="spring-boot",
        explicit_versions=("3.2",),
        allowed_products=("spring-boot", "elasticsearch"),
        allowed_versions=("3.2", "8.13"),
    )

    assert result.applied_filters == {
        "product": "spring-boot",
        "version_values": ["3.2"],
    }
    assert {item["reason"] for item in result.dropped_filters} == {
        "user_override"
    }


def test_self_query_drops_unknown_values():
    result = apply_self_query_filters(
        extracted_filters={
            "product": "unknown",
            "version_values": ["9.9", "3.2"],
        },
        explicit_product=None,
        explicit_versions=(),
        allowed_products=("spring-boot",),
        allowed_versions=("3.2",),
    )

    assert result.applied_filters == {
        "product": None,
        "version_values": ["3.2"],
    }
    assert {item["value"] for item in result.dropped_filters} == {
        "unknown",
        "9.9",
    }
