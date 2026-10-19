# Required LLM Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require every Q&A answer to use an explicitly selected, configured LLM provider/model and remove `ExtractiveLocalGenerator` from production and tests.

**Architecture:** Add normalized provider adapters for OpenAI Responses, OpenAI Chat Completions and Anthropic Messages. Resolve and validate `provider_id`/`model_id` before generation, inject the selected adapter into `LlmGateway`, and expose provider/model selectors in the chat page with the send button disabled until both are selected.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, httpx, Fernet secret storage, Vue 3, Pinia, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-20-required-llm-provider-design.md`

## Global Constraints

- Q&A requests must include non-empty `provider_id` and `model_id`.
- The send button must be disabled when provider, model, knowledge base or question is missing.
- `ExtractiveLocalGenerator` must not exist in production code or be exported from the answer package.
- No fallback may generate an answer from raw chunks when a provider is unavailable.
- Supported provider formats are exactly `openai_responses`, `openai_chat_completions`, and `anthropic_messages`.
- API Keys are encrypted at rest and never returned by API responses.
- Provider/model resolution must validate team access, active status, model membership, key availability, policy allow-list and data classification.
- Stream and non-stream Q&A must use the same selected provider/model.
- Trace/model audit records must contain the real provider and model identifiers.
- Existing API Key, provider, Trace and model-list changes in the worktree must be preserved.

---

### Task 1: Provider Adapters and Answer Normalization

**Files:**
- Create: `backend/app/rag/llm_gateway/providers.py`
- Modify: `backend/app/rag/answer/service.py`
- Test: `backend/tests/providers/test_adapters.py`

**Interfaces:**
- Consumes: `RetrievedChunk`, `AnswerResult`, `AnswerStream`, `AnswerAccumulator`.
- Produces:
  - `LlmProviderAdapter` protocol/class with `provider_id: str`, `model_id: str`, `route: str`, `generate(question, chunks, max_chunks) -> AnswerResult`, `generate_stream(question, chunks, max_chunks) -> AnswerStream`.
  - `build_provider_adapter(provider_type, provider_id, base_url, api_key, model_id, transport=None) -> LlmProviderAdapter`.

- [ ] **Step 1: Write failing adapter tests**

```python
# backend/tests/providers/test_adapters.py
import httpx
from backend.app.rag.domain.models import RetrievedChunk
from backend.app.rag.llm_gateway.providers import (
    AnthropicMessagesAdapter,
    OpenAIChatCompletionsAdapter,
    OpenAIResponsesAdapter,
)


def _chunk():
    return RetrievedChunk(
        chunk_id="chunk-1",
        document_version_id="dv-1",
        content="Virtual threads are lightweight threads.",
        fused_rank=1,
    )


def test_chat_completions_adapter_maps_response_to_answer_result():
    def handler(request):
        assert str(request.url) == "https://gateway.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(200, json={"choices": [{"message": {"content": "Use virtual threads [c1]."}}]})

    adapter = OpenAIChatCompletionsAdapter(
        provider_id="provider-1",
        base_url="https://gateway.example",
        api_key="sk-test",
        model_id="gpt-test",
        transport=httpx.MockTransport(handler),
    )
    result = adapter.generate(question="What?", chunks=[_chunk()], max_chunks=1)
    assert result.text == "Use virtual threads [c1]."
    assert result.citation_chunk_ids == ("chunk-1",)
    assert result.model_id == "gpt-test"


def test_anthropic_adapter_uses_message_headers_and_response_text():
    def handler(request):
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "sk-ant"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Threads are cheap [c1]."}]})

    adapter = AnthropicMessagesAdapter(
        provider_id="provider-2",
        base_url="https://api.anthropic.com",
        api_key="sk-ant",
        model_id="claude-test",
        transport=httpx.MockTransport(handler),
    )
    result = adapter.generate(question="What?", chunks=[_chunk()], max_chunks=1)
    assert result.text == "Threads are cheap [c1]."
    assert result.citation_chunk_ids == ("chunk-1",)
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `.venv/bin/pytest -q backend/tests/providers/test_adapters.py`

Expected: FAIL because `backend.app.rag.llm_gateway.providers` does not exist.

- [ ] **Step 3: Implement adapters and citation parsing**

Add the three adapter classes and `build_provider_adapter`. Use a shared prompt that labels each chunk as `[c1]`, `[c2]` and instructs the model to cite only those labels. Parse `[cN]` from generated text and map citations back to chunk IDs. If the provider returns text without citation markers, use all supplied context chunks as citations and set `degraded=True`.

Also add `answer_result_from_text()` and `answer_stream_from_pieces()` helpers in `backend/app/rag/answer/service.py` so all adapters produce the same normalized stream/result.

