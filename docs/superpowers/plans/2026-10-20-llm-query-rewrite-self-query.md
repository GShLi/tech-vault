# LLM Query Rewrite and Self-Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace deterministic-only QueryRewrite with an LLM-first structured rewrite that also performs native Self-Query filtering for `product` and `version_values`.

**Architecture:** Provider adapters own upstream JSON-schema/json-object/tool-use differences and return a normalized `RewriteResult`. `LlmGateway` orchestrates policy, history gating, downgrade, deterministic fallback and audit. `chats.py` applies the validated filters to `RetrievalFilters`, and `TraceRecord.rewrite` stores the complete rewrite decision.

**Tech Stack:** FastAPI, SQLAlchemy, httpx, pytest, Vue 3, TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-20-llm-query-rewrite-self-query-design.md`

## Global Constraints

- Self-Query is always enabled in this phase; do not add a toggle, policy flag or UI switch.
- LLM may extract only `product` and `version_values`.
- Self-Query uses native hard filters; do not implement score boosts, soft filters or filter relaxation.
- Hard-filtered zero results must end as `refused` / `INSUFFICIENT_EVIDENCE`.
- Reuse the provider/model selected for the answer; do not add a rewrite-model setting.
- Try `json_schema` first; downgrade once to `json_object` or prompt-only JSON, then fall back to deterministic rules.
- A valid unchanged rewrite is accepted; do not merge deterministic product/version into it.
- Only send chat history to the external LLM when `ModelPolicyDecision.allow_chat_history` is true.
- Security fields (`team_id`, `knowledge_base_ids`, `viewer_user_id`, `visibility`, `data_classification`, grants) never come from the LLM.
- Use Python 3.9-compatible annotations (`Optional`, `Dict`, `List`).
- Do not add third-party dependencies.

---

## File Structure

Create:

- `backend/app/rag/llm_gateway/contracts.py` — normalized rewrite result shared by Gateway and adapters.
- `backend/app/rag/llm_gateway/rewrite_contract.py` — JSON schema, prompt builder, parser and validation.
- `backend/app/rag/llm_gateway/self_query.py` — facet canonicalization, user precedence and dropped-filter accounting.
- `backend/tests/providers/test_rewrite_contract.py` — prompt/parser unit tests.
- `backend/tests/rag/test_self_query.py` — filter merge and canonicalization tests.
- `backend/tests/api/test_chat_self_query.py` — end-to-end API filtering tests.
- `backend/tests/api/test_trace_rewrite.py` — rewrite trace persistence and API tests.

Modify:

- `backend/app/rag/llm_gateway/providers.py` — add `rewrite()` to the protocol and all adapters.
- `backend/app/rag/llm_gateway/gateway.py` — LLM-first rewrite orchestration and fallback.
- `backend/app/rag/llm_gateway/__init__.py` — keep public exports.
- `backend/app/api/v1/chats.py` — facets, history gating, applied filters, trace and SSE.
- `backend/app/api/v1/kbs.py` — reusable readable-document facets helper.
- `backend/app/rag/retrieval/in_memory.py` — missing-field parity with ES/Qdrant.
- `backend/app/db/models.py` — `TraceRecord.rewrite`.
- `backend/app/db/session.py` — idempotent schema bridge.
- `backend/app/api/v1/traces.py` — return rewrite metadata.
- `frontend/src/types/api.ts` — trace rewrite type.
- `frontend/src/views/TraceDetailView.vue` — QueryRewrite section.
- `frontend/src/views/TraceDetailView.spec.ts` — UI tests.
- `docs/api/api-contract.md`, `docs/product/page-map.md` — API and UI contracts.

---

### Task 1: Rewrite Contract and Prompt Validation

**Files:**
- Create: `backend/app/rag/llm_gateway/contracts.py`
- Create: `backend/app/rag/llm_gateway/rewrite_contract.py`
- Create: `backend/tests/providers/test_rewrite_contract.py`
- Modify: `backend/app/rag/llm_gateway/gateway.py`
- Modify: `backend/app/rag/llm_gateway/__init__.py`

**Interfaces:**
- Produces: `RewriteResult` dataclass with `original_query`, `rewritten_query`, `changed`, `route`, `model_id`, `provider_id`, `structured_mode`, `extracted_filters`, `applied_filters`, `dropped_filters`, `fallback_reason`, `validation_error`, `context_used`, `input_tokens`, `output_tokens`, `latency_ms`.
- Produces: `QUERY_REWRITE_SCHEMA`, `REWRITE_SYSTEM_PROMPT`, `build_rewrite_prompt(...)`, `parse_rewrite_payload(...)`, `parse_rewrite_text(...)`, `RewriteValidationError`.

- [ ] **Step 1: Write failing contract tests**

```python
# backend/tests/providers/test_rewrite_contract.py
import pytest

from backend.app.rag.llm_gateway.rewrite_contract import (
    RewriteValidationError,
    build_rewrite_prompt,
    parse_rewrite_payload,
    parse_rewrite_text,
)


