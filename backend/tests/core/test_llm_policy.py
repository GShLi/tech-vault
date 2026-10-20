import pytest

import backend.app.rag.llm_gateway.gateway as gateway_module
from backend.app.rag.domain.models import DataClassification
from backend.app.rag.domain.models import RetrievedChunk
from backend.app.rag.llm_gateway.providers import ProviderAdapterError


def test_default_policy_blocks_external_calls():
    from backend.app.core.llm_policy import (
        assert_external_call_allowed,
        resolve_model_policy,
    )

    decision = resolve_model_policy(
        deployment_mode="local_only",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is False
    with pytest.raises(PermissionError):
        assert_external_call_allowed(decision, DataClassification.PUBLIC)


def test_external_allowed_policy_allows_public_data():
    from backend.app.core.llm_policy import (
        assert_external_call_allowed,
        resolve_model_policy,
    )

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        requested_classification=DataClassification.PUBLIC,
        allowed_provider_ids=("provider-a",),
        allowed_model_ids=("model-a",),
    )

    assert decision.allow_external is True
    assert decision.allowed_provider_ids == ("provider-a",)
    assert decision.allowed_model_ids == ("model-a",)
    assert_external_call_allowed(decision, DataClassification.PUBLIC)


@pytest.mark.parametrize(
    "policy_argument",
    ["team_mode", "knowledge_base_mode", "request_mode"],
)
def test_any_local_only_level_is_strictest(policy_argument):
    from backend.app.core.llm_policy import resolve_model_policy

    arguments = {
        "deployment_mode": "external_allowed",
        "requested_classification": DataClassification.PUBLIC,
        policy_argument: "local_only",
    }
    decision = resolve_model_policy(**arguments)

    assert decision.allow_external is False


def test_request_cannot_relax_team_policy():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        team_mode="local_only",
        request_mode="external_required",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is False


def test_inherit_request_mode_uses_the_remaining_policy_layers():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        request_mode="inherit",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is True


def test_missing_deployment_policy_fails_closed():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode=None,
        team_mode="external_allowed",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is False


@pytest.mark.parametrize("mode", ["external_allowed", "external_required"])
def test_restricted_data_is_never_sent_externally(mode):
    from backend.app.core.llm_policy import (
        assert_external_call_allowed,
        resolve_model_policy,
    )

    decision = resolve_model_policy(
        deployment_mode=mode,
        requested_classification=DataClassification.RESTRICTED,
    )

    assert decision.allow_external is False
    with pytest.raises(PermissionError):
        assert_external_call_allowed(decision, DataClassification.RESTRICTED)


def test_private_data_requires_local_model_even_when_external_is_allowed():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        requested_classification=DataClassification.PRIVATE,
    )

    assert decision.allow_external is False
    assert decision.fallback_mode == "local_model"


def test_policy_service_failure_fails_closed():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_required",
        requested_classification=DataClassification.PUBLIC,
        policy_available=False,
    )

    assert decision.allow_external is False
    assert decision.reason_code == "policy_unavailable"


def test_unknown_policy_mode_fails_closed():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="unexpected_mode",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is False


def test_external_call_rechecks_data_classification():
    from backend.app.core.llm_policy import (
        assert_external_call_allowed,
        resolve_model_policy,
    )

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        requested_classification=DataClassification.PUBLIC,
    )

    with pytest.raises(PermissionError):
        assert_external_call_allowed(decision, DataClassification.RESTRICTED)


def test_policy_uses_chat_naming_only():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        requested_classification=DataClassification.PUBLIC,
        allow_chat_history=True,
    )

    assert decision.allow_chat_history is True
    assert not hasattr(decision, "allow_conversation_history")


