from __future__ import annotations

import asyncio
import inspect
import re
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from backend.app.core.llm_policy import assert_external_call_allowed
from backend.app.rag.answer import AnswerAccumulator, AnswerResult, AnswerStream
from backend.app.rag.domain.models import (
    DataClassification,
    ModelPolicyDecision,
    RetrievedChunk,
)
from backend.app.rag.llm_gateway.contracts import RewriteResult
from backend.app.rag.llm_gateway.providers import ProviderAdapterError
from backend.app.rag.llm_gateway.self_query import apply_self_query_filters


class PolicyDeniedError(PermissionError):
    """Raised when the effective policy forbids the requested model route."""


class ModelUnavailableError(RuntimeError):
    """Raised when no usable model provider or approved fallback is available."""


@dataclass(frozen=True)
class SensitiveScan:
    text: str
    categories: Tuple[str, ...] = ()
    redacted_count: int = 0


def _stream_piece_text(piece: Any) -> str:
    if isinstance(piece, bytes):
        return piece.decode("utf-8", errors="replace")
    if isinstance(piece, str):
        return piece
    if isinstance(piece, dict):
        value = piece.get("text") or piece.get("delta") or ""
        return value if isinstance(value, str) else str(value)
    value = getattr(piece, "text", None)
    return value if isinstance(value, str) else (str(piece) if piece is not None else "")


async def _iterate_provider_stream(value: Any):
    if isinstance(value, (str, bytes)):
        yield _stream_piece_text(value)
        return
    if hasattr(value, "__aiter__"):
        async for piece in value:
            yield _stream_piece_text(piece)
        return
    for piece in iter(value):
        yield _stream_piece_text(piece)
        await asyncio.sleep(0)


def _completed_text_slices(text: str, size: int = 96):
    for start in range(0, len(text), size):
        yield text[start : start + size]


@dataclass(frozen=True)
class GatewayAudit:
    purpose: str
    route: str
    model_id: str
    provider_id: Optional[str]
    external: bool
    classification: str
    policy_version: str
    reason_code: str
    redacted_count: int
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    degraded: bool = False


_REDACTION_PATTERNS = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    (
        "bearer_token",
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    ),
    (
        "api_key",
        re.compile(r"\b(?:sk|ak|pk)-[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "database_url",
        re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mariadb|redis)://[^\s]+"),
    ),
    (
        "password",
        re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*[^\s,;]+"),
    ),
    (
        "internal_url",
        re.compile(
            r"(?i)https?://(?:localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|"
            r"192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})"
            r"(?::\d+)?(?:/[^\s]*)?"
        ),
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "ip_address",
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ),
)


def scan_and_redact(text: str) -> SensitiveScan:
    """Redact credentials and identifying network data before external egress."""
    redacted = text
    categories: List[str] = []
    count = 0
    for category, pattern in _REDACTION_PATTERNS:
        redacted, replacements = pattern.subn(
            "[REDACTED:{0}]".format(category), redacted
        )
        if replacements:
            count += replacements
            categories.append(category)
    return SensitiveScan(
        text=redacted,
        categories=tuple(dict.fromkeys(categories)),
        redacted_count=count,
    )


def _message_value(message: Any, key: str) -> str:
    if isinstance(message, dict):
        value = message.get(key, "")
    else:
        value = getattr(message, key, "")
    return value if isinstance(value, str) else ""


_PRODUCT_VERSION_RE = re.compile(
    r"(?P<product>[A-Za-z][A-Za-z0-9_.+#-]*(?:\s+[A-Za-z][A-Za-z0-9_.+#-]*){0,3})"
    r"\s+(?P<version>\d+(?:\.\d+){1,3})\b"
)
_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){1,3}\b")
_PRONOUN_RE = re.compile(r"^(它|这个|该|上面|上述|其)|(?<![\w])(it|this|that|they)(?![\w])", re.I)