def test_parse_rewrite_payload_normalizes_query_and_filters():
    parsed = parse_rewrite_payload(
        {
            "rewritten_query": "  Spring   Boot 3.2 虚拟线程配置  ",
            "filters": {"product": " spring-boot ", "version_values": ["3.2", "3.2"]},
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
        ({"rewritten_query": "q", "filters": {}, "extra": 1}, "unexpected_field"),
        ({"rewritten_query": "q", "filters": {"product": None}}, "missing_field"),
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
    with pytest.raises(RewriteValidationError) as markdown:
        parse_rewrite_text('```json\n{"rewritten_query":"q","filters":{"product":null,"version_values":[]}}\n```')
    assert markdown.value.code == "markdown_not_allowed"

    with pytest.raises(RewriteValidationError) as invalid:
        parse_rewrite_text("not json")
    assert invalid.value.code == "invalid_json"


def test_build_rewrite_prompt_keeps_roles_and_limits_history():
    history = tuple(
        {"role": "user", "content": "m{0}".format(index)} for index in range(8)
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
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/providers/test_rewrite_contract.py -q
```

Expected: collection fails because `rewrite_contract.py` does not exist.

- [ ] **Step 3: Add the shared result contract**

```python
# backend/app/rag/llm_gateway/contracts.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class RewriteResult:
    original_query: str
    rewritten_query: str
    changed: bool
    route: str
    model_id: str
    provider_id: Optional[str] = None
    structured_mode: Optional[str] = None
    extracted_filters: Dict[str, Any] = field(default_factory=dict)
    applied_filters: Dict[str, Any] = field(default_factory=dict)
    dropped_filters: List[Dict[str, Any]] = field(default_factory=list)
    fallback_reason: Optional[str] = None
    validation_error: Optional[str] = None
    context_used: Dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
```

- [ ] **Step 4: Add schema, prompt and parser**

```python
# backend/app/rag/llm_gateway/rewrite_contract.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


MAX_REWRITE_CHARS = 4000
MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_CHARS = 1000
MAX_VERSION_VALUES = 5
MAX_FACET_VALUES = 200

QUERY_REWRITE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "rewritten_query": {"type": "string"},
        "filters": {
            "type": "object",
            "properties": {
                "product": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "version_values": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["product", "version_values"],
            "additionalProperties": False,
        },
    },
    "required": ["rewritten_query", "filters"],
    "additionalProperties": False,
}

REWRITE_SYSTEM_PROMPT = """You rewrite the latest user question into one self-contained search query for a technical knowledge base retrieval system, and extract only the metadata filters explicitly supported by the provided filter schema.

Rules:
- Use conversation history only to resolve references and omitted context.
- Resolve pronouns only when exactly one clear antecedent exists; otherwise keep the original question unchanged.
- Preserve the user's language, intent, entities, versions, code identifiers, error messages, and constraints.
- Add product/version filters only when they are explicit in the question or unambiguous from the recent conversation.
- Never invent facts, products, versions, or requirements.
- Do not answer, explain, translate, or split the question.
- If no rewrite is needed, return the original question unchanged.
- Return JSON only, matching the provided schema."""


class RewriteValidationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ParsedRewrite:
    rewritten_query: str
    extracted_filters: Dict[str, Any]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _message_value(item: Any, key: str) -> str:
    if isinstance(item, dict):
        value = item.get(key)
    else:
        value = getattr(item, key, None)
    return value if isinstance(value, str) else ""


def _truncate_history(history: Sequence[Any]) -> List[str]:
    lines: List[str] = []
    for item in list(history)[-MAX_HISTORY_MESSAGES:]:
        role = _message_value(item, "role").lower()
        if role not in {"user", "assistant"}:
            continue
        content = _message_value(item, "content").strip()[:MAX_HISTORY_CHARS]
        if content:
            lines.append("{0}: {1}".format(role, content))
    return lines


def build_rewrite_prompt(
    *,
    question: str,
    history: Sequence[Any] = (),
    product: Optional[str] = None,
    version_values: Sequence[str] = (),
    allowed_products: Sequence[str] = (),
    allowed_versions: Sequence[str] = (),
) -> Tuple[str, str]:
    history_lines = _truncate_history(history)
    allowed_product_values = list(allowed_products)[:MAX_FACET_VALUES]
    allowed_version_values = list(allowed_versions)[:MAX_FACET_VALUES]
    sections = [
        "Known product: {0}".format(product or "(none)"),
        "Known version: {0}".format(", ".join(version_values) or "(none)"),
        "Allowed products: {0}".format(
            json.dumps(allowed_product_values, ensure_ascii=False)
        ),
        "Allowed versions: {0}".format(
            json.dumps(allowed_version_values, ensure_ascii=False)
        ),
        "Required JSON shape:\n{0}".format(
            json.dumps(QUERY_REWRITE_SCHEMA, ensure_ascii=False)
        ),
        "Conversation history:\n{0}".format(
            "\n".join(history_lines) if history_lines else "(none)"
        ),
        "Latest question:\n{0}".format(question.strip()),
    ]
    return REWRITE_SYSTEM_PROMPT, "\n\n".join(sections)


def parse_rewrite_payload(payload: Any) -> ParsedRewrite:
    if not isinstance(payload, dict):
        raise RewriteValidationError("invalid_json")
    if set(payload) != {"rewritten_query", "filters"}:
        raise RewriteValidationError(
            "unexpected_field" if set(payload) - {"rewritten_query", "filters"} else "missing_field"
        )
    rewritten_query = payload.get("rewritten_query")
    if not isinstance(rewritten_query, str):
        raise RewriteValidationError("invalid_query_type")
    rewritten_query = _normalize_text(rewritten_query)
    if not rewritten_query or len(rewritten_query) > MAX_REWRITE_CHARS:
        raise RewriteValidationError("invalid_query_length")

    filters = payload.get("filters")
    if not isinstance(filters, dict):
        raise RewriteValidationError("invalid_filters_type")
    if set(filters) != {"product", "version_values"}:
        raise RewriteValidationError(
            "unexpected_field" if set(filters) - {"product", "version_values"} else "missing_field"
        )
    product = filters.get("product")
    if product is not None and not isinstance(product, str):
        raise RewriteValidationError("invalid_filter_type")
    product = _normalize_text(product) if isinstance(product, str) else None
    if product == "":
        product = None

    raw_versions = filters.get("version_values")
    if not isinstance(raw_versions, list) or any(
        not isinstance(value, str) for value in raw_versions
    ):
        raise RewriteValidationError("invalid_filter_type")
    seen = set()
    versions = []
    for value in raw_versions:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            versions.append(normalized)
    versions = versions[:MAX_VERSION_VALUES]
    return ParsedRewrite(
        rewritten_query=rewritten_query,
        extracted_filters={"product": product, "version_values": versions},
    )


def parse_rewrite_text(text: str) -> ParsedRewrite:
    stripped = text.strip()
    if stripped.startswith("```"):
        raise RewriteValidationError("markdown_not_allowed")
    try:
        payload = json.loads(stripped)
    except (TypeError, json.JSONDecodeError) as error:
        raise RewriteValidationError("invalid_json") from error
    return parse_rewrite_payload(payload)
```

- [ ] **Step 5: Move `RewriteResult` imports without breaking public exports**

In `backend/app/rag/llm_gateway/gateway.py`, remove the local `RewriteResult` dataclass and
the now-unused `field` import, then import:

```python
from backend.app.rag.llm_gateway.contracts import RewriteResult
```

Keep `RewriteResult` exported from `backend/app/rag/llm_gateway/__init__.py`.

- [ ] **Step 6: Run contract tests and existing gateway tests**

```bash
.venv/bin/python -m pytest backend/tests/providers/test_rewrite_contract.py backend/tests/core/test_llm_policy.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/rag/llm_gateway/contracts.py backend/app/rag/llm_gateway/rewrite_contract.py backend/app/rag/llm_gateway/gateway.py backend/app/rag/llm_gateway/__init__.py backend/tests/providers/test_rewrite_contract.py
git commit -m "feat: add structured rewrite contract"
```

---

### Task 2: Chat Completions Structured Rewrite and Downgrade

**Files:**
- Modify: `backend/app/rag/llm_gateway/providers.py`
- Modify: `backend/tests/providers/test_adapters.py`

**Interfaces:**
- Consumes: `RewriteResult`, `QUERY_REWRITE_SCHEMA`, `build_rewrite_prompt`, `parse_rewrite_text`.
- Produces: `LlmProviderAdapter.rewrite(...) -> RewriteResult`, `ProviderAdapterError.http_status`, `ProviderAdapterError.upstream_code`, `ProviderAdapterError.upstream_param`.

- [ ] **Step 1: Add failing Chat Completions tests**

```python
# append to backend/tests/providers/test_adapters.py
def test_chat_completions_rewrite_uses_json_schema():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["name"] == "query_rewrite"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["messages"][0]["role"] == "system"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "rewritten_query": "Spring Boot 3.2 如何开启虚拟线程？",
                                    "filters": {
                                        "product": "spring-boot",
                                        "version_values": ["3.2"],
                                    },
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 120, "completion_tokens": 18},
            },
        )

    adapter = OpenAIChatCompletionsAdapter(
        "provider-1",
        "https://gateway.example",
        "sk-test",
        "model-test",
        transport=httpx.MockTransport(handler),
    )
    result = adapter.rewrite(
        question="它怎么开启？",
        history=({"role": "user", "content": "Spring Boot 3.2 虚拟线程"},),
        product=None,
        version_values=(),
        allowed_products=("spring-boot",),
        allowed_versions=("3.2",),
    )

    assert result.structured_mode == "json_schema"
    assert result.rewritten_query == "Spring Boot 3.2 如何开启虚拟线程？"
    assert result.extracted_filters == {
        "product": "spring-boot",
        "version_values": ["3.2"],
    }
    assert result.input_tokens == 120
    assert result.output_tokens == 18
    assert len(calls) == 1


