import json

from backend.app.api.v1 import chats as chats_module
from backend.app.db.models import Document, IndexGenerationRecord, TraceRecord
from backend.app.rag.domain.models import SearchResult


def test_chat_applies_llm_self_query_filters_to_retrieval(
    api_client, api_app, admin_headers, monkeypatch
):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Self Query Team"},
        headers=admin_headers,
    ).json()["data"]
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Self Query KB"},
        headers=admin_headers,
    ).json()["data"]
    chat = api_client.post(
        "/api/v1/chats/create",
        json={
            "team_id": team["id"],
            "knowledge_base_ids": [kb["id"]],
        },
        headers=admin_headers,
    ).json()["data"]
    provider = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team["id"],
            "name": "Self Query Provider",
            "provider_type": "openai_chat_completions",
            "base_url": "http://provider.test/v1",
            "api_key": "sk-self-query",
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

    with api_app.state.session_factory() as session:
        user_id = api_client.get(
            "/api/v1/auth/me",
            headers=admin_headers,
        ).json()["data"]["user"]["id"]
        session.add(
            Document(
                knowledge_base_id=kb["id"],
                owner_user_id=user_id,
                file_name="spring.md",
                product="spring-boot",
                version_values=json.dumps(["3.2"]),
                doc_status="active",
            )
        )
        session.add(
            IndexGenerationRecord(team_id=team["id"], status="active")
        )
        session.commit()

    captured = {}

    class Retriever:
        async def search(self, request):
            captured["filters"] = request.filters
            return SearchResult(
                chunks=[],
                stage_latency={},
                degraded=False,
                trace_id="trace-self-query",
            )

    class Provider:
        provider_id = provider["id"]
        model_id = "model-test"
        route = "openai_chat_completions"

        def rewrite(self, **kwargs):
            from backend.app.rag.llm_gateway.contracts import RewriteResult

            return RewriteResult(
                original_query=kwargs["question"],
                rewritten_query="Spring Boot 3.2 如何开启虚拟线程？",
                changed=True,
                route=self.route,
                model_id=self.model_id,
                provider_id=self.provider_id,
                structured_mode="json_schema",
                extracted_filters={
                    "product": "spring-boot",
                    "version_values": ["3.2"],
                },
            )

        def generate(self, *, question, chunks, max_chunks):
            from backend.app.rag.answer import AnswerResult

            return AnswerResult(
                text="No evidence.",
                status="refused",
                citation_chunk_ids=(),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
                refusal_reason="INSUFFICIENT_EVIDENCE",
            )

    monkeypatch.setattr(
        chats_module,
        "build_retriever",
        lambda *args: Retriever(),
    )
    monkeypatch.setattr(
        chats_module.EmbeddingClient,
        "embed",
        lambda self, texts: [[0.1]],
    )
    monkeypatch.setattr(
        chats_module.RerankerClient,
        "rerank",
        lambda self, query, chunks, top_n: list(chunks),
    )
    monkeypatch.setattr(
        chats_module,
        "_build_gateway",
        lambda request, decision, resolved: chats_module.LlmGateway(
            decision=decision,
            external_answer_provider=Provider(),
            external_api_key="test-key",
            local_embed_provider=chats_module.EmbeddingClient(
                request.app.state.settings.embedding_url
            ),
            local_rerank_provider=chats_module.RerankerClient(
                request.app.state.settings.rerank_url
            ),
        ),
    )

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "它怎么开启？",
            "provider_id": provider["id"],
            "model_id": "model-test",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert captured["filters"].product == "spring-boot"
    assert captured["filters"].version_values == ("3.2",)
    assert response.json()["data"]["status"] == "refused"
    trace_id = response.json()["data"]["trace_id"]
    with api_app.state.session_factory() as session:
        trace = session.query(TraceRecord).filter_by(trace_id=trace_id).one()
        rewrite_trace = json.loads(trace.rewrite)
    assert rewrite_trace["structured_mode"] == "json_schema"
    assert rewrite_trace["applied_filters"] == {
        "product": "spring-boot",
        "version_values": ["3.2"],
    }
