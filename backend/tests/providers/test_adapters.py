import asyncio
import json

import httpx
import pytest

from backend.app.rag.answer.service import (
    answer_result_from_text,
    answer_stream_from_pieces,
)
from backend.app.rag.domain.models import RetrievedChunk
from backend.app.rag.llm_gateway.providers import (
    AnthropicMessagesAdapter,
    OpenAIChatCompletionsAdapter,
    OpenAIResponsesAdapter,
    ProviderAdapterError,
    build_provider_adapter,
    parse_provider_stream_chunk,
)


def _chunk(
    chunk_id="chunk-1",
    content="Virtual threads are lightweight threads.",
    fused_rank=1,
):
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_version_id="dv-1",
        content=content,
        fused_rank=fused_rank,
    )


async def _collect(stream):
    return [piece async for piece in stream]


def test_chat_completions_adapter_maps_response_to_answer_result():
    def handler(request):
        assert str(request.url) == "https://gateway.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["model"] == "gpt-test"
        assert "[c1]" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Use virtual threads [c1]."}}
                ]
            },
        )

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
    assert result.route == "openai_chat_completions"
    assert result.degraded is False


def test_openai_responses_adapter_reads_output_text_blocks():
    def handler(request):
        assert str(request.url) == "https://gateway.example/v1/responses"
        body = json.loads(request.content)
        assert body["model"] == "gpt-response"
        assert "[c1]" in body["input"]
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "Responses answer [c1]."}
                        ],
                    }
                ]
            },
        )

    adapter = OpenAIResponsesAdapter(
        provider_id="provider-1",
        base_url="https://gateway.example",
        api_key="sk-test",
        model_id="gpt-response",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.generate(question="What?", chunks=[_chunk()], max_chunks=1)

    assert result.text == "Responses answer [c1]."
    assert result.citation_chunk_ids == ("chunk-1",)
    assert result.route == "openai_responses"


def test_anthropic_adapter_uses_message_headers_and_response_text():
    def handler(request):
        assert str(request.url) == "https://api.anthropic.com/v1/messages"
        assert request.headers["x-api-key"] == "sk-ant"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == "claude-test"
        assert "[c1]" in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Threads are cheap [c1]."}
                ]
            },
        )

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
    assert result.route == "anthropic_messages"


def test_answer_result_maps_citations_in_first_occurrence_order():
    chunks = (
        _chunk("chunk-1", "First"),
        _chunk("chunk-2", "Second", fused_rank=2),
    )

    result = answer_result_from_text(
        "Second [c2], first [c1], second again [c2].",
        question="What?",
        chunks=chunks,
        model_id="model-1",
        route="openai_responses",
    )

    assert result.citation_chunk_ids == ("chunk-2", "chunk-1")
    assert result.degraded is False
    assert result.status == "completed"


def test_answer_result_without_citation_markers_uses_all_chunks_and_degrades():
    chunks = (
        _chunk("chunk-1", "First"),
        _chunk("chunk-2", "Second", fused_rank=2),
    )

    result = answer_result_from_text(
        "Answer without markers.",
        question="What?",
        chunks=chunks,
        model_id="model-1",
        route="openai_chat_completions",
    )

    assert result.citation_chunk_ids == ("chunk-1", "chunk-2")
    assert result.degraded is True


def test_answer_result_without_markers_and_without_chunks_still_degrades():
    result = answer_result_from_text(
        "Answer without markers.",
        question="What?",
        chunks=(),
        model_id="model-1",
        route="openai_chat_completions",
    )

    assert result.citation_chunk_ids == ()
    assert result.degraded is True


def test_answer_result_degrades_for_invalid_citations_alongside_valid_ones():
    result = answer_result_from_text(
        "Valid [c1], invalid [c99].",
        question="What?",
        chunks=(_chunk("chunk-1", "First"),),
        model_id="model-1",
        route="openai_chat_completions",
    )

    assert result.citation_chunk_ids == ("chunk-1",)
    assert result.degraded is True