def test_chat_completions_rewrite_downgrades_to_json_object_once():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "type": "invalid_request_error",
                        "param": "response_format",
                        "message": "response_format json_schema is unsupported",
                    }
                },
            )
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "rewritten_query": "原问题",
                                    "filters": {
                                        "product": None,
                                        "version_values": [],
                                    },
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    adapter = OpenAIChatCompletionsAdapter(
        "provider-1",
        "https://gateway.example",
        "sk-test",
        "model-test",
        transport=httpx.MockTransport(handler),
    )
    result = adapter.rewrite(
        question="原问题",
        allowed_products=(),
        allowed_versions=(),
    )

    assert result.structured_mode == "json_object"
    assert len(calls) == 2


def test_chat_completions_rewrite_rejects_invalid_json():
    adapter = OpenAIChatCompletionsAdapter(
        "provider-1",
        "https://gateway.example",
        "sk-test",
        "model-test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "not json"}}]},
            )
        ),
    )

    with pytest.raises(ProviderAdapterError) as error:
        adapter.rewrite(question="q")

    assert error.value.code == "MODEL_RESPONSE_INVALID"
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/providers/test_adapters.py -q -k rewrite
```

Expected: FAIL because adapters have no `rewrite`.

- [ ] **Step 3: Extend provider errors and add base rewrite helpers**

```python
# backend/app/rag/llm_gateway/providers.py
class LlmProviderAdapter(Protocol):
    provider_id: str
    model_id: str
    route: str

    def generate(self, *, question, chunks, max_chunks=8) -> AnswerResult: ...

    def generate_stream(
        self, *, question, chunks, max_chunks=8
    ) -> AnswerStream: ...

    def rewrite(
        self,
        *,
        question: str,
        history: Sequence[Any] = (),
        product: Optional[str] = None,
        version_values: Sequence[str] = (),
        allowed_products: Sequence[str] = (),
        allowed_versions: Sequence[str] = (),
    ) -> RewriteResult: ...


class ProviderAdapterError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        http_status: Optional[int] = None,
        upstream_code: Optional[str] = None,
        upstream_param: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.http_status = http_status
        self.upstream_code = upstream_code
        self.upstream_param = upstream_param


def is_structured_output_unsupported(error: ProviderAdapterError) -> bool:
    if error.http_status not in {400, 422}:
        return False
    marker_text = " ".join(
        value
        for value in (
            error.upstream_code,
            error.upstream_param,
            str(error),
        )
        if value
    ).lower()
    return any(
        marker in marker_text
        for marker in (
            "response_format",
            "json_schema",
            "json_object",
            "text.format",
            "tool_choice",
            "unsupported",
            "unknown parameter",
        )
    )
```

Update `_raise_for_response` to retain non-secret error metadata:

```python
def _error_details(response: httpx.Response):
    try:
        payload = response.json()
    except ValueError:
        return None, None
    if not isinstance(payload, dict):
        return None, None
    error = payload.get("error")
    if not isinstance(error, dict):
        error = payload
    code = error.get("code") or error.get("type")
    param = error.get("param")
    message = str(error.get("message") or "").lower()
    if param is None:
        for marker in (
            "response_format",
            "json_schema",
            "json_object",
            "text.format",
            "tool_choice",
            "tools",
        ):
            if marker in message:
                param = marker
                break
    return (
        str(code) if code is not None else None,
        str(param) if param is not None else None,
    )


def _raise_for_response(response: httpx.Response) -> None:
    if response.status_code in {401, 403}:
        raise ProviderAdapterError(
            502,
            "MODEL_AUTH_FAILED",
            "Upstream rejected the provider API Key.",
            http_status=response.status_code,
        )
    if response.status_code >= 400:
        upstream_code, upstream_param = _error_details(response)
        raise ProviderAdapterError(
            503,
            "MODEL_UNAVAILABLE",
            "Upstream model request failed with HTTP {0}.".format(
                response.status_code
            ),
            http_status=response.status_code,
            upstream_code=upstream_code,
            upstream_param=upstream_param,
        )
```

Add base helpers:

```python
    def _post_json(
        self,
        payload: Dict[str, Any],
        *,
        timeout: float,
    ) -> Dict[str, Any]:
        try:
            with httpx.Client(
                timeout=timeout,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post(
                    self._url,
                    headers=self._headers(stream=False),
                    json=payload,
                )
            _raise_for_response(response)
            return _safe_json(response)
        except Exception as error:
            normalized = self._provider_error(error)
            if normalized is error:
                raise
            raise normalized

    def rewrite(
        self,
        *,
        question: str,
        history: Sequence[Any] = (),
        product: Optional[str] = None,
        version_values: Sequence[str] = (),
        allowed_products: Sequence[str] = (),
        allowed_versions: Sequence[str] = (),
    ) -> RewriteResult:
        started = time.perf_counter()
        history = tuple(history)
        allowed_products = tuple(allowed_products)
        allowed_versions = tuple(allowed_versions)
        system_prompt, user_prompt = build_rewrite_prompt(
            question=question,
            history=history,
            product=product,
            version_values=version_values,
            allowed_products=allowed_products,
            allowed_versions=allowed_versions,
        )
        attempts = self._rewrite_attempts(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        unsupported_error = None
        for index, (mode, payload) in enumerate(attempts):
            try:
                response_payload = self._post_json(payload, timeout=10.0)
                parsed = self._parse_rewrite_response(mode, response_payload)
                input_tokens, output_tokens = self._rewrite_usage(response_payload)
                return RewriteResult(
                    original_query=question,
                    rewritten_query=parsed.rewritten_query,
                    changed=parsed.rewritten_query != question.strip(),
                    route=self.route,
                    model_id=self.model_id,
                    provider_id=self.provider_id,
                    structured_mode=mode,
                    extracted_filters=parsed.extracted_filters,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    context_used={
                        "history_messages": len(history),
                        "product": product,
                        "version_values": list(version_values),
                        "allowed_products": len(allowed_products),
                        "allowed_versions": len(allowed_versions),
                    },
                )
            except RewriteValidationError as error:
                raise ProviderAdapterError(
                    502,
                    "MODEL_RESPONSE_INVALID",
                    "Rewrite response was invalid.",
                    upstream_code=error.code,
                ) from error
            except ProviderAdapterError as error:
                if index == 0 and is_structured_output_unsupported(error):
                    unsupported_error = error
                    continue
                raise
        raise unsupported_error or ProviderAdapterError(
            502,
            "MODEL_RESPONSE_INVALID",
            "Rewrite response was invalid.",
        )

    def _rewrite_attempts(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> List[tuple[str, Dict[str, Any]]]:
        raise NotImplementedError

    def _parse_rewrite_response(
        self,
        mode: str,
        payload: Dict[str, Any],
    ) -> ParsedRewrite:
        raise NotImplementedError

    def _rewrite_usage(self, payload: Dict[str, Any]) -> tuple[int, int]:
        return 0, 0
```

- [ ] **Step 4: Implement Chat Completions hooks**

```python
class OpenAIChatCompletionsAdapter(_HttpProviderAdapter):
    route = "openai_chat_completions"
    _stream_type = "chat"

    def _rewrite_attempts(self, *, system_prompt, user_prompt):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        strict = {
            "model": self.model_id,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "query_rewrite",
                    "strict": True,
                    "schema": QUERY_REWRITE_SCHEMA,
                },
            },
        }
        weak = {
            "model": self.model_id,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        return [("json_schema", strict), ("json_object", weak)]

    def _parse_rewrite_response(self, mode, payload):
        return parse_rewrite_text(self._response_text(payload))

    def _rewrite_usage(self, payload):
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return 0, 0
        return (
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )
```

Add `time` and the new imports:

```python
import time
from backend.app.rag.llm_gateway.contracts import RewriteResult
from backend.app.rag.llm_gateway.rewrite_contract import (
    QUERY_REWRITE_SCHEMA,
    ParsedRewrite,
    RewriteValidationError,
    build_rewrite_prompt,
    parse_rewrite_text,
)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/providers/test_adapters.py -q -k "rewrite or chat_completions"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/rag/llm_gateway/providers.py backend/tests/providers/test_adapters.py
git commit -m "feat: add structured rewrite for chat completions"
```

---

### Task 3: Responses and Anthropic Structured Rewrite

**Files:**
- Modify: `backend/app/rag/llm_gateway/providers.py`
- Modify: `backend/tests/providers/test_adapters.py`

**Interfaces:**
- Produces: `OpenAIResponsesAdapter._rewrite_attempts()` and `_parse_rewrite_response()`.
- Produces: `AnthropicMessagesAdapter._rewrite_attempts()` and `_parse_rewrite_response()`.

- [ ] **Step 1: Add failing tests**

```python
def test_responses_rewrite_uses_text_format_and_downgrades():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            assert body["text"]["format"]["type"] == "json_schema"
            return httpx.Response(
                400,
                json={
                    "error": {
                        "type": "invalid_request_error",
                        "param": "text.format",
                        "message": "json_schema unsupported",
                    }
                },
            )
        assert body["text"]["format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "output_text": json.dumps(
                    {
                        "rewritten_query": "Virtual threads",
                        "filters": {"product": None, "version_values": []},
                    }
                ),
                "usage": {"input_tokens": 30, "output_tokens": 8},
            },
        )

    adapter = OpenAIResponsesAdapter(
        "provider-1",
        "https://gateway.example",
        "sk-test",
        "model-test",
        transport=httpx.MockTransport(handler),
    )
    result = adapter.rewrite(question="Virtual threads")

    assert result.structured_mode == "json_object"
    assert result.input_tokens == 30
    assert len(calls) == 2


