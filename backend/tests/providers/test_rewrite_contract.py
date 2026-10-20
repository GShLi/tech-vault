import pytest

from backend.app.rag.llm_gateway.rewrite_contract import (
    REWRITE_SYSTEM_PROMPT,
    RewriteValidationError,
    build_rewrite_prompt,
    parse_rewrite_payload,
    parse_rewrite_text,
)


def test_rewrite_prompt_resolves_primary_entity_before_secondary_aliases():
    assert "primary entity" in REWRITE_SYSTEM_PROMPT
    assert "Secondary aliases" in REWRITE_SYSTEM_PROMPT


def test_parse_rewrite_payload_normalizes_query_and_filters():
    parsed = parse_rewrite_payload(
        {
            "rewritten_query": "  Spring   Boot 3.2 虚拟线程配置  ",
            "filters": {
                "product": " spring-boot ",
                "version_values": ["3.2", "3.2"],
            },
        }
    )

    assert parsed.rewritten_query == "Spring Boot 3.2 虚拟线程配置"
    assert parsed.extracted_filters == {
        "product": "spring-boot",
        "version_values": ["3.2"],
    }


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            {"rewritten_query": "q", "filters": {}, "extra": 1},
            "unexpected_field",
        ),
        (
            {"rewritten_query": "q", "filters": {"product": None}},
            "missing_field",
        ),
        (
            {
                "rewritten_query": "q",
                "filters": {"product": None, "version_values": [1]},
            },
            "invalid_filter_type",
        ),
    ],
)
def test_parse_rewrite_payload_rejects_invalid_shapes(payload, code):
    with pytest.raises(RewriteValidationError) as error:
        parse_rewrite_payload(payload)

    assert error.value.code == code


def test_parse_rewrite_text_rejects_markdown_and_invalid_json():
    markdown_payload = (
        '```json\n{"rewritten_query":"q","filters":'
        '{"product":null,"version_values":[]}}\n```'
    )
    with pytest.raises(RewriteValidationError) as markdown:
        parse_rewrite_text(markdown_payload)
    assert markdown.value.code == "markdown_not_allowed"

    with pytest.raises(RewriteValidationError) as invalid:
        parse_rewrite_text("not json")
    assert invalid.value.code == "invalid_json"


def test_build_rewrite_prompt_keeps_roles_and_limits_history():
    history = tuple(
        {"role": "user", "content": "m{0}".format(index)}
        for index in range(8)
    )
    system_prompt, user_prompt = build_rewrite_prompt(
        question="它怎么开启？",
        history=history,
        product=None,
        version_values=(),
        allowed_products=("spring-boot",),
        allowed_versions=("3.2",),
    )

    assert "technical knowledge base retrieval system" in system_prompt
    assert "user: m2" in user_prompt
    assert "user: m7" in user_prompt
    assert "m0" not in user_prompt
    assert "allowed_products" not in user_prompt.lower()
    assert "spring-boot" in user_prompt
    assert "3.2" in user_prompt