def _context_from_history(
    history: Sequence[Any],
) -> Tuple[Optional[str], Optional[str]]:
    product = None
    version = None
    for message in reversed(list(history)):
        role = _message_value(message, "role").lower()
        if role not in {"", "user", "assistant"}:
            continue
        content = _message_value(message, "content")
        if not content:
            continue
        match = _PRODUCT_VERSION_RE.search(content)
        if match:
            product = product or match.group("product").strip()
            version = version or match.group("version")
        if version is None:
            version_match = _VERSION_RE.search(content)
            if version_match:
                version = version_match.group(0)
        if product and version:
            break
    return product, version


def deterministic_rewrite(
    *,
    question: str,
    history: Sequence[Any] = (),
    product: Optional[str] = None,
    version_values: Sequence[str] = (),
) -> RewriteResult:
    history_product, history_version = _context_from_history(history)
    inferred_product = product or history_product
    inferred_version = (version_values[0] if version_values else None) or history_version

    if product and history_product:
        normalize = lambda value: re.sub(r"[-_\s]+", "", value).lower()
        if normalize(product) == normalize(history_product):
            inferred_product = history_product

    context_parts = [
        value for value in (inferred_product, inferred_version) if value
    ]
    context_text = " ".join(context_parts).strip()
    rewritten = question.strip()

    if context_text:
        pronoun = _PRONOUN_RE.search(rewritten)
        if pronoun:
            start, end = pronoun.span()
            rewritten = rewritten[:start] + context_text + rewritten[end:]
        elif inferred_product and inferred_product.lower() not in rewritten.lower():
            rewritten = "{0}：{1}".format(context_text, rewritten)
        elif inferred_version and inferred_version not in rewritten:
            rewritten = "{0}：{1}".format(context_text, rewritten)

    rewritten = re.sub(r"\s+", " ", rewritten).strip()
    changed = rewritten != question.strip()
    return RewriteResult(
        original_query=question,
        rewritten_query=rewritten,
        changed=changed,
        route="local_rules",
        model_id="deterministic-rewrite",
        context_used={
            "product": inferred_product,
            "version": inferred_version,
            "history_messages": len(history),
        },
    )