def test_anthropic_rewrite_uses_forced_tool_use():
    def handler(request):
        body = json.loads(request.content)
        assert body["tool_choice"] == {
            "type": "tool",
            "name": "submit_query_rewrite",
        }
        assert body["tools"][0]["input_schema"]["properties"]["filters"]
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "tool_use",
                        "name": "submit_query_rewrite",
                        "input": {
                            "rewritten_query": "Elasticsearch 8.13 默认分片数",
                            "filters": {
                                "product": "elasticsearch",
                                "version_values": ["8.13"],
                            },
                        },
                    }
                ],
                "usage": {"input_tokens": 44, "output_tokens": 12},
            },
        )

    adapter = AnthropicMessagesAdapter(
        "provider-1",
        "https://gateway.example",
        "sk-test",
        "model-test",
        transport=httpx.MockTransport(handler),
    )
    result = adapter.rewrite(
        question="它默认几个分片？",
        history=({"role": "user", "content": "Elasticsearch 8.13"},),
        allowed_products=("elasticsearch",),
        allowed_versions=("8.13",),
    )

    assert result.structured_mode == "tool_use"
    assert result.extracted_filters["product"] == "elasticsearch"
    assert result.output_tokens == 12
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/providers/test_adapters.py -q -k "responses_rewrite or anthropic_rewrite"
```

Expected: FAIL because the adapters do not implement `_rewrite_attempts`.

- [ ] **Step 3: Implement Responses hooks**

```python
class OpenAIResponsesAdapter(_HttpProviderAdapter):
    route = "openai_responses"
    _stream_type = "responses"

    def _rewrite_attempts(self, *, system_prompt, user_prompt):
        prompt = "{0}\n\n{1}".format(system_prompt, user_prompt)
        strict = {
            "model": self.model_id,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "query_rewrite",
                    "strict": True,
                    "schema": QUERY_REWRITE_SCHEMA,
                }
            },
        }
        weak = {
            "model": self.model_id,
            "input": prompt,
            "text": {"format": {"type": "json_object"}},
        }
        return [("json_schema", strict), ("json_object", weak)]

    def _parse_rewrite_response(self, mode, payload):
        return parse_rewrite_text(self._response_text(payload))

    def _rewrite_usage(self, payload):
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return 0, 0
        return (
            int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0),
        )
```

- [ ] **Step 4: Implement Anthropic hooks**

```python
class AnthropicMessagesAdapter(_HttpProviderAdapter):
    route = "anthropic_messages"
    _stream_type = "anthropic"

    def _rewrite_attempts(self, *, system_prompt, user_prompt):
        prompt = "{0}\n\n{1}".format(system_prompt, user_prompt)
        strict = {
            "model": self.model_id,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [
                {
                    "name": "submit_query_rewrite",
                    "description": "Submit the rewritten query and metadata filters.",
                    "input_schema": QUERY_REWRITE_SCHEMA,
                }
            ],
            "tool_choice": {
                "type": "tool",
                "name": "submit_query_rewrite",
            },
        }
        weak = {
            "model": self.model_id,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
        }
        return [("tool_use", strict), ("prompt_json", weak)]

    def _parse_rewrite_response(self, mode, payload):
        if mode == "tool_use":
            content = payload.get("content")
            if isinstance(content, list):
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_use"
                        and block.get("name") == "submit_query_rewrite"
                    ):
                        return parse_rewrite_payload(block.get("input"))
            raise RewriteValidationError("missing_tool_use")
        return parse_rewrite_text(self._response_text(payload))

    def _rewrite_usage(self, payload):
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return 0, 0
        return (
            int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0),
        )
```

Add `parse_rewrite_payload` to the `rewrite_contract` imports.

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/providers/test_adapters.py -q -k rewrite
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/rag/llm_gateway/providers.py backend/tests/providers/test_adapters.py
git commit -m "feat: add structured rewrite for responses and anthropic"
```

---

### Task 4: Gateway Orchestration and Self-Query Filter Merge

**Files:**
- Create: `backend/app/rag/llm_gateway/self_query.py`
- Create: `backend/tests/rag/test_self_query.py`
- Modify: `backend/app/rag/llm_gateway/gateway.py`
- Modify: `backend/tests/core/test_llm_policy.py`

**Interfaces:**
- Produces: `SelfQueryApplication` with `applied_filters` and `dropped_filters`.
- Produces: `apply_self_query_filters(*, extracted_filters, explicit_product, explicit_versions, allowed_products, allowed_versions)`.
- Produces: `LlmGateway.rewrite(..., allowed_products, allowed_versions, allow_chat_history)`.

- [ ] **Step 1: Write failing Self-Query tests**

```python
# backend/tests/rag/test_self_query.py
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
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/rag/test_self_query.py -q
```

Expected: collection fails because `self_query.py` does not exist.

- [ ] **Step 3: Implement filter merge**