def test_sensitive_scan_redacts_credentials_email_and_internal_urls():
    from backend.app.rag.llm_gateway import scan_and_redact

    scan = scan_and_redact(
        "email dev@example.com token Bearer abc.def.ghi "
        "url http://192.168.1.20:8080/admin password=hunter2"
    )

    assert scan.redacted_count >= 4
    assert "dev@example.com" not in scan.text
    assert "abc.def.ghi" not in scan.text
    assert "192.168.1.20" not in scan.text
    assert "hunter2" not in scan.text
    assert set(scan.categories) >= {"email", "bearer_token", "internal_url", "password"}


def test_gateway_uses_injected_answer_provider_without_external_key():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.answer import AnswerResult
    from backend.app.rag.llm_gateway import LlmGateway

    class AnswerProvider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "local_model"

        def __init__(self):
            self.calls = 0

        def generate(self, *, question, chunks, max_chunks):
            self.calls += 1
            return AnswerResult(
                text="Provider answer [c1].",
                status="completed",
                citation_chunk_ids=(chunks[0].chunk_id,),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
            )

    provider = AnswerProvider()
    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        requested_classification=DataClassification.PUBLIC,
        allowed_provider_ids=("provider-a",),
    )
    gateway = LlmGateway(
        decision=decision,
        external_answer_provider=provider,
        external_api_key="",
    )

    result = gateway.generate(
        question="How do virtual threads work?",
        chunks=(
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="Virtual threads reduce thread cost.",
                fused_rank=1,
            ),
        ),
        classification=DataClassification.PUBLIC,
    )

    assert provider.calls == 1
    assert result.text == "Provider answer [c1]."
    assert result.model_id == "model-a"
    assert gateway.audits[-1].provider_id == "provider-a"
    assert gateway.audits[-1].model_id == "model-a"


def test_gateway_rewrites_follow_up_from_recent_product_and_version():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway

    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="local_only",
            requested_classification=DataClassification.INTERNAL,
        )
    )

    result = gateway.rewrite(
        question="它和 2.x 有什么区别？",
        history=(
            {"role": "user", "content": "Spring Boot 3.2 如何配置虚拟线程？"},
            {"role": "assistant", "content": "可以使用 spring.threads.virtual.enabled。"},
        ),
    )

    assert result.changed is True
    assert result.rewritten_query != result.original_query
    assert "Spring Boot" in result.rewritten_query
    assert "3.2" in result.rewritten_query


def test_external_required_without_key_fails_instead_of_silently_falling_back():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway, ModelUnavailableError

    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_required",
            requested_classification=DataClassification.PUBLIC,
        )
    )

    with pytest.raises(ModelUnavailableError):
        gateway.generate(
            question="public question",
            chunks=(
                RetrievedChunk(
                    chunk_id="chunk-1",
                    document_version_id="version-1",
                    content="public evidence",
                    fused_rank=1,
                ),
            ),
            classification=DataClassification.PUBLIC,
        )


def test_gateway_rejects_answer_generation_without_provider():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway, ModelUnavailableError

    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="local_only",
            requested_classification=DataClassification.INTERNAL,
        )
    )

    with pytest.raises(ModelUnavailableError, match="No answer provider"):
        gateway.generate(
            question="Question",
            chunks=[],
            max_chunks=1,
        )


def test_gateway_rejects_answer_stream_without_provider():
    import asyncio

    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway, ModelUnavailableError

    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="local_only",
            requested_classification=DataClassification.INTERNAL,
        )
    )
    stream = gateway.generate_stream(
        question="Question",
        chunks=[],
        max_chunks=1,
    )

    async def collect():
        return [piece async for piece in stream]

    with pytest.raises(ModelUnavailableError, match="No answer provider"):
        asyncio.run(collect())