def test_max_chunks_limits_prompt_context_and_default_citations():
    def handler(request):
        body = json.loads(request.content)
        prompt = body["messages"][0]["content"]
        assert "[c1]" in prompt
        assert "[c2] Second" not in prompt
        assert "Virtual threads are lightweight threads." in prompt
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Only one chunk."}}]},
        )

    adapter = OpenAIChatCompletionsAdapter(
        provider_id="provider-1",
        base_url="https://gateway.example",
        api_key="sk-test",
        model_id="gpt-test",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.generate(
        question="What?",
        chunks=[_chunk(), _chunk("chunk-2", "Second", fused_rank=2)],
        max_chunks=1,
    )

    assert result.citation_chunk_ids == ("chunk-1",)
    assert result.degraded is True


@pytest.mark.parametrize(
    ("adapter_type", "chunk_text"),
    [
        (
            "responses",
            'event: response.output_text.delta\ndata: {"delta":"hello"}\n\n',
        ),
        (
            "chat",
            'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n',
        ),
        (
            "anthropic",
            'event: content_block_delta\n'
            'data: {"type":"content_block_delta","delta":'
            '{"type":"text_delta","text":"hello"}}\n\n',
        ),
    ],
)
def test_stream_parsers_emit_normalized_text(adapter_type, chunk_text):
    assert parse_provider_stream_chunk(adapter_type, chunk_text) == "hello"


@pytest.mark.parametrize(
    ("adapter_type", "chunk_text"),
    [
        (
            "responses",
            'event: error\ndata: {"type":"error","error":'
            '{"type":"server_error","message":"upstream failed"}}\n\n',
        ),
        (
            "chat",
            'data: {"error":{"type":"server_error","message":"upstream failed"}}\n\n',
        ),
        (
            "anthropic",
            'event: error\ndata: {"type":"error","error":'
            '{"type":"overloaded_error","message":"upstream failed"}}\n\n',
        ),
    ],
)
def test_stream_parsers_raise_on_protocol_error_events(adapter_type, chunk_text):
    with pytest.raises(ProviderAdapterError) as caught:
        parse_provider_stream_chunk(adapter_type, chunk_text)

    assert caught.value.status_code == 503
    assert caught.value.code == "MODEL_UNAVAILABLE"


def test_chat_stream_adapter_yields_text_and_sets_terminal_result():
    def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(
            200,
            text=(
                'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"[c1]"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    adapter = OpenAIChatCompletionsAdapter(
        provider_id="provider-1",
        base_url="https://gateway.example/v1",
        api_key="sk-test",
        model_id="gpt-test",
        transport=httpx.MockTransport(handler),
    )

    stream = adapter.generate_stream(
        question="What?",
        chunks=[_chunk()],
        max_chunks=1,
    )

    assert asyncio.run(_collect(stream)) == ["hello ", "[c1]"]
    assert stream.result is not None
    assert stream.result.text == "hello [c1]"
    assert stream.result.citation_chunk_ids == ("chunk-1",)
    assert stream.result.model_id == "gpt-test"


def test_answer_stream_helper_normalizes_sync_pieces():
    stream = answer_stream_from_pieces(
        ["part one ", "part two [c1]"],
        question="What?",
        chunks=(_chunk(),),
        model_id="model-1",
        route="anthropic_messages",
    )

    assert asyncio.run(_collect(stream)) == ["part one ", "part two [c1]"]
    assert stream.result is not None
    assert stream.result.text == "part one part two [c1]"
    assert stream.result.citation_chunk_ids == ("chunk-1",)


def test_answer_stream_leaves_result_unset_when_piece_source_raises():
    def pieces():
        yield "partial [c1]"
        raise RuntimeError("stream interrupted")

    stream = answer_stream_from_pieces(
        pieces(),
        question="What?",
        chunks=(_chunk(),),
        model_id="model-1",
        route="anthropic_messages",
    )

    async def consume():
        iterator = stream.__aiter__()
        assert await iterator.__anext__() == "partial [c1]"
        with pytest.raises(RuntimeError, match="stream interrupted"):
            await iterator.__anext__()

    asyncio.run(consume())

    assert stream.result is None


@pytest.mark.parametrize("streaming", [False, True])
def test_request_errors_do_not_retain_request_metadata(streaming):
    def handler(request):
        raise httpx.ConnectError("connection failed", request=request)

    adapter = OpenAIResponsesAdapter(
        provider_id="provider-1",
        base_url="https://gateway.example",
        api_key="sk-super-secret",
        model_id="gpt-test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderAdapterError) as caught:
        if streaming:
            asyncio.run(
                _collect(
                    adapter.generate_stream(
                        question="What?",
                        chunks=[_chunk()],
                        max_chunks=1,
                    )
                )
            )
        else:
            adapter.generate(question="What?", chunks=[_chunk()], max_chunks=1)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_build_provider_adapter_selects_supported_formats():
    adapter = build_provider_adapter(
        "openai_responses",
        "provider-1",
        "https://gateway.example/v1",
        "sk-test",
        "gpt-test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"output_text": "ok"})
        ),
    )

    assert isinstance(adapter, OpenAIResponsesAdapter)
    assert adapter.provider_id == "provider-1"
    assert adapter.model_id == "gpt-test"
    assert adapter.route == "openai_responses"


def test_build_provider_adapter_rejects_unsupported_format():
    with pytest.raises(ProviderAdapterError) as caught:
        build_provider_adapter(
            "ollama",
            "provider-1",
            "https://gateway.example",
            "sk-test",
            "model-1",
        )

    assert caught.value.status_code == 400
    assert caught.value.code == "INVALID_ARGUMENT"