- [ ] **Step 4: Add stream parser tests**

```python
@pytest.mark.parametrize(
    ("adapter_type", "chunk_text"),
    [
        ("responses", 'event: response.output_text.delta\ndata: {"delta":"hello"}\n\n'),
        ("chat", 'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'),
        ("anthropic", 'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hello"}}\n\n'),
    ],
)
def test_stream_parsers_emit_normalized_text(adapter_type, chunk_text):
    assert parse_provider_stream_chunk(adapter_type, chunk_text) == "hello"
```

- [ ] **Step 5: Run adapter tests**

Run: `.venv/bin/pytest -q backend/tests/providers/test_adapters.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/rag/llm_gateway/providers.py backend/app/rag/answer/service.py backend/tests/providers/test_adapters.py
git commit -m "feat: add normalized llm provider adapters"
```

### Task 2: Remove Extractive Answer Generation from Gateway

**Files:**
- Modify: `backend/app/rag/answer/service.py`
- Modify: `backend/app/rag/answer/__init__.py`
- Modify: `backend/app/rag/llm_gateway/gateway.py`
- Modify: `backend/tests/core/test_llm_policy.py`
- Modify: `backend/tests/api/test_chat_retrieval_generation.py`

**Interfaces:**
- Consumes: `LlmProviderAdapter` from Task 1.
- Produces: `LlmGateway` requiring `external_answer_provider`; no default answer provider.

- [ ] **Step 1: Write failing no-provider test**

```python
def test_gateway_rejects_answer_generation_without_provider():
    gateway = LlmGateway(decision=_local_decision())
    with pytest.raises(ModelUnavailableError, match="No answer provider"):
        gateway.generate(question="Question", chunks=[], max_chunks=1)
```

- [ ] **Step 2: Run test and confirm failure**

Run: `.venv/bin/pytest -q backend/tests/core/test_llm_policy.py -k without_provider`

Expected: FAIL because the gateway currently creates `ExtractiveLocalGenerator`.

- [ ] **Step 3: Remove `ExtractiveLocalGenerator`**

Delete the class from `service.py` and the export from `answer/__init__.py`. Change `LlmGateway.__init__` to store `self._answer_provider = external_answer_provider`, and raise `ModelUnavailableError("No answer provider is configured.")` in both generation methods when it is missing. Delete all local answer fallback branches.

- [ ] **Step 4: Update obsolete tests**

Replace assertions for `extractive-local` and `local_extractive_fallback` with an injected fake provider asserting `provider_id`, `model_id`, and response text. Remove tests that expect local extraction.

- [ ] **Step 5: Run the focused suite**

Run: `.venv/bin/pytest -q backend/tests/core/test_llm_policy.py backend/tests/api/test_chat_retrieval_generation.py`