```python
# backend/app/rag/llm_gateway/self_query.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MAX_VERSION_VALUES = 5


@dataclass(frozen=True)
class SelfQueryApplication:
    applied_filters: Dict[str, Any]
    dropped_filters: List[Dict[str, Any]]


def _key(value: str) -> str:
    return re.sub(r"[\s-]+", "", value.strip().casefold())


def _canonical(value: str, allowed: Sequence[str]) -> Optional[str]:
    wanted = _key(value)
    for candidate in allowed:
        if _key(candidate) == wanted:
            return candidate
    return None


def _canonical_versions(
    values: Iterable[str],
    allowed: Sequence[str],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    applied = []
    dropped = []
    seen = set()
    for value in values:
        canonical = _canonical(value, allowed)
        if canonical is None:
            dropped.append(
                {
                    "field": "version_values",
                    "value": value,
                    "reason": "unknown_facet_value",
                }
            )
            continue
        if canonical not in seen:
            seen.add(canonical)
            applied.append(canonical)
    return applied[:MAX_VERSION_VALUES], dropped


def apply_self_query_filters(
    *,
    extracted_filters: Dict[str, Any],
    explicit_product: Optional[str],
    explicit_versions: Sequence[str],
    allowed_products: Sequence[str],
    allowed_versions: Sequence[str],
) -> SelfQueryApplication:
    dropped: List[Dict[str, Any]] = []
    extracted_product = extracted_filters.get("product")
    extracted_versions = list(extracted_filters.get("version_values") or [])

    if explicit_product:
        applied_product = _canonical(explicit_product, allowed_products) or explicit_product.strip()
        if extracted_product and _key(str(extracted_product)) != _key(applied_product):
            dropped.append(
                {
                    "field": "product",
                    "value": extracted_product,
                    "reason": "user_override",
                }
            )
    elif extracted_product:
        applied_product = _canonical(str(extracted_product), allowed_products)
        if applied_product is None:
            dropped.append(
                {
                    "field": "product",
                    "value": extracted_product,
                    "reason": "unknown_facet_value",
                }
            )
    else:
        applied_product = None

    if explicit_versions:
        applied_versions = [
            _canonical(value, allowed_versions) or value.strip()
            for value in explicit_versions
        ]
        if extracted_versions:
            if {_key(value) for value in extracted_versions} != {
                _key(value) for value in applied_versions
            }:
                dropped.append(
                    {
                        "field": "version_values",
                        "value": extracted_versions,
                        "reason": "user_override",
                    }
                )
    else:
        applied_versions, version_dropped = _canonical_versions(
            extracted_versions,
            allowed_versions,
        )
        dropped.extend(version_dropped)

    return SelfQueryApplication(
        applied_filters={
            "product": applied_product,
            "version_values": applied_versions,
        },
        dropped_filters=dropped,
    )
```

- [ ] **Step 4: Add failing Gateway tests**

```python
# append to backend/tests/core/test_llm_policy.py
def test_gateway_uses_llm_rewrite_and_applies_self_query_filters():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway
    from backend.app.rag.llm_gateway.contracts import RewriteResult

    class Provider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "openai_chat_completions"

        def __init__(self):
            self.history = None

        def rewrite(self, **kwargs):
            self.history = kwargs["history"]
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

    provider = Provider()
    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=DataClassification.INTERNAL,
            allowed_provider_ids=("provider-a",),
            allowed_model_ids=("model-a",),
            allow_chat_history=True,
        ),
        external_answer_provider=provider,
        external_api_key="test-key",
    )
    result = gateway.rewrite(
        question="它怎么开启？",
        history=({"role": "user", "content": "Spring Boot 3.2 虚拟线程"},),
        allowed_products=("spring-boot",),
        allowed_versions=("3.2",),
        allow_chat_history=True,
    )

    assert result.route == "openai_chat_completions"
    assert result.applied_filters == {
        "product": "spring-boot",
        "version_values": ["3.2"],
    }
    assert provider.history[0]["role"] == "user"


def test_gateway_does_not_send_history_when_policy_disallows_it():
    from backend.app.core.llm_policy import resolve_model_policy
    from backend.app.rag.llm_gateway import LlmGateway
    from backend.app.rag.llm_gateway.contracts import RewriteResult

    class Provider:
        provider_id = "provider-a"
        model_id = "model-a"
        route = "openai_chat_completions"

        def __init__(self):
            self.history = ("sentinel",)

        def rewrite(self, **kwargs):
            self.history = kwargs["history"]
            return RewriteResult(
                original_query=kwargs["question"],
                rewritten_query=kwargs["question"],
                changed=False,
                route=self.route,
                model_id=self.model_id,
                provider_id=self.provider_id,
                structured_mode="json_object",
            )

    provider = Provider()
    gateway = LlmGateway(
        decision=resolve_model_policy(
            deployment_mode="external_allowed",
            requested_classification=DataClassification.INTERNAL,
            allowed_provider_ids=("provider-a",),
            allowed_model_ids=("model-a",),
            allow_chat_history=False,
        ),
        external_answer_provider=provider,
        external_api_key="test-key",
    )
    gateway.rewrite(
        question="独立问题",
        history=({"role": "user", "content": "secret history"},),
        allow_chat_history=False,
    )

    assert provider.history == ()
```

- [ ] **Step 5: Implement Gateway orchestration**

Replace `LlmGateway.rewrite` with:

```python
    def rewrite(
        self,
        *,
        question: str,
        history: Sequence[Any] = (),
        product: Optional[str] = None,
        version_values: Sequence[str] = (),
        allowed_products: Sequence[str] = (),
        allowed_versions: Sequence[str] = (),
        allow_chat_history: bool = False,
        classification: DataClassification = DataClassification.INTERNAL,
    ) -> RewriteResult:
        started = time.perf_counter()
        result = deterministic_rewrite(
            question=question,
            history=history,
            product=product,
            version_values=version_values,
        )
        result = replace(
            result,
            applied_filters={
                "product": product,
                "version_values": list(version_values),
            },
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        fallback_reason = None
        validation_error = None
        redacted_count = 0

        if self._has_external_route(self._answer_provider) and self._decision.allow_external:
            try:
                assert_external_call_allowed(self._decision, classification)
                question_scan = scan_and_redact(question)
                redacted_count += question_scan.redacted_count
                safe_history = []
                if allow_chat_history:
                    for item in history:
                        content = _message_value(item, "content")
                        if not content:
                            continue
                        content_scan = scan_and_redact(content)
                        redacted_count += content_scan.redacted_count
                        safe_history.append(
                            {
                                "role": _message_value(item, "role") or "user",
                                "content": content_scan.text,
                            }
                        )
                external_rewrite = getattr(self._answer_provider, "rewrite", None)
                if external_rewrite is None:
                    fallback_reason = "provider_rewrite_unsupported"
                else:
                    candidate = external_rewrite(
                        question=question_scan.text,
                        history=tuple(safe_history),
                        product=product,
                        version_values=tuple(version_values),
                        allowed_products=tuple(allowed_products),
                        allowed_versions=tuple(allowed_versions),
                    )
                    if not isinstance(candidate, RewriteResult):
                        fallback_reason = "provider_rewrite_invalid"
                    else:
                        application = apply_self_query_filters(
                            extracted_filters=candidate.extracted_filters,
                            explicit_product=product,
                            explicit_versions=version_values,
                            allowed_products=allowed_products,
                            allowed_versions=allowed_versions,
                        )
                        result = replace(
                            candidate,
                            applied_filters=application.applied_filters,
                            dropped_filters=application.dropped_filters,
                            latency_ms=int(
                                (time.perf_counter() - started) * 1000
                            ),
                        )
            except PermissionError:
                fallback_reason = "policy_denied"
            except ProviderAdapterError as error:
                if error.code == "MODEL_RESPONSE_INVALID":
                    fallback_reason = "invalid_response"
                else:
                    fallback_reason = "provider_error"
                validation_error = error.upstream_code or error.code.lower()
            except ModelUnavailableError:
                fallback_reason = "provider_error"
        else:
            fallback_reason = (
                "local_only"
                if not self._decision.allow_external
                else "provider_unavailable"
            )

        if fallback_reason is not None:
            result = replace(
                result,
                fallback_reason=fallback_reason,
                validation_error=validation_error,
                degraded=True,
            )

        self._audit(
            GatewayAudit(
                purpose="query_rewrite",
                route=result.route,
                model_id=result.model_id,
                provider_id=result.provider_id,
                external=result.route != "local_rules",
                classification=classification.value,
                policy_version=self._decision.policy_version,
                reason_code=result.fallback_reason
                or result.structured_mode
                or "no_rewrite",
                redacted_count=redacted_count,
                latency_ms=result.latency_ms,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                degraded=result.degraded,
            )
        )
        return result
```

