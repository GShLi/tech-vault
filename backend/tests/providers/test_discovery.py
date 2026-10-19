import httpx
import pytest

from backend.app.modules.providers.discovery import (
    ModelDiscoveryError,
    discover_models,
    normalize_model_list_url,
)


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://api.openai.com", "https://api.openai.com/v1/models"),
        ("https://api.openai.com/v1", "https://api.openai.com/v1/models"),
        (
            "https://api.openai.com/v1/responses",
            "https://api.openai.com/v1/models",
        ),
        (
            "https://api.openai.com/v1/chat/completions",
            "https://api.openai.com/v1/models",
        ),
        (
            "https://api.anthropic.com/v1/messages",
            "https://api.anthropic.com/v1/models",
        ),
    ],
)
def test_normalize_model_list_url(base_url, expected):
    assert normalize_model_list_url(base_url) == expected


def test_openai_model_discovery_uses_bearer_auth_and_reads_data_ids():
    def handler(request):
        assert str(request.url) == "https://gateway.example/v1/models"
        assert request.headers["authorization"] == "Bearer sk-openai-test"
        return httpx.Response(
            200,
            json={"data": [{"id": "gpt-a"}, {"id": "gpt-b"}, {"id": "gpt-a"}]},
        )

    models = discover_models(
        provider_type="openai_chat_completions",
        base_url="https://gateway.example/v1",
        api_key="sk-openai-test",
        transport=httpx.MockTransport(handler),
    )

    assert models == ["gpt-a", "gpt-b"]


def test_anthropic_model_discovery_uses_anthropic_headers_and_pagination():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        assert request.headers["x-api-key"] == "sk-ant-test"
        assert request.headers["anthropic-version"] == "2023-06-01"
        if "after_id" in str(request.url):
            return httpx.Response(
                200,
                json={"data": [{"id": "claude-b"}], "has_more": False},
            )
        return httpx.Response(
            200,
            json={
                "data": [{"id": "claude-a"}],
                "has_more": True,
                "last_id": "claude-a",
            },
        )

    models = discover_models(
        provider_type="anthropic_messages",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test",
        transport=httpx.MockTransport(handler),
    )

    assert models == ["claude-a", "claude-b"]
    assert len(calls) == 2
    assert "after_id=claude-a" in calls[1]


def test_model_discovery_reports_authentication_failure():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": {"message": "bad key"}})
    )

    with pytest.raises(ModelDiscoveryError) as caught:
        discover_models(
            provider_type="openai_responses",
            base_url="https://gateway.example",
            api_key="bad-key",
            transport=transport,
        )

    assert caught.value.status_code == 400
    assert caught.value.code == "MODEL_LIST_AUTH_FAILED"