Expected: PASS with no references to `ExtractiveLocalGenerator`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/rag/answer/service.py backend/app/rag/answer/__init__.py backend/app/rag/llm_gateway/gateway.py backend/tests/core/test_llm_policy.py backend/tests/api/test_chat_retrieval_generation.py
git commit -m "refactor: require an answer provider in llm gateway"
```

### Task 3: Resolve the Requested Provider and Model

**Files:**
- Create: `backend/app/modules/providers/resolution.py`
- Modify: `backend/app/api/v1/schemas.py`
- Modify: `backend/app/api/v1/chats.py`
- Modify: `backend/app/api/v1/model_policy.py`
- Test: `backend/tests/api/test_chat_provider_selection.py`

**Interfaces:**
- Consumes: decrypted `ModelProvider`, effective `ModelPolicyDecision`, provider type adapters.
- Produces:
  - `resolve_provider(session, team_id, provider_id, model_id, decision, settings) -> ResolvedProvider`.
  - `AskRequest.provider_id: str`, `AskRequest.model_id: str`.
  - Provider views include `has_api_key: bool`.

- [ ] **Step 1: Write failing API validation tests**

```python
def test_chat_ask_requires_provider_and_model(api_client, admin_headers):
    team, chat = _setup_chat(api_client, admin_headers)
    response = api_client.post(
        "/api/v1/chats/ask",
        json={"team_id": team["id"], "chat_id": chat["id"], "question": "Q?", "stream": False},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_chat_ask_rejects_model_not_configured_on_provider(api_client, admin_headers):
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
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `.venv/bin/pytest -q backend/tests/api/test_chat_provider_selection.py`

Expected: FAIL because the fields and resolver do not exist.

- [ ] **Step 3: Implement resolution**

Resolve provider by ID, validate `active`, team/global scope, model membership, non-empty encrypted API key, policy allow-list and `assert_external_call_allowed`. Decrypt the key only at the final adapter construction boundary. Raise the exact error codes from the spec.

- [ ] **Step 4: Inject the adapter into both stream and non-stream paths**

At both `_build_gateway` call sites in `chats.py`, resolve the provider/model and call `build_provider_adapter`. Pass it as `external_answer_provider` with `external_api_key` equal to the decrypted key. Record the real provider/model in Trace and `ModelCall`.

- [ ] **Step 5: Add provider selection API tests**

Assert successful non-stream and stream generation with a fake provider, real provider mask remains hidden, and no answer is generated without a provider.

- [ ] **Step 6: Run focused tests**

Run: `.venv/bin/pytest -q backend/tests/api/test_chat_provider_selection.py backend/tests/api/test_chat_retrieval_generation.py backend/tests/api/test_provider_model_discovery.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/modules/providers/resolution.py backend/app/api/v1/schemas.py backend/app/api/v1/chats.py backend/app/api/v1/model_policy.py backend/tests/api/test_chat_provider_selection.py
git commit -m "feat: require selected llm provider for chat"
```

### Task 4: Add Provider and Model Selectors to the Chat Page

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/views/ChatPage.vue`
- Modify: `frontend/src/views/ChatPage.spec.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: `GET /providers`, `GET /model-policy`, `AskChatInput`.
- Produces: selected `providerId`, `modelId`, disabled send button when either is empty, and request payload with both fields.

- [ ] **Step 1: Write failing chat-page tests**

```typescript
it('keeps send disabled until provider and model are selected', async () => {
  const { wrapper } = await mountPage('/chat')
  expect(wrapper.get('[data-testid="send-message"]').attributes('disabled')).toBeDefined()
  await wrapper.get('[data-testid="chat-provider-select"]').setValue('provider-1')
  await wrapper.get('[data-testid="chat-model-select"]').setValue('gpt-a')
  expect(wrapper.get('[data-testid="send-message"]').attributes('disabled')).toBeUndefined()
})

it('includes provider and model in the ask request', async () => {
  const { wrapper } = await mountPage('/chat')
  await wrapper.get('[data-testid="chat-provider-select"]').setValue('provider-1')
  await wrapper.get('[data-testid="chat-model-select"]').setValue('gpt-a')
  await wrapper.get('[data-testid="question-input"]').setValue('Question')
  await wrapper.get('[data-testid="send-message"]').trigger('click')
  expect(askMock).toHaveBeenCalledWith(expect.objectContaining({ provider_id: 'provider-1', model_id: 'gpt-a' }))
})
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `npm test -- --run src/views/ChatPage.spec.ts`

Expected: FAIL because the selectors and request fields do not exist.

- [ ] **Step 3: Implement selectors and disabled state**

Load active providers with `has_api_key=true`, intersect with policy-allowed provider IDs, and populate model options from the selected provider. Leave both blank initially. Include provider/model in `canSubmit`. Use `data-testid="chat-provider-select"`, `data-testid="chat-model-select"`, and `data-testid="send-message"`.

- [ ] **Step 4: Run frontend tests and build**

Run: `npm test -- --run src/views/ChatPage.spec.ts && npm run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/api/client.ts frontend/src/views/ChatPage.vue frontend/src/views/ChatPage.spec.ts frontend/src/styles.css
git commit -m "feat: require provider and model selection in chat"
```

### Task 5: Update API Contract and Remove Extractive Examples

**Files:**
- Modify: `docs/api/api-contract.md`
- Modify: `docs/api/openapi.yaml`
- Modify: `docs/product/page-map.md`
- Modify: `backend/tests/docs/test_openapi.py`

**Interfaces:**
- Consumes: implemented `provider_id`/`model_id` contract.
- Produces: machine-readable and human-readable contracts without `local-extractive` fallback.

- [ ] **Step 1: Write failing documentation tests**

```python
def test_chat_ask_requires_provider_and_model():
    schema = _spec()["components"]["schemas"]["AskChatBody"]
    assert "provider_id" in schema["required"]
    assert "model_id" in schema["required"]


def test_contract_has_no_extractive_fallback():
    contract = API_CONTRACT_PATH.read_text(encoding="utf-8")
    assert "local_extractive_fallback" not in contract
    assert "extractive-local" not in contract
```

- [ ] **Step 2: Update OpenAPI and API contract**

Add required `provider_id`/`model_id` fields, document provider/model selector behavior, remove extractive examples, and add `MODEL_UNAVAILABLE` behavior for missing providers. Update the page map to state that send remains disabled until both are selected.

- [ ] **Step 3: Run docs tests**

Run: `.venv/bin/pytest -q backend/tests/docs/test_openapi.py`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/api/api-contract.md docs/api/openapi.yaml docs/product/page-map.md backend/tests/docs/test_openapi.py
git commit -m "docs: require llm provider for chat"
```

### Task 6: End-to-End Provider and Browser Verification

**Files:**
- Modify: `scripts/verify_rag_e2e.py`
- Modify: `frontend/scripts/integration-smoke.mjs`
- Create: `backend/tests/e2e/test_provider_chat_flow.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: proof that stream/non-stream Q&A calls the selected provider and the UI disables send until selection.

- [ ] **Step 1: Add a fake provider E2E test**

Use a local HTTP server exposing one of the supported inference endpoints. Create a provider with the test API Key, set policy to allow it, upload a document, ask a question with `provider_id`/`model_id`, and assert the returned answer contains the fake provider text and Trace contains the provider/model.

```python
def test_chat_uses_selected_fake_provider(api_client, api_app, admin_headers, monkeypatch):
    team, chat = _setup_chat(api_client, admin_headers)
    provider = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team["id"],
            "name": "E2E Provider",
            "provider_type": "openai_chat_completions",
            "base_url": "http://fake-provider/v1",
            "api_key": "sk-e2e",
            "model_ids": ["fake-model"],
        },
        headers=admin_headers,
    ).json()["data"]
    api_client.post(
        "/api/v1/admin/model-policy/update",
        json={"mode": "external_allowed", "allowed_provider_ids": [provider["id"]]},
        headers=admin_headers,
    )
    api_client.post(
        "/api/v1/model-policy/update",
        json={
            "team_id": team["id"],
            "mode": "external_allowed",
            "allowed_provider_ids": [provider["id"]],
        },
        headers=admin_headers,
    )

    class FakeAdapter:
        provider_id = provider["id"]
        model_id = "fake-model"
        route = "fake_provider"

        def generate(self, **kwargs):
            from backend.app.rag.answer import AnswerResult

            return AnswerResult(
                text="Answer from fake provider [c1].",
                status="completed",
                citation_chunk_ids=("chunk-1",),
                model_id=self.model_id,
                route=self.route,
                degraded=False,
            )

    monkeypatch.setattr(
        chats_module,
        "build_provider_adapter",
        lambda **kwargs: FakeAdapter(),
    )

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "Question?",
            "provider_id": provider["id"],
            "model_id": "fake-model",
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["content"] == "Answer from fake provider [c1]."
    trace = api_client.get(
        "/api/v1/traces/detail",
        params={"team_id": team["id"], "trace_id": response.json()["data"]["trace_id"]},
        headers=admin_headers,
    ).json()["data"]
    assert trace["model"]["provider_id"] == provider["id"]
    assert trace["model"]["model_id"] == "fake-model"