def test_external_gateway_sends_redacted_payload_and_marks_route():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.answer import AnswerResult
    from backend.app.rag.llm_gateway import LlmGateway

    class ExternalProvider:
        provider_id = "provider-a"
        model_id = "external-model"
        route = "external"

        def __init__(self):
            self.questions = []

        def generate(self, *, question, chunks, max_chunks):
            self.questions.append(question)
            return AnswerResult(
                text="External answer [c1]",
                status="completed",
                citation_chunk_ids=("chunk-1",),
                model_id="external-model",
                route="external",
                degraded=False,
            )

    provider = ExternalProvider()
    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=DataClassification.PUBLIC,
            allowed_provider_ids=("provider-a",),
        ),
        external_answer_provider=provider,
        external_api_key="secret-key",
    )

    result = gateway.generate(
        question="contact dev@example.com",
        chunks=(
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="public evidence",
                fused_rank=1,
            ),
        ),
        classification=DataClassification.PUBLIC,
    )

    assert result.route == "external"
    assert provider.questions == ["contact [REDACTED:email]"]
    assert gateway.audits[-1].external is True
    assert gateway.audits[-1].redacted_count == 1


@pytest.mark.parametrize(
    ("policy_classification", "classification"),
    [
        (DataClassification.PUBLIC, DataClassification.PRIVATE),
        (DataClassification.PUBLIC, DataClassification.RESTRICTED),
        (DataClassification.PRIVATE, DataClassification.PRIVATE),
        (DataClassification.RESTRICTED, DataClassification.RESTRICTED),
    ],
)
def test_policy_denial_after_external_identification_never_calls_provider(
    policy_classification,
    classification,
):
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway, PolicyDeniedError

    class Provider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "external"

        def __init__(self):
            self.calls = 0

        def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("provider must not receive denied data")

    provider = Provider()
    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=policy_classification,
            allowed_provider_ids=("provider-a",),
        ),
        external_answer_provider=provider,
        external_api_key="secret-key",
    )

    with pytest.raises(PolicyDeniedError):
        gateway.generate(
            question="contact dev@example.com",
            chunks=(
                RetrievedChunk(
                    chunk_id="chunk-1",
                    document_version_id="version-1",
                    content="private evidence",
                    fused_rank=1,
                ),
            ),
            classification=classification,
        )

    assert provider.calls == 0
    assert gateway.audits == []


@pytest.mark.parametrize(
    ("policy_classification", "classification"),
    [
        (DataClassification.PUBLIC, DataClassification.PRIVATE),
        (DataClassification.PUBLIC, DataClassification.RESTRICTED),
        (DataClassification.PRIVATE, DataClassification.PRIVATE),
        (DataClassification.RESTRICTED, DataClassification.RESTRICTED),
    ],
)
def test_stream_policy_denial_after_external_identification_never_calls_provider(
    policy_classification,
    classification,
):
    import asyncio

    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway, PolicyDeniedError

    class Provider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "external"

        def __init__(self):
            self.calls = 0

        async def generate_stream(self, **_kwargs):
            self.calls += 1
            yield "unredacted private evidence"

    provider = Provider()
    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=policy_classification,
            allowed_provider_ids=("provider-a",),
        ),
        external_answer_provider=provider,
        external_api_key="secret-key",
    )
    stream = gateway.generate_stream(
        question="contact dev@example.com",
        chunks=(
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                content="private evidence",
                fused_rank=1,
            ),
        ),
        classification=classification,
    )

    async def collect():
        return [piece async for piece in stream]

    with pytest.raises(PolicyDeniedError):
        asyncio.run(collect())

    assert provider.calls == 0
    assert stream.result is None
    assert gateway.audits == []