Add imports:

```python
from dataclasses import replace
from backend.app.rag.llm_gateway.self_query import apply_self_query_filters
```

- [ ] **Step 6: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/rag/test_self_query.py backend/tests/core/test_llm_policy.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/rag/llm_gateway/self_query.py backend/app/rag/llm_gateway/gateway.py backend/tests/rag/test_self_query.py backend/tests/core/test_llm_policy.py
git commit -m "feat: add LLM rewrite orchestration and self-query merge"
```

---

### Task 5: Facets Helper, Chat Wiring and Retrieval Parity

**Files:**
- Modify: `backend/app/api/v1/kbs.py`
- Modify: `backend/app/api/v1/chats.py`
- Modify: `backend/app/rag/retrieval/in_memory.py`
- Create: `backend/tests/api/test_chat_self_query.py`
- Modify: `backend/tests/retrieval/test_engine_filters.py`

**Interfaces:**
- Produces: `readable_document_facets(session, team_id, user, knowledge_base_ids=None) -> dict`.
- Consumes: `RewriteResult.applied_filters`.
- Produces: `RetrievalFilters.product` / `version_values` from applied filters.

- [ ] **Step 1: Write failing facet and parity tests**

```python
# backend/tests/api/test_chat_self_query.py
import json

from backend.app.api.v1 import chats as chats_module
from backend.app.db.models import Document, IndexGenerationRecord
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
        json={"team_id": team["id"], "knowledge_base_ids": [kb["id"]]},
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
            "/api/v1/auth/me", headers=admin_headers
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
        session.add(IndexGenerationRecord(team_id=team["id"], status="active"))
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

    monkeypatch.setattr(chats_module, "build_retriever", lambda *args: Retriever())
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

    assert response.status_code == 200
    assert captured["filters"].product == "spring-boot"
    assert captured["filters"].version_values == ("3.2",)
    assert response.json()["data"]["status"] == "refused"
```

Add to `backend/tests/retrieval/test_engine_filters.py`:

```python
def test_in_memory_filter_excludes_missing_product_when_filter_is_set():
    import asyncio

    from backend.app.rag.domain.models import (
        Chunk,
        DataClassification,
        RetrievalFilters,
        SearchRequest,
        Visibility,
    )
    from backend.app.rag.retrieval.in_memory import InMemoryRetriever

    chunk = Chunk(
        chunk_id="chunk-missing-product",
        document_id="doc-1",
        document_version_id="version-1",
        team_id="team-a",
        knowledge_base_id="kb-a",
        owner_user_id="user-a",
        visibility=Visibility.TEAM_SHARED,
        data_classification=DataClassification.INTERNAL,
        source_path="missing-product.md",
        heading_path=(),
        content="Spring Boot virtual threads",
        logical_chunk_key="logical-1",
        content_hash="hash-1",
        product=None,
        version_values=(),
    )
    retriever = InMemoryRetriever([chunk], {chunk.chunk_id: [0.1]})
    result = asyncio.run(
        retriever.search(
            SearchRequest(
                query="spring-boot",
                rewritten_query=None,
                query_vector=[0.1],
                filters=RetrievalFilters(
                    team_id="team-a",
                    knowledge_base_ids=("kb-a",),
                    viewer_user_id="user-a",
                    product="spring-boot",
                ),
            )
        )
    )
    assert result.chunks == []
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/api/test_chat_self_query.py backend/tests/retrieval/test_engine_filters.py -q
```

Expected: FAIL because filters are not extracted/applied and in-memory still treats missing product as a match.

- [ ] **Step 3: Extract reusable readable facets**

In `backend/app/api/v1/kbs.py`, add:

```python
# replace the existing typing import with:
from typing import Optional, Sequence


def readable_document_facets(
    session: Session,
    team_id: str,
    user: User,
    knowledge_base_ids: Optional[Sequence[str]] = None,
) -> dict:
    query = (
        select(Document, KnowledgeBase)
        .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
        .where(
            KnowledgeBase.team_id == team_id,
            Document.doc_status != "deleted",
            KnowledgeBase.id.in_(
                knowledge_base_member_ids(session, team_id, user.id)
            ),
            _readable_documents_filter(session, team_id, user),
        )
    )
    if knowledge_base_ids:
        query = query.where(KnowledgeBase.id.in_(list(knowledge_base_ids)))
    rows = session.execute(query).all()
    return {
        "products": sorted({doc.product for doc, _ in rows if doc.product}),
        "versions": sorted(
            {
                value
                for doc, _ in rows
                for value in json.loads(doc.version_values or "[]")
            }
        ),
        "sources": sorted({doc.source_type for doc, _ in rows}),
        "knowledge_base_ids": sorted({kb.id for _, kb in rows}),
    }
```

Change `list_facets` to call this helper and preserve its response shape, including
`knowledge_base_ids`.

- [ ] **Step 4: Pass facets and applied filters in both ask paths**

In `backend/app/api/v1/chats.py`, import the helper:

```python
from backend.app.api.v1.kbs import readable_document_facets
```

In the non-stream path, compute this immediately before resolving the gateway. In the
streaming path, compute it before returning `StreamingResponse` and close over the plain
dict inside `stream_events`; do not use the request-scoped session inside the generator:

```python
facet_catalog = readable_document_facets(
    session,
    body.team_id,
    user,
    tuple(knowledge_base_ids),
)
```

Call:

```python
rewrite = await asyncio.to_thread(
    gateway.rewrite,
    question=question,
    history=history,
    product=product,
    version_values=version_values,
    allowed_products=tuple(facet_catalog["products"]),
    allowed_versions=tuple(facet_catalog["versions"]),
    allow_chat_history=decision.allow_chat_history,
    classification=DataClassification.INTERNAL,
)
```

Before constructing `RetrievalFilters`:

```python
applied_product = rewrite.applied_filters.get("product")
applied_versions = tuple(
    rewrite.applied_filters.get("version_values") or ()
)
```

Use `applied_product` / `applied_versions` in both retrieval paths and in the Trace
`filters` JSON.

- [ ] **Step 5: Fix in-memory filter parity**

```python
        if filters.product and chunk.product != filters.product:
            return False
        if filters.version_values:
            if not chunk.version_values:
                return False
            if not set(filters.version_values).intersection(chunk.version_values):
                return False
```

- [ ] **Step 6: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/api/test_chat_self_query.py backend/tests/retrieval/test_engine_filters.py backend/tests/api/test_chat_retrieval_generation.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/kbs.py backend/app/api/v1/chats.py backend/app/rag/retrieval/in_memory.py backend/tests/api/test_chat_self_query.py backend/tests/retrieval/test_engine_filters.py
git commit -m "feat: apply self-query filters during retrieval"
```

---

