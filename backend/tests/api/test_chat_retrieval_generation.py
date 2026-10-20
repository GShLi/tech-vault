import asyncio
import json
import threading
import time

import backend.app.api.v1.chats as chats_module
import pytest
from sqlalchemy import select
from starlette.requests import Request

from backend.app.api.v1.schemas import AskRequest
from backend.app.core.llm_policy import resolve_model_policy
from backend.app.db.models import (
    ChunkRecord,
    Document,
    IndexGenerationRecord,
    Message,
    ModelProvider,
    TraceRecord,
    User,
)
from backend.app.rag.answer import AnswerResult
from backend.app.rag.answer.service import answer_result_from_text
from backend.app.rag.domain.models import (
    DataClassification,
    RetrievedChunk,
    SearchResult,
)


def _setup_chat(api_client, admin_headers):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Retrieval Team"},
        headers=admin_headers,
    ).json()["data"]
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Retrieval KB"},
        headers=admin_headers,
    ).json()["data"]
    chat = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "knowledge_base_ids": [kb["id"]]},
        headers=admin_headers,
    ).json()["data"]
    provider = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team["id"],
            "name": "Chat Test Provider",
            "provider_type": "openai_chat_completions",
            "base_url": "http://provider.test/v1",
            "api_key": "sk-chat-test-secret",
            "model_ids": ["model-test"],
        },
        headers=admin_headers,
    ).json()["data"]
    api_client.post(
        "/api/v1/admin/model-policy/update",
        json={
            "mode": "external_allowed",
            "allowed_provider_ids": [provider["id"]],
            "max_data_classification": "internal",
        },
        headers=admin_headers,
    )
    kb_policy = api_client.get(
        "/api/v1/kbs/policy",
        params={"team_id": team["id"], "kb_id": kb["id"]},
        headers=admin_headers,
    ).json()["data"]
    api_client.post(
        "/api/v1/kbs/policy/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "mode": "external_allowed",
        },
        headers={**admin_headers, "If-Match": str(kb_policy["version"])},
    )
    chat["provider_id"] = provider["id"]
    chat["model_id"] = "model-test"
    return team, chat


def _selection(chat):
    return {
        "provider_id": chat["provider_id"],
        "model_id": chat["model_id"],
    }


def _add_generation(api_app, team_id):
    with api_app.state.session_factory() as session:
        session.add(IndexGenerationRecord(team_id=team_id, status="active"))
        session.commit()


def _stream_request(api_app, *, disconnected=False):
    async def receive():
        if disconnected:
            return {"type": "http.disconnect"}
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/chats/ask",
            "raw_path": b"/api/v1/chats/ask",
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "app": api_app,
        },
        receive,
    )
    request.state.request_id = "req_stream_test"
    return request


def _direct_stream_request(
    api_app,
    team_id,
    chat_id,
    *,
    question="Stream this answer",
    disconnected=False,
):
    with api_app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.email == "admin@techvault.local"))
        assert user is not None
        provider = session.scalar(
            select(ModelProvider).where(ModelProvider.team_id == team_id)
        )
        assert provider is not None
        response = asyncio.run(
            chats_module.ask(
                AskRequest(
                    team_id=team_id,
                    chat_id=chat_id,
                    question=question,
                    provider_id=provider.id,
                    model_id="model-test",
                    stream=True,
                ),
                _stream_request(api_app, disconnected=disconnected),
                user,
                session,
            )
        )
    return response


async def _consume_stream(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else str(chunk))
    return "".join(chunks)


def _local_decision():
    return resolve_model_policy(
        deployment_mode="local_only",
        requested_classification=DataClassification.INTERNAL,
    )