```

- [ ] **Step 2: Add browser integration assertions**

In `integration-smoke.mjs`, open `/chat`, assert the send button is disabled, select provider and model, then assert it becomes enabled. Complete a fake-provider question and verify the answer renders.

```javascript
await page.goto(`${frontendUrl}/chat`)
await page.waitForSelector('[data-testid="chat-provider-select"]')
if (!(await page.getByTestId('send-message').isDisabled())) {
  throw new Error('send should be disabled before provider/model selection')
}
await page.selectOption('[data-testid="chat-provider-select"]', { label: 'E2E Provider' })
await page.selectOption('[data-testid="chat-model-select"]', 'fake-model')
if (await page.getByTestId('send-message').isDisabled()) {
  throw new Error('send should be enabled after provider/model selection')
}
```

- [ ] **Step 3: Run backend and frontend suites**

Run: `.venv/bin/pytest -q && cd frontend && npm test -- --run && npm run build`

Expected: all tests pass.

- [ ] **Step 4: Run browser visual verification**

Run the Playwright integration against `http://127.0.0.1:5173`, capture desktop and mobile screenshots of the chat selector state and result.

Expected: no horizontal overflow, disabled state is visibly gray, provider/model values persist through the ask flow, and no framework overlay or relevant console error appears.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_rag_e2e.py frontend/scripts/integration-smoke.mjs backend/tests/e2e/test_provider_chat_flow.py
git commit -m "test: verify required llm provider chat flow"
```

## Final Verification Gate

- [ ] `.venv/bin/pytest -q`
- [ ] `cd frontend && npm test -- --run`
- [ ] `cd frontend && npm run build`
- [ ] `.venv/bin/python -m compileall -q backend scripts`
- [ ] `git diff --check`
- [ ] `rg -n "ExtractiveLocalGenerator|extractive-local|local_extractive_fallback" backend frontend docs --glob '!docs/superpowers/**'` returns no matches.
- [ ] Real browser test proves disabled send state before provider/model selection.
- [ ] Real provider test proves selected provider/model is used in both stream and non-stream chat.