### Task 6: Rewrite Trace Persistence, Migration and API

**Files:**
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/session.py`
- Modify: `backend/app/api/v1/chats.py`
- Modify: `backend/app/api/v1/traces.py`
- Create: `backend/tests/api/test_trace_rewrite.py`
- Modify: `backend/tests/db/test_session.py`

**Interfaces:**
- Produces: `TraceRecord.rewrite` TEXT JSON.
- Produces: `TraceView.rewrite` parsed JSON.

- [ ] **Step 1: Write failing migration and API tests**

```python
# backend/tests/db/test_session.py
def test_create_schema_adds_rewrite_to_legacy_retrieval_traces():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE retrieval_traces ("
                "id VARCHAR(26) PRIMARY KEY, "
                "team_id VARCHAR(26) NOT NULL, "
                "trace_id VARCHAR(36) NOT NULL, "
                "original_query TEXT NOT NULL"
                ")"
            )
        )

    create_schema(engine)
    create_schema(engine)
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("retrieval_traces")
    }
    assert "rewrite" in columns
```

```python
# backend/tests/api/test_trace_rewrite.py
import json
from uuid import uuid4

from backend.app.db.models import Chat, TraceRecord


def test_trace_detail_returns_rewrite_metadata(
    api_client, api_app, admin_headers
):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Rewrite Trace Team"},
        headers=admin_headers,
    ).json()["data"]
    chat = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "knowledge_base_ids": []},
        headers=admin_headers,
    ).json()["data"]
    trace_id = str(uuid4())
    rewrite = {
        "original_query": "它怎么开启？",
        "rewritten_query": "Spring Boot 3.2 如何开启虚拟线程？",
        "changed": True,
        "route": "openai_chat_completions",
        "model_id": "model-test",
        "structured_mode": "json_schema",
        "extracted_filters": {
            "product": "spring-boot",
            "version_values": ["3.2"],
        },
        "applied_filters": {
            "product": "spring-boot",
            "version_values": ["3.2"],
        },
        "dropped_filters": [],
    }

    with api_app.state.session_factory() as session:
        session.add(
            TraceRecord(
                team_id=team["id"],
                chat_id=chat["id"],
                trace_id=trace_id,
                original_query="它怎么开启？",
                rewritten_query="Spring Boot 3.2 如何开启虚拟线程？",
                rewrite=json.dumps(rewrite, ensure_ascii=False),
            )
        )
        session.commit()

    response = api_client.get(
        "/api/v1/traces/detail",
        params={"team_id": team["id"], "trace_id": trace_id},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["data"]["rewrite"] == rewrite
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/db/test_session.py backend/tests/api/test_trace_rewrite.py -q -k rewrite
```

Expected: FAIL because `TraceRecord.rewrite` does not exist.

- [ ] **Step 3: Add model and migration**

In `backend/app/db/models.py`:

```python
class TraceRecord(Base):
    ...
    rewritten_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rewrite: Mapped[str] = mapped_column(Text, default="{}")
```

In `backend/app/db/session.py`:

```python
def _bridge_trace_rewrite(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("retrieval_traces"):
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("retrieval_traces")
    }
    if "rewrite" in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE retrieval_traces "
                "ADD COLUMN rewrite TEXT NOT NULL DEFAULT '{}'"
            )
        )
```

Call `_bridge_trace_rewrite(engine)` inside `create_schema`.

- [ ] **Step 4: Persist rewrite metadata in every trace path**

Add helpers in `backend/app/api/v1/chats.py`:

```python
from backend.app.rag.llm_gateway.contracts import RewriteResult


def _rewrite_trace_payload(rewrite: Optional[RewriteResult]) -> dict:
    if rewrite is None:
        return {}
    return {
        "original_query": rewrite.original_query,
        "rewritten_query": rewrite.rewritten_query,
        "changed": rewrite.changed,
        "route": rewrite.route,
        "provider_id": rewrite.provider_id,
        "model_id": rewrite.model_id,
        "structured_mode": rewrite.structured_mode,
        "extracted_filters": rewrite.extracted_filters,
        "applied_filters": rewrite.applied_filters,
        "dropped_filters": rewrite.dropped_filters,
        "fallback_reason": rewrite.fallback_reason,
        "validation_error": rewrite.validation_error,
        "latency_ms": rewrite.latency_ms,
        "input_tokens": rewrite.input_tokens,
        "output_tokens": rewrite.output_tokens,
    }


def _rewrite_json(rewrite: Optional[RewriteResult]) -> str:
    return json.dumps(
        _rewrite_trace_payload(rewrite),
        ensure_ascii=False,
    )
```

Set `rewrite=_rewrite_json(rewrite)` on TraceRecord at:

- stream `persist_trace` create/update
- failure trace
- non-stream success trace

- [ ] **Step 5: Return rewrite metadata from the Trace API**

In `backend/app/api/v1/traces.py`, reuse the existing `_json_value` helper and add to
`_trace_view`:

```python
"rewrite": _json_value(trace.rewrite, {}),
```

- [ ] **Step 6: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/db/test_session.py backend/tests/api/test_trace_rewrite.py backend/tests/api/test_trace_security.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/app/db/session.py backend/app/api/v1/chats.py backend/app/api/v1/traces.py backend/tests/db/test_session.py backend/tests/api/test_trace_rewrite.py
git commit -m "feat: persist query rewrite metadata in traces"
```

---

### Task 7: Frontend Trace QueryRewrite Section