class _FakeAnswerProvider:
    provider_id = "provider-test"
    model_id = "model-test"
    route = "local_model"

    def __init__(self):
        self.context_chunks = []

    def generate(self, *, question, chunks, max_chunks):
        selected = list(chunks[:max_chunks])
        self.context_chunks.append(selected)
        if not selected:
            return AnswerResult(
                text="No evidence.",
                status="refused",
                citation_chunk_ids=(),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
                refusal_reason="INSUFFICIENT_EVIDENCE",
            )
        citations = tuple(chunk.chunk_id for chunk in selected)
        text = "Provider answer " + " ".join(
            "[c{0}]".format(index) for index in range(1, len(selected) + 1)
        )
        return AnswerResult(
            text=text,
            status="completed",
            citation_chunk_ids=citations,
            model_id=self.model_id,
            route=self.route,
            degraded=False,
        )


def _install_answer_provider(monkeypatch, provider=None):
    provider = provider or _FakeAnswerProvider()

    def build_gateway(request, decision, resolved_provider):
        provider.provider_id = resolved_provider.provider_id
        return chats_module.LlmGateway(
            decision=decision,
            external_answer_provider=provider,
            external_api_key="test-key",
            local_embed_provider=chats_module.EmbeddingClient(
                request.app.state.settings.embedding_url
            ),
            local_rerank_provider=chats_module.RerankerClient(
                request.app.state.settings.rerank_url
            ),
        )

    monkeypatch.setattr(chats_module, "_build_gateway", build_gateway)
    return provider


def test_gateway_streams_provider_generate_stream_without_buffering():
    class Provider:
        model_id = "stream-model"
        route = "local_model"

        def __init__(self):
            self.calls = 0

        async def generate_stream(self, *, question, chunks, max_chunks):
            self.calls += 1
            yield "first "
            yield "second"

    provider = Provider()
    gateway = chats_module.LlmGateway(
        decision=_local_decision(),
        external_answer_provider=provider,
    )
    chunk = RetrievedChunk(
        chunk_id="chunk-1",
        document_version_id="version-1",
        content="Grounded evidence",
        fused_rank=1,
    )

    stream = gateway.generate_stream(
        question="Question",
        chunks=(chunk,),
        classification=DataClassification.INTERNAL,
    )

    assert provider.calls == 0
    pieces = asyncio.run(_collect_async(stream))
    assert pieces == ["first ", "second"]
    assert stream.result is not None
    assert stream.result.text == "first second"
    assert stream.result.citation_chunk_ids == ()
    assert stream.result.degraded is True
    assert provider.calls == 1


def test_gateway_accepts_sync_stream_provider_and_reports_result():
    class Provider:
        model_id = "sync-stream-model"
        route = "local_model"

        def stream(self, *, question, chunks, max_chunks):
            return iter(["alpha", "-beta"])

    gateway = chats_module.LlmGateway(
        decision=_local_decision(),
        external_answer_provider=Provider(),
    )
    stream = gateway.generate_stream(
        question="Question",
        chunks=(
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Evidence",
                fused_rank=1,
            ),
        ),
        classification=DataClassification.INTERNAL,
    )

    assert asyncio.run(_collect_async(stream)) == ["alpha", "-beta"]
    assert stream.result is not None
    assert stream.result.text == "alpha-beta"


def test_gateway_stream_exception_after_partial_content_does_not_complete_result():
    class Provider:
        provider_id = "provider-1"
        model_id = "stream-model"
        route = "local_model"

        async def generate_stream(self, *, question, chunks, max_chunks):
            yield "partial "
            raise RuntimeError("provider stream failed")

    gateway = chats_module.LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=DataClassification.PUBLIC,
        ),
        external_answer_provider=Provider(),
        external_api_key="secret-key",
    )
    stream = gateway.generate_stream(
        question="Question",
        chunks=(
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Evidence",
                fused_rank=1,
            ),
        ),
        classification=DataClassification.PUBLIC,
    )

    from backend.app.rag.llm_gateway import ModelUnavailableError

    with pytest.raises(ModelUnavailableError, match="Answer provider failed"):
        asyncio.run(_collect_async(stream))

    assert stream.result is None
    assert gateway.audits == []