@pytest.mark.parametrize("streaming", [False, True])
def test_redaction_failure_never_calls_external_answer_provider(
    monkeypatch,
    streaming,
):
    import asyncio

    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.answer import AnswerResult
    from backend.app.rag.llm_gateway import LlmGateway, PolicyDeniedError

    def fail_redaction(_text):
        raise RuntimeError("redaction failed")

    monkeypatch.setattr(gateway_module, "scan_and_redact", fail_redaction)

    class Provider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "external"

        def __init__(self):
            self.calls = []

        def generate(self, **_kwargs):
            self.calls.append("generate")
            return AnswerResult(
                text="unredacted answer",
                status="completed",
                citation_chunk_ids=(),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
            )

        async def generate_stream(self, **_kwargs):
            self.calls.append("generate_stream")
            yield "unredacted answer"

    provider = Provider()
    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=DataClassification.PUBLIC,
            allowed_provider_ids=("provider-a",),
        ),
        external_answer_provider=provider,
        external_api_key="secret-key",
    )

    if streaming:
        stream = gateway.generate_stream(
            question="contact dev@example.com",
            chunks=(),
            classification=DataClassification.PUBLIC,
        )

        async def collect():
            return [piece async for piece in stream]

        with pytest.raises(PolicyDeniedError):
            asyncio.run(collect())
        assert stream.result is None
    else:
        with pytest.raises(PolicyDeniedError):
            gateway.generate(
                question="contact dev@example.com",
                chunks=(),
                classification=DataClassification.PUBLIC,
            )

    assert provider.calls == []
    assert gateway.audits == []


def test_answer_provider_runtime_failure_normalizes_to_model_unavailable():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway, ModelUnavailableError

    error = RuntimeError("provider transport failed")

    class Provider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "external"

        def generate(self, **_kwargs):
            raise error

    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=DataClassification.PUBLIC,
            allowed_provider_ids=("provider-a",),
        ),
        external_answer_provider=Provider(),
        external_api_key="secret-key",
    )

    with pytest.raises(ModelUnavailableError, match="Answer provider failed"):
        gateway.generate(
            question="public question",
            chunks=(),
            classification=DataClassification.PUBLIC,
        )

    assert gateway.audits == []


def test_answer_provider_adapter_error_preserves_status_and_code():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway

    error = ProviderAdapterError(
        502,
        "MODEL_AUTH_FAILED",
        "Upstream rejected the provider API Key.",
    )

    class Provider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "external"

        def generate(self, **_kwargs):
            raise error

    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=DataClassification.PUBLIC,
            allowed_provider_ids=("provider-a",),
        ),
        external_answer_provider=Provider(),
        external_api_key="secret-key",
    )

    with pytest.raises(ProviderAdapterError) as caught:
        gateway.generate(
            question="public question",
            chunks=(),
            classification=DataClassification.PUBLIC,
        )

    assert caught.value is error
    assert caught.value.status_code == 502
    assert caught.value.code == "MODEL_AUTH_FAILED"
    assert gateway.audits == []


def test_external_answer_provider_requires_non_empty_allow_list():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway, PolicyDeniedError

    class Provider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "external"

        def __init__(self):
            self.calls = 0

        def generate(self, **_kwargs):
            self.calls += 1
            raise AssertionError("provider must not be called")

    provider = Provider()
    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=DataClassification.PUBLIC,
            allowed_provider_ids=(),
        ),
        external_answer_provider=provider,
        external_api_key="secret-key",
    )

    with pytest.raises(PolicyDeniedError):
        gateway.generate(
            question="public question",
            chunks=(),
            classification=DataClassification.PUBLIC,
        )

    assert provider.calls == 0
    assert gateway.audits == []


def test_external_required_restricted_data_returns_policy_denial():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway, PolicyDeniedError

    class UnusedProvider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "external"

        def generate(self, **_kwargs):
            raise AssertionError("provider must not be called for denied data")

    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_required",
            requested_classification=DataClassification.RESTRICTED,
        ),
        external_answer_provider=UnusedProvider(),
    )

    with pytest.raises(PolicyDeniedError):
        gateway.generate(
            question="production password",
            chunks=(
                RetrievedChunk(
                    chunk_id="chunk-1",
                    document_version_id="version-1",
                    content="restricted evidence",
                    fused_rank=1,
                ),
            ),
            classification=DataClassification.RESTRICTED,
        )