**Files:**
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/views/TraceDetailView.vue`
- Modify: `frontend/src/views/TraceDetailView.spec.ts`

**Interfaces:**
- Consumes: `TraceView.rewrite`.
- Produces: QueryRewrite summary, source badge and filter chips.

- [ ] **Step 1: Add failing frontend test**

```typescript
it('renders query rewrite source, filters and fallback reason', async () => {
  apiMocks.getTrace.mockResolvedValueOnce({
    ...trace,
    rewritten_query: 'Spring Boot 3.2 如何开启虚拟线程？',
    rewrite: {
      original_query: '它怎么开启？',
      rewritten_query: 'Spring Boot 3.2 如何开启虚拟线程？',
      changed: true,
      route: 'openai_chat_completions',
      model_id: 'gpt-5-mini',
      structured_mode: 'json_schema',
      extracted_filters: {
        product: 'spring-boot',
        version_values: ['3.2'],
      },
      applied_filters: {
        product: 'spring-boot',
        version_values: ['3.2'],
      },
      dropped_filters: [],
      fallback_reason: null,
      latency_ms: 820,
      input_tokens: 450,
      output_tokens: 24,
    },
  })

  const wrapper = await mountPage()
  const panel = wrapper.get('[data-testid="trace-rewrite"]')

  expect(panel.text()).toContain('它怎么开启？')
  expect(panel.text()).toContain('Spring Boot 3.2 如何开启虚拟线程？')
  expect(panel.text()).toContain('LLM 结构化')
  expect(panel.text()).toContain('spring-boot')
  expect(panel.text()).toContain('3.2')
  expect(panel.text()).toContain('gpt-5-mini')
})
```

- [ ] **Step 2: Run test and verify failure**

```bash
cd frontend && npx vitest run src/views/TraceDetailView.spec.ts
```

Expected: FAIL because `trace-rewrite` does not exist.

- [ ] **Step 3: Add TypeScript types**

```typescript
export interface TraceRewriteView {
  original_query?: string
  rewritten_query?: string
  changed?: boolean
  route?: string
  provider_id?: string | null
  model_id?: string
  structured_mode?: string | null
  extracted_filters?: JsonRecord
  applied_filters?: JsonRecord
  dropped_filters?: JsonRecord[]
  fallback_reason?: string | null
  validation_error?: string | null
  latency_ms?: number
  input_tokens?: number
  output_tokens?: number
}
```

Add `rewrite?: TraceRewriteView` to `TraceView`.

- [ ] **Step 4: Render the QueryRewrite panel**

Add computed helpers in `TraceDetailView.vue`:

```typescript
const rewrite = computed(() => trace.value?.rewrite ?? null)
const rewriteSourceLabel = computed(() => {
  const value = rewrite.value
  if (!value) return ''
  if (value.fallback_reason || value.route === 'local_rules') return '规则回退'
  if (value.structured_mode === 'json_schema') return 'LLM 结构化'
  if (value.structured_mode === 'tool_use') return 'LLM 工具调用'
  return 'LLM JSON'
})
const rewriteFilters = computed(() => {
  const filters = rewrite.value?.applied_filters ?? {}
  const product = typeof filters.product === 'string' ? filters.product : ''
  const versions = Array.isArray(filters.version_values)
    ? filters.version_values.filter((value): value is string => typeof value === 'string')
    : []
  return [product, ...versions].filter(Boolean)
})
```

Template block placed after the detail grid:

```html
<div v-if="rewrite" class="rewrite-summary" data-testid="trace-rewrite">
  <div class="rewrite-summary-head">
    <strong>QueryRewrite</strong>
    <span class="rewrite-source">{{ rewriteSourceLabel }}</span>
  </div>
  <div class="rewrite-query-flow">
    <span>{{ rewrite.original_query || '—' }}</span>
    <span class="rewrite-arrow">→</span>
    <span>{{ rewrite.rewritten_query || '—' }}</span>
  </div>
  <div v-if="rewriteFilters.length" class="rewrite-filter-list">
    <span v-for="filter in rewriteFilters" :key="filter" class="rewrite-filter">
      {{ filter }}
    </span>
  </div>
  <p class="muted-text">
    {{ rewrite.model_id || '未知模型' }}
    · {{ formatTraceDuration(rewrite.latency_ms ?? 0) }}
    · {{ rewrite.input_tokens ?? 0 }} / {{ rewrite.output_tokens ?? 0 }} tokens
  </p>
  <p v-if="rewrite.fallback_reason" class="muted-text">
    回退原因：{{ rewrite.fallback_reason }}
  </p>
</div>
```

Add restrained CSS matching the existing Trace detail styles:

```css
.rewrite-summary {
  margin: 16px 0;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #f8fafb;
}

.rewrite-summary-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.rewrite-source {
  padding: 2px 8px;
  border-radius: 999px;
  background: #e6f4f1;
  color: var(--accent-strong);
  font-size: 12px;
}

.rewrite-query-flow {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  line-height: 1.6;
}

.rewrite-arrow {
  color: var(--muted);
}

.rewrite-filter-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.rewrite-filter {
  padding: 2px 8px;
  border-radius: 4px;
  background: #eef2f5;
  color: var(--text);
  font-size: 12px;
}

.rewrite-summary p {
  margin: 8px 0 0;
}
```

- [ ] **Step 5: Run tests and build**

```bash
cd frontend && npx vitest run src/views/TraceDetailView.spec.ts
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/views/TraceDetailView.vue frontend/src/views/TraceDetailView.spec.ts frontend/src/styles.css
git commit -m "feat: show query rewrite details in trace"
```

---

### Task 8: SSE, Documentation and Full Regression

**Files:**
- Modify: `backend/app/api/v1/chats.py`
- Modify: `backend/tests/api/test_chat_retrieval_generation.py`
- Modify: `docs/api/api-contract.md`
- Modify: `docs/product/page-map.md`

**Interfaces:**
- Produces: extended SSE `rewrite` event and non-stream `rewrite` payload.

- [ ] **Step 1: Add failing SSE test**

```python
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

    _mock_ask_stack(api_app, team["id"], monkeypatch, result, Provider())
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
```

- [ ] **Step 2: Run test and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/api/test_chat_retrieval_generation.py -q -k rewrite_event
```

Expected: FAIL because the event only contains `original` and `rewritten`.

- [ ] **Step 3: Extend SSE and non-stream payloads**

```python
extracted_product = rewrite.extracted_filters.get("product")
extracted_versions = rewrite.extracted_filters.get("version_values") or []
if rewrite.changed or extracted_product or extracted_versions:
    yield sse(
        "rewrite",
        {
            "original": rewrite.original_query,
            "rewritten": rewrite.rewritten_query,
            "changed": rewrite.changed,
            "route": rewrite.route,
            "model_id": rewrite.model_id,
            "structured_mode": rewrite.structured_mode,
            "applied_filters": rewrite.applied_filters,
            "fallback_reason": rewrite.fallback_reason,
        },
    )
```

Non-stream payload:

```python
"rewrite": {
    "original": rewrite.original_query,
    "rewritten": rewrite.rewritten_query,
    "changed": rewrite.changed,
    "route": rewrite.route,
    "model_id": rewrite.model_id,
    "structured_mode": rewrite.structured_mode,
    "applied_filters": rewrite.applied_filters,
    "fallback_reason": rewrite.fallback_reason,
},
```

- [ ] **Step 4: Update docs**

In `docs/api/api-contract.md`, document:

- `rewrite` JSON object on Trace detail.
- extended `rewrite` SSE fields.
- Self-Query filter whitelist and zero-result refusal.

In `docs/product/page-map.md`, document:

- QueryRewrite badge and filter chips on Trace detail.
- Hard-filter zero-result refusal on the chat page.

- [ ] **Step 5: Run focused suites**

```bash
.venv/bin/python -m pytest backend/tests/providers/test_rewrite_contract.py backend/tests/providers/test_adapters.py backend/tests/rag/test_self_query.py backend/tests/core/test_llm_policy.py backend/tests/api/test_chat_self_query.py backend/tests/api/test_chat_retrieval_generation.py backend/tests/api/test_trace_rewrite.py backend/tests/db/test_session.py -q
cd frontend && npx vitest run src/views/TraceDetailView.spec.ts
```

Expected: PASS.

- [ ] **Step 6: Run full regression and build**

```bash
.venv/bin/python -m pytest -q
cd frontend && npm test
cd frontend && npm run build
```

Expected:

- backend: all tests pass.
- frontend: all tests pass.
- `vue-tsc` and Vite build pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/chats.py backend/tests/api/test_chat_retrieval_generation.py docs/api/api-contract.md docs/product/page-map.md
git commit -m "docs: document LLM rewrite and self-query behavior"
git push origin main
```

---

## Self-Review

Spec coverage:

- LLM-first rewrite: Task 4.
- Three provider structured modes: Tasks 2 and 3.
- JSON schema downgrade: Tasks 2 and 3.
- Self-Query hard filters: Tasks 4 and 5.
- User filter precedence and facet validation: Task 4.
- History policy enforcement: Task 4.
- Missing-field parity: Task 5.
- Zero-result refusal: covered by existing refusal path and Task 5 API test.
- Trace column/migration/API: Task 6.
- Trace UI: Task 7.
- SSE and docs: Task 8.

Placeholder scan: no `TBD`, `TODO`, `FIXME`, or “similar to another task” references.

Type consistency: `RewriteResult` fields, `SelfQueryApplication` fields, `TraceRecord.rewrite`
and `TraceView.rewrite` use the same names across tasks.