def test_gateway_defers_non_stream_provider_until_iteration():
    class Provider:
        model_id = "local-model"
        route = "local_model"

        def __init__(self):
            self.calls = 0

        def generate(self, *, question, chunks, max_chunks):
            self.calls += 1
            return AnswerResult(
                text="completed locally",
                status="completed",
                citation_chunk_ids=("chunk-1",),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
            )

    provider = Provider()
    gateway = chats_module.LlmGateway(
        decision=_local_decision(),
        external_answer_provider=provider,
    )
    stream = gateway.generate_stream(
        question="Question",
        chunks=(
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Evidence",
                fused_rank=1,
            ),
        ),
        classification=DataClassification.INTERNAL,
    )

    assert provider.calls == 0
    assert "".join(asyncio.run(_collect_async(stream))) == "completed locally"
    assert provider.calls == 1
    assert stream.result is not None
    assert stream.result.text == "completed locally"


async def _collect_async(stream):
    return [piece async for piece in stream]


def test_chat_ask_uses_team_active_generation_and_backend_engine_mode(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    with api_app.state.session_factory() as session:
        generation = IndexGenerationRecord(team_id=team["id"], status="active")
        session.add(generation)
        session.commit()
        generation_id = generation.id

    captured = {}

    class Retriever:
        async def search(self, request):
            captured["mode"] = "called"
            return SearchResult([], {}, False, "trace-test")

    def build_retriever(settings, selected_generation_id, mode):
        captured["generation_id"] = selected_generation_id
        captured["engine_mode"] = mode.value
        return Retriever()

    monkeypatch.setattr(chats_module.EmbeddingClient, "embed", lambda self, texts: [[0.1]])
    monkeypatch.setattr(chats_module, "build_retriever", build_retriever)
    _install_answer_provider(monkeypatch)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "What is RAG?",
            **_selection(chat),
            "knowledge_base_ids": [],
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert captured["generation_id"] == generation_id
    assert captured["engine_mode"] == "dual_engine"


def test_chat_ask_fails_closed_without_active_generation(api_client, admin_headers):
    team, chat = _setup_chat(api_client, admin_headers)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "What is RAG?",
            **_selection(chat),
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INDEX_NOT_READY"


def _mock_ask_stack(api_app, team_id, monkeypatch, result, provider=None):
    with api_app.state.session_factory() as session:
        session.add(IndexGenerationRecord(team_id=team_id, status="active"))
        session.commit()

    class Retriever:
        async def search(self, request):
            return result

    monkeypatch.setattr(chats_module.EmbeddingClient, "embed", lambda self, texts: [[0.1]])
    monkeypatch.setattr(chats_module, "build_retriever", lambda *args: Retriever())
    monkeypatch.setattr(
        chats_module.RerankerClient,
        "rerank",
        lambda self, query, chunks, top_n: list(chunks),
    )
    _install_answer_provider(monkeypatch, provider)


def test_chat_ask_streams_citations_delta_and_done(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    result = SearchResult(
        chunks=[
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Virtual threads are lightweight.",
                fused_rank=1,
                source_locator={"file_name": "threads.md"},
            ),
            RetrievedChunk(
                chunk_id="chunk-2",
                document_version_id="version-2",
                content="Virtual threads reduce thread cost.",
                fused_rank=2,
                source_locator={"file_name": "thread-cost.md"},
            ),
        ],
        stage_latency={},
        degraded=False,
        trace_id="trace-stream",
    )

    class SelectiveCitationProvider:
        model_id = "model-test"
        route = "local_model"

        async def generate_stream(self, *, question, chunks, max_chunks):
            yield "Provider answer [c2]"

    _mock_ask_stack(
        api_app,
        team["id"],
        monkeypatch,
        result,
        SelectiveCitationProvider(),
    )

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "How do virtual threads work?",
            **_selection(chat),
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in response.text
    assert "event: citation" in response.text
    citation_index = response.text.index("event: citation")
    done_index = response.text.index("event: done")
    assert citation_index < done_index
    assert response.text.count("event: citation") == 1
    assert '"chunk_id": "chunk-2"' in response.text
    assert '"citation_id": "c2"' in response.text
    assert '"excerpt": "Virtual threads reduce thread cost."' in response.text
    assert "event: delta" in response.text
    assert '"text": "Provider answer [c2]"' in response.text
    assert '"model_id": "model-test"' in response.text
    assert "event: done" in response.text
    assert '"citation_ids": ["c2"]' in response.text
    assert "event: answer" not in response.text


def test_chat_ask_non_stream_preserves_citation_source_index(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    result = SearchResult(
        chunks=[
            RetrievedChunk(
                chunk_id="chunk-{0}".format(index),
                document_version_id="version-{0}".format(index),
                content="Evidence {0}".format(index),
                fused_rank=index,
                source_locator={"file_name": "evidence-{0}.md".format(index)},
            )
            for index in range(1, 8)
        ],
        stage_latency={},
        degraded=False,
        trace_id="trace-non-stream-c7",
    )

    class SeventhCitationProvider:
        model_id = "model-test"
        route = "local_model"

        def generate(self, *, question, chunks, max_chunks):
            return AnswerResult(
                text="Provider answer [c7]",
                status="completed",
                citation_chunk_ids=("chunk-7",),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
            )

    _mock_ask_stack(
        api_app,
        team["id"],
        monkeypatch,
        result,
        SeventhCitationProvider(),
    )

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Use the seventh source",
            **_selection(chat),
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["content"] == "Provider answer [c7]"
    assert data["citations"] == [
        {
            "citation_id": "c7",
            "chunk_id": "chunk-7",
            "document_version_id": "version-7",
            "excerpt": "Evidence 7",
            "source_locator": {"file_name": "evidence-7.md"},
        }
    ]


def test_chat_ask_non_stream_without_citations_refuses_with_model_text(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    refusal_text = "提供的知识库中没有包含我的名字或身份信息，因此无法回答“你叫什么名字”。"
    result = SearchResult(
        [
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Virtual threads reduce thread cost.",
                fused_rank=1,
                source_locator={"file_name": "threads.md"},
            )
        ],
        {},
        False,
        "trace-no-citation",
    )

    class NoCitationProvider:
        model_id = "model-test"
        route = "local_model"

        def generate(self, *, question, chunks, max_chunks):
            return answer_result_from_text(
                refusal_text,
                question=question,
                chunks=chunks,
                model_id=self.model_id,
                route=self.route,
            )

    _mock_ask_stack(
        api_app,
        team["id"],
        monkeypatch,
        result,
        NoCitationProvider(),
    )

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "你叫什么名字",
            **_selection(chat),
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "refused"
    assert data["refusal_reason"] == "INSUFFICIENT_EVIDENCE"
    assert data["citations"] == []
    assert data["content"] == refusal_text


def test_chat_ask_stream_without_citations_refuses_without_citation_or_done(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    refusal_text = "提供的知识库中没有包含我的名字或身份信息，因此无法回答“你叫什么名字”。"
    result = SearchResult(
        [
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Virtual threads reduce thread cost.",
                fused_rank=1,
                source_locator={"file_name": "threads.md"},
            )
        ],
        {},
        False,
        "trace-stream-no-citation",
    )

    class NoCitationStreamProvider:
        model_id = "model-test"
        route = "local_model"

        async def generate_stream(self, *, question, chunks, max_chunks):
            yield refusal_text

    _mock_ask_stack(
        api_app,
        team["id"],
        monkeypatch,
        result,
        NoCitationStreamProvider(),
    )

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "你叫什么名字",
            **_selection(chat),
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert "event: citation" not in response.text
    assert '"text": "{0}"'.format(refusal_text) in response.text
    assert "event: refused" in response.text
    assert '"reason_code": "INSUFFICIENT_EVIDENCE"' in response.text
    assert "event: done" not in response.text


def test_chat_ask_hydrates_citation_locator_from_persisted_chunk(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    _add_generation(api_app, team["id"])
    with api_app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.email == "admin@techvault.local"))
        assert user is not None
        knowledge_base_id = chat["knowledge_base_ids"][0]
        session.add(
            Document(
                id="doc-1",
                knowledge_base_id=knowledge_base_id,
                owner_user_id=user.id,
                file_name="threads.md",
                source_uri="/tmp/threads.md",
            )
        )
        session.flush()
        session.add(
            ChunkRecord(
                id="chunk-1",
                document_id="doc-1",
                content="Virtual threads reduce thread cost.",
                source_locator=json.dumps(
                    {
                        "document_id": "doc-1",
                        "document_version_id": "version-1",
                        "file_name": "threads.md",
                        "source_url": "/api/v1/docs/download?team_id=team-a&document_id=doc-1",
                        "source_path": "threads.md",
                        "heading_path": ["Virtual Threads"],
                    }
                ),
            )
        )
        session.commit()

    result = SearchResult(
        chunks=[
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Virtual threads reduce thread cost.",
                fused_rank=1,
                source_locator={},
            )
        ],
        stage_latency={},
        degraded=False,
        trace_id="trace-hydrated-citation",
    )
    _mock_ask_stack(api_app, team["id"], monkeypatch, result)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "How do virtual threads work?",
            **_selection(chat),
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert '"document_id": "doc-1"' in response.text
    assert '"document_name": "threads.md"' in response.text
    assert (
        '"source_url": "/api/v1/docs/download?team_id=team-a&document_id=doc-1"'
        in response.text
    )


