import json

from sqlalchemy import select

import backend.app.api.v1.chats as chats_module
from backend.app.db.models import (
    IndexGenerationRecord,
    ModelCall,
    ModelProvider,
    TraceRecord,
)
from backend.app.rag.answer.service import (
    AnswerResult,
    answer_stream_from_pieces,
)
from backend.app.rag.domain.models import RetrievedChunk, SearchResult


def _setup_chat(api_client, admin_headers):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Provider Selection Team"},
        headers=admin_headers,
    ).json()["data"]
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Provider Selection KB"},
        headers=admin_headers,
    ).json()["data"]
    chat = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "knowledge_base_ids": [kb["id"]]},
        headers=admin_headers,
    ).json()["data"]
    return team, chat


def _create_provider(
    api_client,
    admin_headers,
    team_id,
    *,
    name="Selected Provider",
    base_url="http://provider.test/v1",
    model_ids=("model-a",),
):
    response = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team_id,
            "name": name,
            "provider_type": "openai_chat_completions",
            "base_url": base_url,
            "api_key": "sk-provider-secret",
            "model_ids": list(model_ids),
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _configure_external_policy(
    api_client,
    admin_headers,
    team_id,
    knowledge_base_id,
    provider_id,
    *,
    max_data_classification="internal",
):
    policy = api_client.post(
        "/api/v1/admin/model-policy/update",
        json={
            "mode": "external_allowed",
            "allowed_provider_ids": [provider_id],
            "max_data_classification": max_data_classification,
        },
        headers=admin_headers,
    )
    assert policy.status_code == 200, policy.text
    team_policy = api_client.post(
        "/api/v1/model-policy/update",
        json={
            "team_id": team_id,
            "mode": "external_allowed",
            "allowed_provider_ids": [provider_id],
            "max_data_classification": max_data_classification,
        },
        headers=admin_headers,
    )
    assert team_policy.status_code == 200, team_policy.text
    kb_policy = api_client.get(
        "/api/v1/kbs/policy",
        params={"team_id": team_id, "kb_id": knowledge_base_id},
        headers=admin_headers,
    ).json()["data"]
    updated = api_client.post(
        "/api/v1/kbs/policy/update",
        json={
            "team_id": team_id,
            "kb_id": knowledge_base_id,
            "mode": "external_allowed",
        },
        headers={
            **admin_headers,
            "If-Match": str(kb_policy["version"]),
        },
    )
    assert updated.status_code == 200, updated.text


def _select_provider(api_client, admin_headers, team_id, knowledge_base_id):
    provider = _create_provider(api_client, admin_headers, team_id)
    _configure_external_policy(
        api_client,
        admin_headers,
        team_id,
        knowledge_base_id,
        provider["id"],
    )
    return provider


def _add_generation(api_app, team_id):
    with api_app.state.session_factory() as session:
        session.add(IndexGenerationRecord(team_id=team_id, status="active"))
        session.commit()


def _stream_error_event(response):
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        if lines and lines[0] == "event: error":
            data_line = next(line for line in lines if line.startswith("data:"))
            return json.loads(data_line.removeprefix("data:").lstrip())
    raise AssertionError("stream response did not contain an error event")


class _FakeSelectedAdapter:
    def __init__(self, *, provider_id, model_id):
        self.provider_id = provider_id
        self.model_id = model_id
        self.route = "openai_chat_completions"

    def generate(self, *, question, chunks, max_chunks):
        selected = tuple(chunks[:max_chunks])
        return AnswerResult(
            text="provider answer [c1]",
            status="completed",
            citation_chunk_ids=tuple(chunk.chunk_id for chunk in selected),
            model_id=self.model_id,
            route=self.route,
            degraded=False,
        )

    def generate_stream(self, *, question, chunks, max_chunks):
        return answer_stream_from_pieces(
            ["provider ", "stream [c1]"],
            question=question,
            chunks=tuple(chunks[:max_chunks]),
            model_id=self.model_id,
            route=self.route,
        )


def _install_fake_chat_stack(monkeypatch):
    captured = {}

    def build_adapter(**kwargs):
        captured["adapter"] = kwargs
        return _FakeSelectedAdapter(
            provider_id=kwargs["provider_id"],
            model_id=kwargs["model_id"],
        )

    class Retriever:
        async def search(self, request):
            return SearchResult(
                chunks=[
                    RetrievedChunk(
                        chunk_id="chunk-1",
                        document_version_id="version-1",
                        content="Grounded evidence.",
                        fused_rank=1,
                        source_locator={"file_name": "evidence.md"},
                    )
                ],
                stage_latency={},
                degraded=False,
                trace_id="trace-provider-selection",
            )

    monkeypatch.setattr(chats_module, "build_provider_adapter", build_adapter)
    monkeypatch.setattr(
        chats_module.EmbeddingClient, "embed", lambda self, texts: [[0.1]]
    )
    monkeypatch.setattr(chats_module, "build_retriever", lambda *args: Retriever())
    monkeypatch.setattr(
        chats_module.RerankerClient,
        "rerank",
        lambda self, query, chunks, top_n: list(chunks),
    )
    return captured