class LlmGateway:
    """Single policy-enforcing boundary for rewrite, embedding, rerank and answers."""

    def __init__(
        self,
        *,
        decision: ModelPolicyDecision,
        external_answer_provider: Any = None,
        local_embed_provider: Any = None,
        external_embed_provider: Any = None,
        local_rerank_provider: Any = None,
        external_rerank_provider: Any = None,
        external_api_key: str = "",
        audit_sink: Optional[Callable[[GatewayAudit], None]] = None,
    ) -> None:
        self._decision = decision
        self._answer_provider = external_answer_provider
        self._local_embed = local_embed_provider
        self._external_embed = external_embed_provider
        self._local_rerank = local_rerank_provider
        self._external_rerank = external_rerank_provider
        self._external_api_key = external_api_key.strip()
        self._audit_sink = audit_sink
        self.audits: List[GatewayAudit] = []

    @property
    def decision(self) -> ModelPolicyDecision:
        return self._decision

    def _audit(self, record: GatewayAudit) -> None:
        self.audits.append(record)
        if self._audit_sink is not None:
            self._audit_sink(record)

    def _has_external_route(self, provider: Any) -> bool:
        if not (
            self._decision.allow_external
            and bool(self._external_api_key)
            and provider is not None
        ):
            return False
        provider_id = str(getattr(provider, "provider_id", "") or "")
        if provider_id not in self._decision.allowed_provider_ids:
            return False
        model_id = str(getattr(provider, "model_id", "") or "")
        if (
            self._decision.allowed_model_ids
            and model_id not in self._decision.allowed_model_ids
        ):
            return False
        return True

    def _answer_provider_is_external(self, provider: Any) -> bool:
        route = str(getattr(provider, "route", "") or "")
        if route == "local_model":
            return False
        return (
            self._has_external_route(provider)
            or bool(route)
            or bool(self._external_api_key)
        )

    def _require_approved_external_answer_provider(self, provider: Any) -> None:
        if not self._decision.allow_external:
            raise PolicyDeniedError(
                "External answer generation is forbidden by policy."
            )

        provider_id = str(getattr(provider, "provider_id", "") or "")
        if provider_id not in self._decision.allowed_provider_ids:
            raise PolicyDeniedError(
                "Answer provider is not approved by policy."
            )

        model_id = str(getattr(provider, "model_id", "") or "")
        if (
            self._decision.allowed_model_ids
            and model_id not in self._decision.allowed_model_ids
        ):
            raise PolicyDeniedError("Answer model is not approved by policy.")

        if not self._external_api_key:
            raise ModelUnavailableError(
                "External answer provider credentials are unavailable."
            )

    @staticmethod
    def _provider_id(provider: Any) -> Optional[str]:
        value = getattr(provider, "provider_id", None)
        return str(value) if value else None

    def _require_local(self, provider: Any, purpose: str) -> None:
        if provider is None:
            raise ModelUnavailableError(
                "No local model is available for {0}.".format(purpose)
            )

    def _require_local_fallback(self, purpose: str) -> None:
        if self._decision.fallback_mode == "reject":
            if self._decision.reason_code in {
                "restricted_classification",
                "private_classification_local_only",
                "classification_above_policy",
            }:
                raise PolicyDeniedError(
                    "Data classification forbids the required external route."
                )
            raise ModelUnavailableError(
                "No approved external model is available for {0}.".format(purpose)
            )

    def _external_failure_policy(self, error: Exception) -> None:
        if self._decision.fallback_mode == "reject":
            raise ModelUnavailableError(
                "External model failed and policy forbids fallback."
            ) from error

    def _prepare_external_answer(
        self,
        *,
        question: str,
        chunks: Sequence[RetrievedChunk],
        classification: DataClassification,
    ) -> Tuple[str, List[RetrievedChunk], int]:
        try:
            assert_external_call_allowed(self._decision, classification)
        except PermissionError as error:
            raise PolicyDeniedError(
                "Data classification forbids external answer generation."
            ) from error

        try:
            question_scan = scan_and_redact(question)
            effective_chunks = [
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_version_id=chunk.document_version_id,
                    content=scan_and_redact(chunk.content).text,
                    fused_rank=chunk.fused_rank,
                    bm25_rank=chunk.bm25_rank,
                    dense_rank=chunk.dense_rank,
                    rerank_score=chunk.rerank_score,
                    source_locator=chunk.source_locator,
                )
                for chunk in chunks
            ]
        except Exception as error:
            raise PolicyDeniedError(
                "External answer redaction failed."
            ) from error

        return question_scan.text, effective_chunks, question_scan.redacted_count

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
        redacted_count = 0
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

        if self._has_external_route(self._answer_provider) and self._decision.allow_external:
            allow_history = bool(
                allow_chat_history and self._decision.allow_chat_history
            )
            try:
                assert_external_call_allowed(self._decision, classification)
                scan = scan_and_redact(question)
                redacted_count = scan.redacted_count
                safe_history = []
                if allow_history:
                    for item in history:
                        content = _message_value(item, "content")
                        if not content:
                            continue
                        content_scan = scan_and_redact(content)
                        redacted_count += content_scan.redacted_count
                        safe_history.append(
                            {
                                "role": _message_value(item, "role")
                                or "user",
                                "content": content_scan.text,
                            }
                        )
                external_rewrite = getattr(self._answer_provider, "rewrite", None)
                if external_rewrite is None:
                    fallback_reason = "provider_rewrite_unsupported"
                else:
                    candidate = external_rewrite(
                        question=scan.text,
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
                reason_code=(
                    result.fallback_reason
                    or result.structured_mode
                    or "no_rewrite"
                ),
                redacted_count=redacted_count,
                latency_ms=result.latency_ms,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                degraded=result.fallback_reason is not None,
            )
        )
        return result

    def embed(
        self,
        texts: Sequence[str],
        *,
        classification: DataClassification = DataClassification.INTERNAL,
    ) -> List[List[float]]:
        started = time.perf_counter()
        provider = self._local_embed
        external = False
        route = "local_model"
        redacted_count = 0
        payload = list(texts)
        if self._has_external_route(self._external_embed):
            try:
                assert_external_call_allowed(self._decision, classification)
                scans = [scan_and_redact(text) for text in payload]
                payload = [scan.text for scan in scans]
                redacted_count = sum(scan.redacted_count for scan in scans)
                provider = self._external_embed
                external = True
                route = "external"
            except Exception as error:
                self._external_failure_policy(error)
        if not external:
            self._require_local_fallback("embedding")
        self._require_local(provider, "embedding")
        try:
            vectors = provider.embed(payload)
        except Exception as error:
            if not external:
                raise
            self._external_failure_policy(error)
            self._require_local(self._local_embed, "embedding")
            vectors = self._local_embed.embed(payload)
            external = False
            route = "local_model"
        self._audit(
            GatewayAudit(
                purpose="embedding",
                route=route,
                model_id=str(getattr(provider, "model_id", "bge-m3")),
                provider_id=self._provider_id(provider) if external else None,
                external=external,
                classification=classification.value,
                policy_version=self._decision.policy_version,
                reason_code=self._decision.reason_code,
                redacted_count=redacted_count,
                latency_ms=int((time.perf_counter() - started) * 1000.0),
                input_tokens=sum(max(1, len(text) // 4) for text in texts),
            )
        )
        return vectors

    def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        top_n: int,
        classification: DataClassification = DataClassification.INTERNAL,
    ) -> List[RetrievedChunk]:
        started = time.perf_counter()
        provider = self._local_rerank
        external = False
        route = "local_model"
        redacted_count = 0
        effective_query = query
        effective_chunks = list(chunks)
        if self._has_external_route(self._external_rerank):
            try:
                assert_external_call_allowed(self._decision, classification)
                scan = scan_and_redact(query)
                redacted_count = scan.redacted_count
                effective_query = scan.text
                effective_chunks = [
                    RetrievedChunk(
                        chunk_id=chunk.chunk_id,
                        document_version_id=chunk.document_version_id,
                        content=scan_and_redact(chunk.content).text,
                        fused_rank=chunk.fused_rank,
                        bm25_rank=chunk.bm25_rank,
                        dense_rank=chunk.dense_rank,
                        rerank_score=chunk.rerank_score,
                        source_locator=chunk.source_locator,
                    )
                    for chunk in effective_chunks
                ]
                provider = self._external_rerank
                external = True
                route = "external"
            except Exception as error:
                self._external_failure_policy(error)
        if not external:
            self._require_local_fallback("rerank")
        self._require_local(provider, "rerank")
        try:
            rows = provider.rerank(effective_query, effective_chunks, top_n=top_n)
        except Exception as error:
            if not external:
                raise
            self._external_failure_policy(error)
            self._require_local(self._local_rerank, "rerank")
            rows = self._local_rerank.rerank(
                effective_query, effective_chunks, top_n=top_n
            )
            provider = self._local_rerank
            external = False
            route = "local_model"
        self._audit(
            GatewayAudit(
                purpose="rerank",
                route=route,
                model_id=str(getattr(provider, "model_id", "bge-reranker-v2-m3")),
                provider_id=self._provider_id(provider) if external else None,
                external=external,
                classification=classification.value,
                policy_version=self._decision.policy_version,
                reason_code=self._decision.reason_code,
                redacted_count=redacted_count,
                latency_ms=int((time.perf_counter() - started) * 1000.0),
                input_tokens=max(1, len(query) // 4)
                + sum(max(1, len(chunk.content) // 4) for chunk in chunks),
            )
        )
        return rows

    def generate(
        self,
        *,
        question: str,
        chunks: Sequence[RetrievedChunk],
        classification: DataClassification = DataClassification.INTERNAL,
        max_chunks: int = 8,
    ) -> AnswerResult:
        started = time.perf_counter()
        provider = self._answer_provider
        if provider is None:
            raise ModelUnavailableError("No answer provider is configured.")
        external = False
        route = str(getattr(provider, "route", "local_model"))
        redacted_count = 0
        effective_question = question
        effective_chunks = list(chunks[:max_chunks])

        if self._answer_provider_is_external(provider):
            self._require_approved_external_answer_provider(provider)
            (
                effective_question,
                effective_chunks,
                redacted_count,
            ) = self._prepare_external_answer(
                question=question,
                chunks=effective_chunks,
                classification=classification,
            )
            external = True
            route = "external"

        if not external:
            self._require_local_fallback("answer generation")
        try:
            result = provider.generate(
                question=effective_question,
                chunks=effective_chunks,
                max_chunks=max_chunks,
            )
        except ProviderAdapterError:
            raise
        except Exception as error:
            raise ModelUnavailableError("Answer provider failed.") from error

        self._audit(
            GatewayAudit(
                purpose="answer",
                route=result.route if not external else route,
                model_id=result.model_id,
                provider_id=self._provider_id(provider),
                external=external,
                classification=classification.value,
                policy_version=self._decision.policy_version,
                reason_code=result.refusal_reason or self._decision.reason_code,
                redacted_count=redacted_count,
                latency_ms=int((time.perf_counter() - started) * 1000.0),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_micros=result.cost_micros,
                degraded=result.degraded,
            )
        )
        return result

    def generate_stream(
        self,
        *,
        question: str,
        chunks: Sequence[RetrievedChunk],
        classification: DataClassification = DataClassification.INTERNAL,
        max_chunks: int = 8,
    ) -> AnswerStream:
        """Return a policy-enforced answer stream with a terminal result."""

        stream = AnswerStream()

        async def iterate():
            started = time.perf_counter()
            provider = self._answer_provider
            if provider is None:
                raise ModelUnavailableError("No answer provider is configured.")
            external = False
            route = str(getattr(provider, "route", "local_model"))
            redacted_count = 0
            effective_question = question
            effective_chunks = list(chunks[:max_chunks])

            if self._answer_provider_is_external(provider):
                self._require_approved_external_answer_provider(provider)
                (
                    effective_question,
                    effective_chunks,
                    redacted_count,
                ) = self._prepare_external_answer(
                    question=question,
                    chunks=effective_chunks,
                    classification=classification,
                )
                external = True
                route = "external"

            if not external:
                self._require_local_fallback("answer generation")
            accumulator = AnswerAccumulator(
                question=effective_question,
                chunks=effective_chunks,
                model_id=str(
                    getattr(provider, "model_id", None)
                    or getattr(provider, "route", None)
                    or "streaming-provider"
                ),
                route=str(getattr(provider, "route", None) or route),
                degraded=bool(getattr(provider, "degraded", False)),
            )
            result = None
            completed = False
            try:
                stream_method = getattr(provider, "generate_stream", None)
                if not callable(stream_method):
                    stream_method = getattr(provider, "stream", None)

                if callable(stream_method):
                    candidate = stream_method(
                        question=effective_question,
                        chunks=effective_chunks,
                        max_chunks=max_chunks,
                    )
                    if inspect.isawaitable(candidate):
                        candidate = await candidate
                    async for piece in _iterate_provider_stream(candidate):
                        if not piece:
                            continue
                        accumulator.add(piece)
                        yield piece
                    result = accumulator.finish()
                    completed = True
                else:
                    result = provider.generate(
                        question=effective_question,
                        chunks=effective_chunks,
                        max_chunks=max_chunks,
                    )
                    if result.status != "refused":
                        for piece in _completed_text_slices(result.text):
                            yield piece
                    completed = True
            except ProviderAdapterError:
                raise
            except Exception as error:
                raise ModelUnavailableError("Answer provider failed.") from error
            finally:
                if completed and result is not None:
                    self._audit(
                        GatewayAudit(
                            purpose="answer",
                            route=result.route if not external else route,
                            model_id=result.model_id,
                            provider_id=self._provider_id(provider),
                            external=external,
                            classification=classification.value,
                            policy_version=self._decision.policy_version,
                            reason_code=result.refusal_reason
                            or self._decision.reason_code,
                            redacted_count=redacted_count,
                            latency_ms=int(
                                (time.perf_counter() - started) * 1000.0
                            ),
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                            cost_micros=result.cost_micros,
                            degraded=result.degraded,
                        )
                    )
                    stream.result = result

        stream.bind(iterate())
        return stream