def test_chat_ask_streams_refused_as_terminal_event(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    result = SearchResult([], {}, False, "trace-refused")
    _mock_ask_stack(api_app, team["id"], monkeypatch, result)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Unknown topic",
            **_selection(chat),
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert "event: refused" in response.text
    assert '"reason_code": "INSUFFICIENT_EVIDENCE"' in response.text
    assert "event: delta" not in response.text
    assert "event: done" not in response.text


def test_chat_ask_accepts_nested_filters_and_retrieves_with_rewritten_query(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    with api_app.state.session_factory() as session:
        session.add(
            Message(
                chat_id=chat["id"],
                role="user",
                content="Spring Boot 3.2 如何配置虚拟线程？",
                status="completed",
            )
        )
        session.add(IndexGenerationRecord(team_id=team["id"], status="active"))
        session.commit()

    captured = {}

    class Retriever:
        async def search(self, request):
            captured["request"] = request
            return SearchResult([], {}, False, "trace-rewrite")

    monkeypatch.setattr(chats_module.EmbeddingClient, "embed", lambda self, texts: [[0.1]])
    monkeypatch.setattr(chats_module, "build_retriever", lambda *args: Retriever())
    _install_answer_provider(monkeypatch)
    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "它和 2.x 有什么区别？",
            **_selection(chat),
            "filters": {
                "knowledge_base_ids": chat["knowledge_base_ids"],
                "product": "spring-boot",
                "version_values": ["3.2"],
            },
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    request = captured["request"]
    assert request.query == "它和 2.x 有什么区别？"
    assert "Spring Boot" in request.rewritten_query
    assert request.filters.product == "spring-boot"
    assert request.filters.version_values == ("3.2",)
    assert "event: rewrite" in response.text
    with api_app.state.session_factory() as session:
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.trace_id == "trace-rewrite")
        )
        assert trace.original_query == "它和 2.x 有什么区别？"
        assert "Spring Boot" in trace.rewritten_query
        assert '"product": "spring-boot"' in trace.filters