def test_chat_ask_requires_provider_and_model(api_client, admin_headers):
    team, chat = _setup_chat(api_client, admin_headers)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Q?",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_chat_ask_rejects_model_not_configured_on_provider(
    api_client, admin_headers
):
    team, chat = _setup_chat(api_client, admin_headers)
    created = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team["id"],
            "name": "Selected Provider",
            "provider_type": "openai_chat_completions",
            "base_url": "http://provider.test/v1",
            "api_key": "sk-secret",
            "model_ids": ["model-a"],
        },
        headers=admin_headers,
    ).json()["data"]

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Q?",
            "provider_id": created["id"],
            "model_id": "model-b",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_chat_ask_rejects_disabled_provider(api_client, api_app, admin_headers):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = _create_provider(api_client, admin_headers, team["id"])
    _configure_external_policy(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
        provider["id"],
    )
    with api_app.state.session_factory() as session:
        stored = session.get(ModelProvider, provider["id"])
        assert stored is not None
        stored.status = "disabled"
        session.commit()

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Do not use a disabled provider.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert response.json()["error"]["message"] == "Provider is not active."


def test_chat_ask_rejects_provider_from_another_team(
    api_client, admin_headers
):
    team, chat = _setup_chat(api_client, admin_headers)
    other_team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Other Provider Team"},
        headers=admin_headers,
    ).json()["data"]
    provider = _create_provider(api_client, admin_headers, other_team["id"])
    _configure_external_policy(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
        provider["id"],
    )

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Do not use another team's provider.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert (
        response.json()["error"]["message"]
        == "Provider is not available to this team."
    )


def test_chat_ask_accepts_global_provider(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    created = api_client.post(
        "/api/v1/admin/providers/create",
        json={
            "name": "Global Provider",
            "provider_type": "openai_chat_completions",
            "base_url": "http://global-provider.test/v1",
            "api_key": "sk-global-secret",
            "model_ids": ["model-global"],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    provider = created.json()["data"]
    _configure_external_policy(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
        provider["id"],
    )
    _add_generation(api_app, team["id"])
    captured = _install_fake_chat_stack(monkeypatch)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Use the global provider.",
            "provider_id": provider["id"],
            "model_id": "model-global",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["content"] == "provider answer [c1]"
    assert captured["adapter"]["provider_id"] == provider["id"]
    assert captured["adapter"]["model_id"] == "model-global"
    assert "sk-global-secret" not in response.text


def test_chat_ask_maps_classification_denial_to_policy_denied(
    api_client, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = _create_provider(api_client, admin_headers, team["id"])
    _configure_external_policy(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
        provider["id"],
        max_data_classification="public",
    )
    captured = _install_fake_chat_stack(monkeypatch)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Do not send internal data externally.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "POLICY_DENIED"
    assert (
        response.json()["error"]["message"]
        == "External answer generation is forbidden by policy."
    )
    assert captured == {}


def test_provider_view_reports_key_presence_without_exposing_secret(
    api_client, admin_headers
):
    team, _ = _setup_chat(api_client, admin_headers)

    response = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team["id"],
            "name": "Secret Provider",
            "provider_type": "openai_responses",
            "base_url": "http://provider.test/v1",
            "api_key": "sk-plain-secret",
            "model_ids": ["model-a"],
        },
        headers=admin_headers,
    )

    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["has_api_key"] is True
    assert "api_key" not in data
    assert "api_key_encrypted" not in data
    assert "sk-plain-secret" not in response.text


def test_chat_ask_uses_selected_provider_for_non_stream_answer(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = _select_provider(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
    )
    _add_generation(api_app, team["id"])
    captured = _install_fake_chat_stack(monkeypatch)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Use the selected provider.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["content"] == "provider answer [c1]"
    assert captured["adapter"]["provider_type"] == "openai_chat_completions"
    assert captured["adapter"]["provider_id"] == provider["id"]
    assert captured["adapter"]["base_url"] == "http://provider.test/v1"
    assert captured["adapter"]["api_key"] == "sk-provider-secret"
    assert captured["adapter"]["model_id"] == "model-a"
    assert "sk-provider-secret" not in response.text

    with api_app.state.session_factory() as session:
        model_call = session.scalar(
            select(ModelCall).where(ModelCall.purpose == "answer")
        )
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.trace_id == "trace-provider-selection")
        )
        assert model_call is not None
        assert model_call.provider_id == provider["id"]
        assert model_call.model_id == "model-a"
        assert trace is not None
        model = json.loads(trace.model)
        assert model["provider_id"] == provider["id"]
        assert model["model_id"] == "model-a"
        assert "sk-provider-secret" not in trace.model


def test_chat_ask_uses_selected_provider_for_stream_answer(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = _select_provider(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
    )
    _add_generation(api_app, team["id"])
    captured = _install_fake_chat_stack(monkeypatch)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Stream from the selected provider.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert "event: delta" in response.text
    assert '"text": "provider "' in response.text
    assert "event: done" in response.text
    assert captured["adapter"]["provider_id"] == provider["id"]
    assert captured["adapter"]["api_key"] == "sk-provider-secret"
    assert "sk-provider-secret" not in response.text

    with api_app.state.session_factory() as session:
        model_call = session.scalar(
            select(ModelCall).where(ModelCall.purpose == "answer")
        )
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.trace_id == "trace-provider-selection")
        )
        assert model_call is not None
        assert model_call.provider_id == provider["id"]
        assert model_call.model_id == "model-a"
        assert trace is not None
        model = json.loads(trace.model)
        assert model["provider_id"] == provider["id"]
        assert model["model_id"] == "model-a"


