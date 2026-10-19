"""Normalized adapters for the supported upstream LLM API formats."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence
from urllib.parse import urlsplit, urlunsplit

import httpx

from backend.app.rag.answer.service import (
    AnswerResult,
    AnswerStream,
    answer_result_from_text,
    answer_stream_from_pieces,
)
from backend.app.rag.domain.models import RetrievedChunk


SUPPORTED_PROVIDER_TYPES = frozenset(
    {
        "openai_responses",
        "openai_chat_completions",
        "anthropic_messages",
    }
)
_ANTHROPIC_VERSION = "2023-06-01"
_OPERATION_SUFFIXES = (
    "/chat/completions",
    "/responses",
    "/completions",
    "/messages",
)
_OPERATIONS = {
    "openai_responses": "/responses",
    "openai_chat_completions": "/chat/completions",
    "anthropic_messages": "/messages",
}


class ProviderAdapterError(RuntimeError):
    """A safe, normalized upstream failure that never contains credentials."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class LlmProviderAdapter(Protocol):
    provider_id: str
    model_id: str
    route: str

    def generate(
        self,
        *,
        question: str,
        chunks: Sequence[RetrievedChunk],
        max_chunks: int = 8,
    ) -> AnswerResult:
        ...

    def generate_stream(
        self,
        *,
        question: str,
        chunks: Sequence[RetrievedChunk],
        max_chunks: int = 8,
    ) -> AnswerStream:
        ...


def _operation_url(provider_type: str, base_url: str) -> str:
    normalized = base_url.strip()
    if not normalized:
        raise ProviderAdapterError(
            400,
            "INVALID_ARGUMENT",
            "Base URL is required.",
        )
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderAdapterError(
            400,
            "INVALID_ARGUMENT",
            "Base URL must be an absolute HTTP or HTTPS URL.",
        )

    path = parsed.path.rstrip("/")
    for suffix in _OPERATION_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)].rstrip("/")
            break
    operation = _OPERATIONS[provider_type]
    if not path.endswith("/v1"):
        path += "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path + operation, "", ""))


def _prompt(question: str, chunks: Sequence[RetrievedChunk]) -> str:
    context = "\n\n".join(
        "[c{0}] {1}".format(index, chunk.content.strip())
        for index, chunk in enumerate(chunks, start=1)
    )
    if not context:
        context = "(no knowledge base context was retrieved)"
    return (
        "Answer the question using only the supplied knowledge base context. "
        "Cite supporting context with only labels such as [c1] and [c2]. "
        "Use no other citation labels. If the context is insufficient, say so.\n\n"
        "Question:\n{0}\n\nKnowledge base context:\n{1}".format(
            question.strip(),
            context,
        )
    )


def _content_text(value: object) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        pieces = []
        for item in value:
            text = _content_text(item)
            if text is not None:
                pieces.append(text)
        return "".join(pieces)
    if isinstance(value, dict):
        text = value.get("text")
        return text if isinstance(text, str) else None
    return None