def test_message_history_returns_citation_objects_without_validation_error(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    result = SearchResult(
        [
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Grounded evidence.",
                fused_rank=1,
                source_locator={"file_name": "evidence.md"},
            )
        ],
        {},
        False,
        "trace-citations",
    )
    _mock_ask_stack(api_app, team["id"], monkeypatch, result)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "What is the evidence?",
            **_selection(chat),
            "stream": False,
        },
        headers=admin_headers,
    )
    assert response.status_code == 200

    history = api_client.get(
        "/api/v1/chats/messages",
        params={"team_id": team["id"], "chat_id": chat["id"]},
        headers=admin_headers,
    )
    assert history.status_code == 200
    assistant = history.json()["data"][-1]
    assert assistant["citation_ids"][0]["citation_id"] == "c1"
    assert assistant["citation_ids"][0]["chunk_id"] == "chunk-1"


def test_chat_answer_uses_top_eight_context_chunks_from_injected_provider(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    chunks = [
        RetrievedChunk(
            chunk_id="chunk-{0}".format(index),
            document_version_id="version-1",
            content="Evidence {0}".format(index),
            fused_rank=index,
        )
        for index in range(1, 13)
    ]
    provider = _FakeAnswerProvider()
    _mock_ask_stack(
        api_app,
        team["id"],
        monkeypatch,
        SearchResult(chunks, {}, False, "trace-top-eight"),
        provider,
    )

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Collect evidence",
            **_selection(chat),
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.text.count("event: citation") == 8
    assert len(provider.context_chunks[-1]) == 8
    assert '"model_id": "model-test"' in response.text
    assert '"route": "local_model"' in response.text
    assert '"degraded": false' in response.text


def test_streaming_answer_defers_rewrite_embedding_retrieval_and_rerank(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    _add_generation(api_app, team["id"])
    calls = []
    original_rewrite = chats_module.LlmGateway.rewrite

    def rewrite(self, **kwargs):
        calls.append("rewrite")
        return original_rewrite(self, **kwargs)

    def embed(self, texts, **kwargs):
        calls.append("embedding")
        return [[0.1]]

    class Retriever:
        async def search(self, request):
            calls.append("retrieval")
            return SearchResult([], {}, False, "trace-deferred")

    def build_retriever(*args):
        calls.append("build_retriever")
        return Retriever()

    monkeypatch.setattr(chats_module.LlmGateway, "rewrite", rewrite)
    monkeypatch.setattr(chats_module.LlmGateway, "embed", embed)
    monkeypatch.setattr(chats_module, "build_retriever", build_retriever)
    monkeypatch.setattr(
        chats_module.RerankerClient,
        "rerank",
        lambda self, query, chunks, top_n: calls.append("rerank") or list(chunks),
    )
    _install_answer_provider(monkeypatch)

    response = _direct_stream_request(api_app, team["id"], chat["id"])

    assert calls == []
    body = asyncio.run(_consume_stream(response))
    assert calls == ["rewrite", "embedding", "build_retriever", "retrieval", "rerank"]
    assert "event: refused" in body


def test_streaming_gateway_calls_run_off_event_loop_thread(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    _add_generation(api_app, team["id"])
    main_thread_id = threading.get_ident()
    call_threads = {}
    original_rewrite = chats_module.LlmGateway.rewrite

    def rewrite(self, **kwargs):
        call_threads["rewrite"] = threading.get_ident()
        return original_rewrite(self, **kwargs)

    def embed(self, texts, **kwargs):
        call_threads["embedding"] = threading.get_ident()
        time.sleep(0.05)
        return [[0.1]]

    def rerank(self, query, chunks, top_n):
        call_threads["rerank"] = threading.get_ident()
        return list(chunks)

    class Retriever:
        async def search(self, request):
            return SearchResult([], {}, False, "trace-threaded")

    monkeypatch.setattr(chats_module.LlmGateway, "rewrite", rewrite)
    monkeypatch.setattr(chats_module.LlmGateway, "embed", embed)
    monkeypatch.setattr(chats_module.RerankerClient, "rerank", rerank)
    monkeypatch.setattr(chats_module, "build_retriever", lambda *args: Retriever())
    _install_answer_provider(monkeypatch)

    response = _direct_stream_request(api_app, team["id"], chat["id"])
    body = asyncio.run(_consume_stream(response))

    assert "event: refused" in body
    assert set(call_threads) == {"rewrite", "embedding", "rerank"}
    assert all(thread_id != main_thread_id for thread_id in call_threads.values())


def test_client_disconnect_stops_before_rewrite_and_persists_cancelled(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    _add_generation(api_app, team["id"])
    calls = []

    monkeypatch.setattr(
        chats_module.LlmGateway,
        "rewrite",
        lambda self, **kwargs: calls.append("rewrite"),
    )
    monkeypatch.setattr(
        chats_module.LlmGateway,
        "embed",
        lambda self, texts, **kwargs: calls.append("embedding") or [[0.1]],
    )

    response = _direct_stream_request(
        api_app,
        team["id"],
        chat["id"],
        disconnected=True,
    )
    body = asyncio.run(_consume_stream(response))

    assert calls == []
    assert "event: done" not in body
    with api_app.state.session_factory() as session:
        message = session.scalar(
            select(Message).where(Message.chat_id == chat["id"], Message.role == "assistant")
        )
        assert message is not None
        assert message.status == "cancelled"


def test_database_cancelled_stops_before_pipeline_and_persists_terminal_state(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    _add_generation(api_app, team["id"])
    calls = []

    def rewrite(self, **kwargs):
        calls.append("rewrite")

    monkeypatch.setattr(chats_module.LlmGateway, "rewrite", rewrite)
    monkeypatch.setattr(
        chats_module.LlmGateway,
        "embed",
        lambda self, texts, **kwargs: calls.append("embedding") or [[0.1]],
    )

    response = _direct_stream_request(api_app, team["id"], chat["id"])
    with api_app.state.session_factory() as session:
        message = session.scalar(
            select(Message).where(Message.chat_id == chat["id"], Message.role == "assistant")
        )
        assert message is not None
        message.status = "cancelled"
        session.commit()

    body = asyncio.run(_consume_stream(response))

    assert calls == []
    assert "event: done" not in body
    with api_app.state.session_factory() as session:
        message = session.scalar(
            select(Message).where(Message.chat_id == chat["id"], Message.role == "assistant")
        )
        assert message is not None
        assert message.status == "cancelled"


def test_stream_error_persists_failed_message_and_trace_terminal_state(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    _add_generation(api_app, team["id"])
    result = SearchResult(
        [
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Grounding evidence",
                fused_rank=1,
            )
        ],
        {},
        False,
        "trace-stream-error",
    )

    class Retriever:
        async def search(self, request):
            return result

    async def failing_generate_stream(self, **kwargs):
        if False:
            yield ""
        raise RuntimeError("provider stream failed")

    monkeypatch.setattr(chats_module.LlmGateway, "embed", lambda self, texts, **kwargs: [[0.1]])
    monkeypatch.setattr(chats_module, "build_retriever", lambda *args: Retriever())
    monkeypatch.setattr(
        chats_module.RerankerClient,
        "rerank",
        lambda self, query, chunks, top_n: list(chunks),
    )
    monkeypatch.setattr(
        chats_module.LlmGateway,
        "generate_stream",
        failing_generate_stream,
        raising=False,
    )

    response = _direct_stream_request(api_app, team["id"], chat["id"])
    body = asyncio.run(_consume_stream(response))

    assert "event: error" in body
    assert "event: done" not in body
    with api_app.state.session_factory() as session:
        message = session.scalar(
            select(Message).where(Message.chat_id == chat["id"], Message.role == "assistant")
        )
        assert message is not None
        assert message.status == "failed"
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.trace_id == "trace-stream-error")
        )
        assert trace is not None
        assert trace.message_id == message.id
        assert trace.error_code == "STREAM_ERROR"


def test_retrieval_failure_before_result_persists_failed_trace(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    _add_generation(api_app, team["id"])

    class Retriever:
        async def search(self, request):
            raise RuntimeError("qdrant unavailable")

    monkeypatch.setattr(chats_module.LlmGateway, "embed", lambda self, texts, **kwargs: [[0.1]])
    monkeypatch.setattr(chats_module, "build_retriever", lambda *args: Retriever())

    response = _direct_stream_request(api_app, team["id"], chat["id"])
    body = asyncio.run(_consume_stream(response))

    assert "event: error" in body
    assert "qdrant unavailable" in body
    with api_app.state.session_factory() as session:
        message = session.scalar(
            select(Message).where(Message.chat_id == chat["id"], Message.role == "assistant")
        )
        assert message is not None
        assert message.status == "failed"
        assert message.trace_id
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.message_id == message.id)
        )
        assert trace is not None
        assert trace.trace_id == message.trace_id
        assert trace.error_code == "STREAM_ERROR"
        assert trace.degraded is True
        latencies = json.loads(trace.stage_latency_ms)
        assert latencies["rewrite_ms"] >= 0
        assert latencies["embedding_ms"] >= 0
        assert latencies["retrieval_ms"] >= 0


def test_embedding_failure_before_retrieval_persists_failed_trace(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    _add_generation(api_app, team["id"])
    monkeypatch.setattr(chats_module.LlmGateway, "embed", lambda self, texts, **kwargs: [])

    response = _direct_stream_request(api_app, team["id"], chat["id"])
    body = asyncio.run(_consume_stream(response))

    assert "event: error" in body
    assert "embedding provider returned no vectors" in body
    with api_app.state.session_factory() as session:
        message = session.scalar(
            select(Message).where(Message.chat_id == chat["id"], Message.role == "assistant")
        )
        assert message is not None
        assert message.status == "failed"
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.message_id == message.id)
        )
        assert trace is not None
        assert trace.error_code == "STREAM_ERROR"
        assert trace.degraded is True
        latencies = json.loads(trace.stage_latency_ms)
        assert latencies["rewrite_ms"] >= 0
        assert latencies["embedding_ms"] >= 0


def test_non_stream_retrieval_failure_persists_failed_trace(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    _add_generation(api_app, team["id"])

    class Retriever:
        async def search(self, request):
            raise RuntimeError("retrieval backend unavailable")

    monkeypatch.setattr(chats_module.LlmGateway, "embed", lambda self, texts, **kwargs: [[0.1]])
    monkeypatch.setattr(chats_module, "build_retriever", lambda *args: Retriever())

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Trigger a retrieval failure",
            **_selection(chat),
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RETRIEVAL_UNAVAILABLE"
    with api_app.state.session_factory() as session:
        message = session.scalar(
            select(Message).where(Message.chat_id == chat["id"], Message.role == "assistant")
        )
        assert message is not None
        assert message.status == "failed"
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.message_id == message.id)
        )
        assert trace is not None
        assert trace.error_code == "RETRIEVAL_UNAVAILABLE"
        assert trace.degraded is True
        latencies = json.loads(trace.stage_latency_ms)
        assert latencies["rewrite_ms"] >= 0
        assert latencies["embedding_ms"] >= 0
        assert latencies["retrieval_ms"] >= 0