def test_stream_rejects_malformed_provider_url_with_invalid_argument(
    api_client, api_app, admin_headers
):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = _create_provider(
        api_client,
        admin_headers,
        team["id"],
        base_url="not-a-valid-url",
    )
    _configure_external_policy(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
        provider["id"],
    )
    _add_generation(api_app, team["id"])

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Construct a broken adapter.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    error = _stream_error_event(response)
    assert error["code"] == "INVALID_ARGUMENT"
    assert error["retryable"] is False
    assert "sk-provider-secret" not in response.text
    with api_app.state.session_factory() as session:
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.error_code == "INVALID_ARGUMENT")
        )
        assert trace is not None
        model = json.loads(trace.model)
        assert model["provider_id"] == provider["id"]
        assert model["model_id"] == "model-a"


def test_stream_maps_corrupt_encrypted_key_to_model_unavailable(
    api_client, api_app, admin_headers
):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = _create_provider(api_client, admin_headers, team["id"])
    _configure_external_policy(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
        provider["id"],
    )
    with api_app.state.session_factory() as session:
        stored = session.get(ModelProvider, provider["id"])
        assert stored is not None
        stored.api_key_encrypted = "not-a-valid-fernet-token"
        session.commit()
    _add_generation(api_app, team["id"])

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Decrypt a corrupt provider key.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    error = _stream_error_event(response)
    assert error["code"] == "MODEL_UNAVAILABLE"
    assert error["retryable"] is False
    assert "not-a-valid-fernet-token" not in response.text
    with api_app.state.session_factory() as session:
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.error_code == "MODEL_UNAVAILABLE")
        )
        assert trace is not None
        model = json.loads(trace.model)
        assert model["provider_id"] == provider["id"]
        assert model["model_id"] == "model-a"


def test_chat_ask_maps_provider_policy_denial_to_policy_denied(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team["id"],
            "name": "Unapproved Provider",
            "provider_type": "openai_chat_completions",
            "base_url": "http://provider.test/v1",
            "api_key": "sk-provider-secret",
            "model_ids": ["model-a"],
        },
        headers=admin_headers,
    ).json()["data"]
    captured = _install_fake_chat_stack(monkeypatch)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Do not call this provider.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "POLICY_DENIED"
    assert captured == {}


def test_chat_ask_maps_missing_encrypted_key_to_model_unavailable(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = _select_provider(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
    )
    with api_app.state.session_factory() as session:
        stored = session.get(ModelProvider, provider["id"])
        assert stored is not None
        stored.api_key_encrypted = ""
        session.commit()
    captured = _install_fake_chat_stack(monkeypatch)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Credentials are missing.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"
    assert captured == {}


def test_chat_ask_maps_provider_execution_failure_to_model_unavailable(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = _select_provider(
        api_client,
        admin_headers,
        team["id"],
        chat["knowledge_base_ids"][0],
    )
    _add_generation(api_app, team["id"])
    _install_fake_chat_stack(monkeypatch)

    class FailingAdapter:
        route = "openai_chat_completions"

        def __init__(self, **kwargs):
            self.provider_id = kwargs["provider_id"]
            self.model_id = kwargs["model_id"]

        def generate(self, *, question, chunks, max_chunks):
            raise RuntimeError("upstream failed")

    monkeypatch.setattr(
        chats_module,
        "build_provider_adapter",
        lambda **kwargs: FailingAdapter(**kwargs),
    )

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Trigger an upstream failure.",
            "provider_id": provider["id"],
            "model_id": "model-a",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"
    with api_app.state.session_factory() as session:
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.error_code == "MODEL_UNAVAILABLE")
        )
        assert trace is not None
        model = json.loads(trace.model)
        assert model["provider_id"] == provider["id"]
        assert model["model_id"] == "model-a"