def _safe_json(response: httpx.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as error:
        raise ProviderAdapterError(
            502,
            "MODEL_RESPONSE_INVALID",
            "Upstream returned an invalid JSON response.",
        ) from error
    if not isinstance(payload, dict):
        raise ProviderAdapterError(
            502,
            "MODEL_RESPONSE_INVALID",
            "Upstream returned an invalid response shape.",
        )
    return payload


def _raise_for_response(response: httpx.Response) -> None:
    if response.status_code in {401, 403}:
        raise ProviderAdapterError(
            502,
            "MODEL_AUTH_FAILED",
            "Upstream rejected the provider API Key.",
        )
    if response.status_code >= 400:
        raise ProviderAdapterError(
            503,
            "MODEL_UNAVAILABLE",
            "Upstream model request failed with HTTP {0}.".format(
                response.status_code
            ),
        )


def _stream_json_candidates(chunk_text: str) -> List[str]:
    candidates = []
    blocks = re.split(r"\r?\n\r?\n", chunk_text)
    for block in blocks:
        data_lines = []
        raw_lines = []
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("data:"):
                data_lines.append(stripped[5:].lstrip())
            elif stripped and not stripped.startswith(("event:", "id:", ":")):
                raw_lines.append(stripped)
        if data_lines:
            candidates.extend(data_lines)
        elif raw_lines:
            candidates.append("\n".join(raw_lines))
    return candidates


def _delta_text(payload: Dict[str, Any]) -> str:
    delta = payload.get("delta")
    if isinstance(delta, str):
        return delta
    if isinstance(delta, dict):
        text = delta.get("text")
        return text if isinstance(text, str) else ""
    text = payload.get("text")
    return text if isinstance(text, str) else ""


@dataclass(frozen=True)
class _ProviderStreamEvent:
    text: str
    terminal: bool


def _parse_provider_stream_event(
    adapter_type: str,
    chunk_text: str,
) -> _ProviderStreamEvent:
    aliases = {
        "responses": "responses",
        "openai_responses": "responses",
        "chat": "chat",
        "openai_chat_completions": "chat",
        "anthropic": "anthropic",
        "anthropic_messages": "anthropic",
    }
    normalized_type = aliases.get(adapter_type)
    if normalized_type is None:
        raise ProviderAdapterError(
            400,
            "INVALID_ARGUMENT",
            "Unsupported provider stream format.",
        )

    pieces = []
    terminal = False
    for candidate in _stream_json_candidates(chunk_text):
        if not candidate:
            continue
        if candidate == "[DONE]":
            if normalized_type == "chat":
                terminal = True
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        if payload.get("type") == "error" or "error" in payload:
            raise ProviderAdapterError(
                503,
                "MODEL_UNAVAILABLE",
                "Upstream model stream reported an error.",
            )

        if normalized_type == "responses":
            event_type = payload.get("type")
            if event_type == "response.completed":
                terminal = True
            elif event_type in {None, "response.output_text.delta"}:
                text = _delta_text(payload)
                if text:
                    pieces.append(text)
        elif normalized_type == "chat":
            choices = payload.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                delta = choices[0].get("delta")
                if isinstance(delta, dict):
                    text = _content_text(delta.get("content"))
                    if text:
                        pieces.append(text)
        else:
            event_type = payload.get("type")
            if event_type == "message_stop":
                terminal = True
            elif event_type == "content_block_delta":
                text = _delta_text(payload)
                if text:
                    pieces.append(text)
    return _ProviderStreamEvent(text="".join(pieces), terminal=terminal)


def parse_provider_stream_chunk(adapter_type: str, chunk_text: str) -> str:
    """Return normalized text from one provider SSE chunk or event block."""
    return _parse_provider_stream_event(adapter_type, chunk_text).text


class _HttpProviderAdapter:
    route = ""
    _stream_type = ""

    def __init__(
        self,
        provider_id: str,
        base_url: str,
        api_key: str,
        model_id: str,
        transport: Optional[Any] = None,
    ) -> None:
        self.provider_id = str(provider_id)
        self.model_id = str(model_id)
        self._api_key = api_key.strip()
        self._transport = transport
        if not self._api_key:
            raise ProviderAdapterError(
                400,
                "INVALID_ARGUMENT",
                "API Key is required.",
            )
        self._url = _operation_url(self.route, base_url)

    def __repr__(self) -> str:
        return "{0}(provider_id={1!r}, model_id={2!r}, route={3!r})".format(
            type(self).__name__,
            self.provider_id,
            self.model_id,
            self.route,
        )

    def _selected_chunks(
        self,
        chunks: Sequence[RetrievedChunk],
        max_chunks: int,
    ) -> tuple[RetrievedChunk, ...]:
        return tuple(chunks[: max(0, max_chunks)])

    def _headers(self, *, stream: bool) -> Dict[str, str]:
        return {
            "Accept": "text/event-stream" if stream else "application/json",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        *,
        prompt: str,
        stream: bool,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def _response_text(self, payload: Dict[str, Any]) -> str:
        raise NotImplementedError

    def _provider_error(self, error: Exception) -> ProviderAdapterError:
        if isinstance(error, ProviderAdapterError):
            return error
        if isinstance(error, (httpx.TimeoutException, httpx.RequestError)):
            return ProviderAdapterError(
                503,
                "MODEL_UNAVAILABLE",
                "Upstream model service is unavailable.",
            )
        return ProviderAdapterError(
            502,
            "MODEL_RESPONSE_INVALID",
            "Upstream returned an invalid response.",
        )

    def generate(
        self,
        *,
        question: str,
        chunks: Sequence[RetrievedChunk],
        max_chunks: int = 8,
    ) -> AnswerResult:
        selected = self._selected_chunks(chunks, max_chunks)
        prompt = _prompt(question, selected)
        pending_error = None
        try:
            with httpx.Client(
                timeout=60.0,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post(
                    self._url,
                    headers=self._headers(stream=False),
                    json=self._payload(prompt=prompt, stream=False),
                )
            _raise_for_response(response)
            text = self._response_text(_safe_json(response))
        except Exception as error:
            normalized = self._provider_error(error)
            if normalized is error:
                raise
            pending_error = normalized
        if pending_error is not None:
            raise pending_error
        return answer_result_from_text(
            text,
            question=question,
            chunks=selected,
            model_id=self.model_id,
            route=self.route,
        )

    def _has_async_transport(self) -> bool:
        return isinstance(self._transport, httpx.AsyncBaseTransport)

    async def _stream_pieces(
        self,
        *,
        selected: Sequence[RetrievedChunk],
        prompt: str,
    ):
        headers = self._headers(stream=True)
        payload = self._payload(prompt=prompt, stream=True)
        pending_error = None
        terminal = False
        try:
            if self._transport is not None and not self._has_async_transport():
                with httpx.Client(
                    timeout=60.0,
                    transport=self._transport,
                    trust_env=False,
                ) as client:
                    with client.stream(
                        "POST",
                        self._url,
                        headers=headers,
                        json=payload,
                    ) as response:
                        _raise_for_response(response)
                        for line in response.iter_lines():
                            event = _parse_provider_stream_event(
                                self._stream_type,
                                line + "\n\n" if line else "\n",
                            )
                            terminal = terminal or event.terminal
                            if event.text:
                                yield event.text
            else:
                async with httpx.AsyncClient(
                    timeout=60.0,
                    transport=self._transport,
                    trust_env=False,
                ) as client:
                    async with client.stream(
                        "POST",
                        self._url,
                        headers=headers,
                        json=payload,
                    ) as response:
                        _raise_for_response(response)
                        event_lines = []
                        async for line in response.aiter_lines():
                            if line:
                                event_lines.append(line)
                                continue
                            if event_lines:
                                event = _parse_provider_stream_event(
                                    self._stream_type,
                                    "\n".join(event_lines) + "\n\n",
                                )
                                event_lines = []
                                terminal = terminal or event.terminal
                                if event.text:
                                    yield event.text
                        if event_lines:
                            event = _parse_provider_stream_event(
                                self._stream_type,
                                "\n".join(event_lines) + "\n\n",
                            )
                            terminal = terminal or event.terminal
                            if event.text:
                                yield event.text

            if not terminal:
                raise ProviderAdapterError(
                    502,
                    "MODEL_RESPONSE_INVALID",
                    "Upstream stream ended before a terminal event.",
                )
        except Exception as error:
            normalized = self._provider_error(error)
            if normalized is error:
                raise
            pending_error = normalized
        if pending_error is not None:
            raise pending_error

    def generate_stream(
        self,
        *,
        question: str,
        chunks: Sequence[RetrievedChunk],
        max_chunks: int = 8,
    ) -> AnswerStream:
        selected = self._selected_chunks(chunks, max_chunks)
        prompt = _prompt(question, selected)
        return answer_stream_from_pieces(
            self._stream_pieces(
                selected=selected,
                prompt=prompt,
            ),
            question=question,
            chunks=selected,
            model_id=self.model_id,
            route=self.route,
        )


class OpenAIChatCompletionsAdapter(_HttpProviderAdapter):
    route = "openai_chat_completions"
    _stream_type = "chat"

    def _headers(self, *, stream: bool) -> Dict[str, str]:
        headers = super()._headers(stream=stream)
        headers["Authorization"] = "Bearer {0}".format(self._api_key)
        return headers

    def _payload(self, *, prompt: str, stream: bool) -> Dict[str, Any]:
        return {
            "model": self.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }

    def _response_text(self, payload: Dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderAdapterError(
                502,
                "MODEL_RESPONSE_INVALID",
                "Chat Completions response did not contain choices.",
            )
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict) or "content" not in message:
            raise ProviderAdapterError(
                502,
                "MODEL_RESPONSE_INVALID",
                "Chat Completions response did not contain message content.",
            )
        return _content_text(message.get("content")) or ""


class OpenAIResponsesAdapter(_HttpProviderAdapter):
    route = "openai_responses"
    _stream_type = "responses"

    def _headers(self, *, stream: bool) -> Dict[str, str]:
        headers = super()._headers(stream=stream)
        headers["Authorization"] = "Bearer {0}".format(self._api_key)
        return headers

    def _payload(self, *, prompt: str, stream: bool) -> Dict[str, Any]:
        return {
            "model": self.model_id,
            "input": prompt,
            "stream": stream,
        }

    def _response_text(self, payload: Dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str):
            return output_text
        output = payload.get("output")
        if not isinstance(output, list):
            raise ProviderAdapterError(
                502,
                "MODEL_RESPONSE_INVALID",
                "Responses API response did not contain output.",
            )
        pieces = []
        for item in output:
            if not isinstance(item, dict):
                continue
            text = _content_text(item.get("content"))
            if text is not None:
                pieces.append(text)
        if not pieces and output:
            raise ProviderAdapterError(
                502,
                "MODEL_RESPONSE_INVALID",
                "Responses API output did not contain text.",
            )
        return "".join(pieces)


class AnthropicMessagesAdapter(_HttpProviderAdapter):
    route = "anthropic_messages"
    _stream_type = "anthropic"

    def _headers(self, *, stream: bool) -> Dict[str, str]:
        headers = super()._headers(stream=stream)
        headers["x-api-key"] = self._api_key
        headers["anthropic-version"] = _ANTHROPIC_VERSION
        return headers

    def _payload(self, *, prompt: str, stream: bool) -> Dict[str, Any]:
        return {
            "model": self.model_id,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }

    def _response_text(self, payload: Dict[str, Any]) -> str:
        content = payload.get("content")
        if not isinstance(content, list):
            raise ProviderAdapterError(
                502,
                "MODEL_RESPONSE_INVALID",
                "Anthropic response did not contain content.",
            )
        pieces = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str):
                pieces.append(text)
        return "".join(pieces)


_ADAPTER_TYPES = {
    "openai_responses": OpenAIResponsesAdapter,
    "openai_chat_completions": OpenAIChatCompletionsAdapter,
    "anthropic_messages": AnthropicMessagesAdapter,
}


def build_provider_adapter(
    provider_type: str,
    provider_id: str,
    base_url: str,
    api_key: str,
    model_id: str,
    transport: Optional[Any] = None,
) -> LlmProviderAdapter:
    adapter_type = _ADAPTER_TYPES.get(provider_type)
    if adapter_type is None:
        raise ProviderAdapterError(
            400,
            "INVALID_ARGUMENT",
            "Unsupported provider type.",
        )
    return adapter_type(
        provider_id=provider_id,
        base_url=base_url,
        api_key=api_key,
        model_id=model_id,
        transport=transport,
    )


__all__ = [
    "AnthropicMessagesAdapter",
    "LlmProviderAdapter",
    "OpenAIChatCompletionsAdapter",
    "OpenAIResponsesAdapter",
    "ProviderAdapterError",
    "SUPPORTED_PROVIDER_TYPES",
    "build_provider_adapter",
    "parse_provider_stream_chunk",
]
