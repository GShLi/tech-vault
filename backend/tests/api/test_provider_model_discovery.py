import pytest
from pydantic import SecretStr

import backend.app.api.v1.model_policy as model_policy_module
from backend.app.api.errors import ApiError
from backend.app.core.secrets import decrypt_secret
from backend.app.db.models import ModelProvider
from backend.app.modules.providers.discovery import ModelDiscoveryError


def _create_team(api_client, admin_headers):
    response = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Provider Discovery Team"},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_team_provider_stores_api_key_encrypted_and_returns_only_mask(
    api_client, api_app, admin_headers
):
    team = _create_team(api_client, admin_headers)

    response = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team["id"],
            "name": "OpenAI Gateway",
            "provider_type": "openai_chat_completions",
            "base_url": "https://gateway.example/v1/chat/completions",
            "api_key": "sk-secret-12345678",
            "model_ids": ["gpt-a"],
        },
        headers=admin_headers,
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["api_key_masked"] == "****5678"
    assert "api_key" not in data

    with api_app.state.session_factory() as session:
        provider = session.get(ModelProvider, data["id"])
        assert provider is not None
        assert provider.api_key_encrypted != "sk-secret-12345678"
        assert (
            decrypt_secret(
                provider.api_key_encrypted,
                api_app.state.settings,
            )
            == "sk-secret-12345678"
        )


def test_team_provider_model_discovery_uses_submitted_upstream_configuration(
    api_client, admin_headers, monkeypatch
):
    team = _create_team(api_client, admin_headers)
    captured = {}

    def discover_models(**kwargs):
        captured.update(kwargs)
        return ["model-a", "model-b"]

    monkeypatch.setattr(model_policy_module, "discover_models", discover_models)

    response = api_client.post(
        "/api/v1/providers/models",
        json={
            "team_id": team["id"],
            "provider_type": "anthropic_messages",
            "base_url": "https://api.anthropic.com/v1/messages",
            "api_key": "sk-ant-secret",
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["models"] == ["model-a", "model-b"]
    assert captured == {
        "provider_type": "anthropic_messages",
        "base_url": "https://api.anthropic.com/v1/messages",
        "api_key": "sk-ant-secret",
    }


def test_admin_provider_model_discovery_is_available_without_team_context(
    api_client, admin_headers, monkeypatch
):
    monkeypatch.setattr(
        model_policy_module,
        "discover_models",
        lambda **kwargs: ["admin-model"],
    )

    response = api_client.post(
        "/api/v1/admin/providers/models",
        json={
            "provider_type": "openai_responses",
            "base_url": "https://api.openai.com/v1/responses",
            "api_key": "sk-openai-secret",
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["models"] == ["admin-model"]


def test_provider_type_only_accepts_supported_upstream_formats(
    api_client, admin_headers
):
    team = _create_team(api_client, admin_headers)

    response = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team["id"],
            "name": "Invalid Format",
            "provider_type": "ollama",
            "base_url": "http://localhost:11434",
            "api_key": "secret",
            "model_ids": ["model-a"],
        },
        headers=admin_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_model_discovery_api_error_detaches_exception_chain(monkeypatch):
    def fail_discovery(**_kwargs):
        raise ModelDiscoveryError(
            502,
            "MODEL_LIST_UNAVAILABLE",
            "Upstream model list service is unavailable.",
        )

    monkeypatch.setattr(model_policy_module, "discover_models", fail_discovery)

    with pytest.raises(ApiError) as caught:
        model_policy_module._discover_provider_models(
            provider_type="openai_responses",
            base_url="https://gateway.example",
            api_key=SecretStr("sk-secret"),
        )

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