def test_chat_ask_rewrite_event_includes_self_query_metadata(
    api_client, api_app, admin_headers, monkeypatch
):
    team, chat = _setup_chat(api_client, admin_headers)
    result = SearchResult([], {}, False, "trace-rewrite-event")

    class Provider:
        provider_id = chat["provider_id"]
        model_id = "model-test"
        route = "openai_chat_completions"

        def rewrite(self, **kwargs):
            from backend.app.rag.llm_gateway.contracts import RewriteResult

            return RewriteResult(
                original_query=kwargs["question"],
                rewritten_query="Spring Boot 虚拟线程",
                changed=True,
                route=self.route,
                model_id=self.model_id,
                provider_id=self.provider_id,
                structured_mode="json_schema",
                extracted_filters={
                    "product": None,
                    "version_values": [],
                },
            )

        def generate(self, *, question, chunks, max_chunks):
            return AnswerResult(
                text="No evidence.",
                status="refused",
                citation_chunk_ids=(),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
                refusal_reason="INSUFFICIENT_EVIDENCE",
            )

    _mock_ask_stack(
        api_app,
        team["id"],
        monkeypatch,
        result,
        Provider(),
    )
    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "它是什么？",
            **_selection(chat),
            "stream": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert "event: rewrite" in response.text
    assert '"route": "openai_chat_completions"' in response.text
    assert '"structured_mode": "json_schema"' in response.text
    assert '"applied_filters"' in response.text


def test_candidate_rows_include_bm25_matched_terms():
    rows = chats_module._candidate_rows(
        [
            RetrievedChunk(
                chunk_id="chunk-highlight",
                document_version_id="version-1",
                content="Virtual threads",
                fused_rank=1,
                bm25_rank=1,
                matched_terms=("Virtual", "threads"),
            )
        ]
    )

    assert rows[0]["matched_terms"] == ["Virtual", "threads"]
