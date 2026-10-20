from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import backend.app.api.v1.chats as chats_module
from backend.app.core.config import Settings
from backend.app.db.models import ChunkRecord, Document, IndexGenerationRecord
from backend.app.db.session import (
    build_engine,
    build_session_factory,
    create_schema,
)
from backend.app.main import create_app
from backend.app.rag.domain.models import (
    Chunk,
    ChunkStatus,
    DataClassification,
    DocumentStatus,
    Visibility,
)
from backend.app.rag.embedding.service import hash_embedding
from backend.app.rag.retrieval.in_memory import InMemoryRetriever


ADMIN_EMAIL = "admin@techvault.local"
ADMIN_PASSWORD = "ChangeMe-123!"
FAKE_ANSWER = "Answer from fake provider [c1]."


class _FakeProviderServer:
    def __init__(self) -> None:
        self.requests = []
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                content_length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(content_length) or b"{}")
                with owner._lock:
                    owner.requests.append(
                        {
                            "path": self.path,
                            "headers": dict(self.headers),
                            "payload": payload,
                        }
                    )

                if self._is_rewrite_request(payload):
                    body = self._rewrite_body(payload)
                elif self.path.endswith("/responses"):
                    body = self._responses_body(payload)
                elif self.path.endswith("/messages"):
                    body = self._anthropic_body(payload)
                else:
                    body = self._chat_body(payload)
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    (
                        "text/event-stream"
                        if payload.get("stream")
                        else "application/json"
                    ),
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            @staticmethod
            def _is_rewrite_request(payload) -> bool:
                return bool(
                    payload.get("response_format")
                    or payload.get("text", {}).get("format")
                    or payload.get("tools")
                )

            def _rewrite_body(self, payload) -> bytes:
                rewrite = {
                    "rewritten_query": "What are virtual threads?",
                    "filters": {
                        "product": None,
                        "version_values": [],
                    },
                }
                if self.path.endswith("/responses"):
                    response = {
                        "output_text": json.dumps(rewrite),
                    }
                elif self.path.endswith("/messages"):
                    response = {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "submit_query_rewrite",
                                "input": rewrite,
                            }
                        ]
                    }
                else:
                    response = {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(rewrite),
                                }
                            }
                        ]
                    }
                return json.dumps(response).encode()

            def _chat_body(self, payload) -> bytes:
                if payload.get("stream"):
                    return (
                        'data: {"choices":[{"delta":{"content":"Answer from "}}]}\n\n'
                        'data: {"choices":[{"delta":{"content":"fake provider [c1]."}}]}\n\n'
                        "data: [DONE]\n\n"
                    ).encode()
                return json.dumps(
                    {
                        "choices": [
                            {"message": {"content": FAKE_ANSWER}},
                        ]
                    }
                ).encode()

            def _responses_body(self, payload) -> bytes:
                if payload.get("stream"):
                    return (
                        "event: response.output_text.delta\n"
                        'data: {"type":"response.output_text.delta",'
                        '"delta":"Answer from "}\n\n'
                        "event: response.output_text.delta\n"
                        'data: {"type":"response.output_text.delta",'
                        '"delta":"fake provider [c1]."}\n\n'
                        "event: response.completed\n"
                        'data: {"type":"response.completed"}\n\n'
                    ).encode()
                return json.dumps(
                    {
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {"type": "output_text", "text": FAKE_ANSWER}
                                ],
                            }
                        ]
                    }
                ).encode()

            def _anthropic_body(self, payload) -> bytes:
                if payload.get("stream"):
                    return (
                        "event: content_block_delta\n"
                        'data: {"type":"content_block_delta","delta":'
                        '{"type":"text_delta","text":"Answer from "}}\n\n'
                        "event: content_block_delta\n"
                        'data: {"type":"content_block_delta","delta":'
                        '{"type":"text_delta","text":"fake provider [c1]."}}\n\n'
                        "event: message_stop\n"
                        'data: {"type":"message_stop"}\n\n'
                    ).encode()
                return json.dumps(
                    {
                        "content": [
                            {"type": "text", "text": FAKE_ANSWER},
                        ]
                    }
                ).encode()

            def log_message(self, _format, *_args) -> None:
                return

        self._server = _FastThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return "http://{0}:{1}/v1".format(host, port)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _FastThreadingHTTPServer(ThreadingHTTPServer):
    """Bind without a reverse-DNS lookup, which can stall test startup."""

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


@pytest.fixture()
def fake_provider():
    server = _FakeProviderServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def api_app(tmp_path):
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    session_factory = build_session_factory(engine)
    app = create_app(
        settings=Settings(
            environment="test",
            jwt_secret="test-secret-at-least-32-bytes-long",
            enable_indexing=False,
            task_execution_mode="inline",
            upload_dir=str(tmp_path / "uploads"),
            embedding_url="http://127.0.0.1:1",
            rerank_url="http://127.0.0.1:1",
        ),
        session_factory=session_factory,
    )
    yield app
    engine.dispose()


@pytest.fixture()
def api_client(api_app):
    with TestClient(api_app) as client:
        yield client


@pytest.fixture()
def admin_headers(api_client):
    response = api_client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": "Bearer " + response.json()["data"]["access_token"]
    }


def _setup_chat(api_client, admin_headers):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Provider E2E Team"},
        headers=admin_headers,
    ).json()["data"]
    knowledge_base = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Provider E2E KB"},
        headers=admin_headers,
    ).json()["data"]
    chat = api_client.post(
        "/api/v1/chats/create",
        json={
            "team_id": team["id"],
            "title": "Provider E2E chat",
            "knowledge_base_ids": [knowledge_base["id"]],
        },
        headers=admin_headers,
    ).json()["data"]
    return team, knowledge_base, chat


def _create_provider(
    api_client,
    admin_headers,
    team_id,
    base_url,
    provider_type,
):
    response = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team_id,
            "name": "E2E Provider",
            "provider_type": provider_type,
            "base_url": base_url,
            "api_key": "sk-e2e",
            "model_ids": ["fake-model"],
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
):
    deployment_policy = api_client.post(
        "/api/v1/admin/model-policy/update",
        json={
            "mode": "external_allowed",
            "allowed_provider_ids": [provider_id],
            "max_data_classification": "internal",
        },
        headers=admin_headers,
    )
    assert deployment_policy.status_code == 200, deployment_policy.text

    team_policy = api_client.post(
        "/api/v1/model-policy/update",
        json={
            "team_id": team_id,
            "mode": "external_allowed",
            "allowed_provider_ids": [provider_id],
            "max_data_classification": "internal",
        },
        headers=admin_headers,
    )
    assert team_policy.status_code == 200, team_policy.text

    knowledge_base_policy = api_client.get(
        "/api/v1/kbs/policy",
        params={"team_id": team_id, "kb_id": knowledge_base_id},
        headers=admin_headers,
    )
    assert knowledge_base_policy.status_code == 200, knowledge_base_policy.text
    updated = api_client.post(
        "/api/v1/kbs/policy/update",
        json={
            "team_id": team_id,
            "kb_id": knowledge_base_id,
            "mode": "external_allowed",
        },
        headers={
            **admin_headers,
            "If-Match": str(knowledge_base_policy.json()["data"]["version"]),
        },
    )
    assert updated.status_code == 200, updated.text


def _upload_document(api_client, admin_headers, team_id, knowledge_base_id):
    response = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": team_id, "kb_id": knowledge_base_id},
        files={
            "file": (
                "virtual-threads.md",
                b"# Virtual Threads\n\n"
                b"Virtual threads are lightweight Java threads.\n",
            )
        },
        headers=admin_headers,
    )
    assert response.status_code == 202, response.text
    document_id = response.json()["data"]["document"]["id"]
    chunks = api_client.get(
        "/api/v1/chunks",
        params={"team_id": team_id, "document_id": document_id},
        headers=admin_headers,
    )
    assert chunks.status_code == 200, chunks.text
    assert chunks.json()["data"], "expected uploaded document chunks"


def _activate_generation(api_app, team_id):
    with api_app.state.session_factory() as session:
        session.add(
            IndexGenerationRecord(
                team_id=team_id,
                status="active",
                activated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def _install_uploaded_retriever(api_app, team_id, monkeypatch):
    with api_app.state.session_factory() as session:
        rows = session.scalars(
            select(ChunkRecord).where(
                ChunkRecord.team_id == team_id,
                ChunkRecord.doc_status == "active",
                ChunkRecord.chunk_status == "enabled",
            )
        ).all()
        chunks = []
        for row in rows:
            document = session.get(Document, row.document_id)
            assert document is not None
            chunks.append(
                Chunk(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    document_version_id=document.current_version_id or document.id,
                    team_id=row.team_id,
                    knowledge_base_id=row.knowledge_base_id,
                    owner_user_id=row.owner_user_id,
                    visibility=Visibility(row.visibility),
                    data_classification=DataClassification(
                        row.data_classification
                    ),
                    source_path=row.source_path,
                    heading_path=tuple(json.loads(row.heading_path or "[]")),
                    content=row.content,
                    logical_chunk_key=row.logical_chunk_key,
                    content_hash=row.content_hash,
                    source_locator=json.loads(row.source_locator or "{}"),
                    product=document.product,
                    version_values=tuple(
                        json.loads(row.version_values or "[]")
                    ),
                    doc_status=DocumentStatus.ACTIVE,
                    chunk_status=ChunkStatus(row.chunk_status),
                    index_generation=row.index_generation or "",
                )
            )
    assert chunks, "expected retriever chunks"
    retriever = InMemoryRetriever(
        chunks=chunks,
        embedding={
            chunk.chunk_id: hash_embedding(chunk.content) for chunk in chunks
        },
    )
    monkeypatch.setattr(
        chats_module,
        "build_retriever",
        lambda *args, **kwargs: retriever,
    )


def _sse_events(response_text):
    events = []
    for block in response_text.strip().split("\n\n"):
        lines = block.splitlines()
        if not lines:
            continue
        event_name = next(
            line.removeprefix("event:").strip()
            for line in lines
            if line.startswith("event:")
        )
        data_line = next(
            line for line in lines if line.startswith("data:")
        )
        events.append(
            {
                "event": event_name,
                "data": json.loads(data_line.removeprefix("data:").strip()),
            }
        )
    return events


@pytest.mark.parametrize("stream", [False, True], ids=["non-stream", "stream"])
@pytest.mark.parametrize(
    ("provider_type", "expected_path", "prompt_location"),
    [
        (
            "openai_responses",
            "/v1/responses",
            "input",
        ),
        (
            "openai_chat_completions",
            "/v1/chat/completions",
            "messages",
        ),
        (
            "anthropic_messages",
            "/v1/messages",
            "messages",
        ),
    ],
)
def test_chat_uses_selected_fake_provider(
    api_client,
    api_app,
    admin_headers,
    fake_provider,
    monkeypatch,
    stream,
    provider_type,
    expected_path,
    prompt_location,
):
    team, knowledge_base, chat = _setup_chat(api_client, admin_headers)
    provider = _create_provider(
        api_client,
        admin_headers,
        team["id"],
        fake_provider.base_url,
        provider_type,
    )
    _configure_external_policy(
        api_client,
        admin_headers,
        team["id"],
        knowledge_base["id"],
        provider["id"],
    )
    _upload_document(
        api_client,
        admin_headers,
        team["id"],
        knowledge_base["id"],
    )
    _activate_generation(api_app, team["id"])
    _install_uploaded_retriever(api_app, team["id"], monkeypatch)

    response = api_client.post(
        "/api/v1/chats/ask",
        json={
            "team_id": team["id"],
            "chat_id": chat["id"],
            "question": "What are virtual threads?",
            "provider_id": provider["id"],
            "model_id": "fake-model",
            "stream": stream,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    if stream:
        events = _sse_events(response.text)
        streamed_text = "".join(
            event["data"]["text"]
            for event in events
            if event["event"] == "delta"
        )
        assert streamed_text == FAKE_ANSWER
        done = next(event for event in events if event["event"] == "done")
        message = api_client.get(
            "/api/v1/messages/detail",
            params={
                "team_id": team["id"],
                "message_id": done["data"]["message_id"],
            },
            headers=admin_headers,
        )
        assert message.status_code == 200, message.text
        trace_id = message.json()["data"]["trace_id"]
    else:
        payload = response.json()["data"]
        assert payload["content"] == FAKE_ANSWER
        trace_id = payload["trace_id"]

    trace = api_client.get(
        "/api/v1/traces/detail",
        params={"team_id": team["id"], "trace_id": trace_id},
        headers=admin_headers,
    )
    assert trace.status_code == 200, trace.text
    model = trace.json()["data"]["model"]
    assert model["provider_id"] == provider["id"]
    assert model["model_id"] == "fake-model"
    assert model["route"] == provider_type
    assert model["external"] is True
    assert "sk-e2e" not in response.text

    assert len(fake_provider.requests) == 2
    rewrite_request, provider_request = fake_provider.requests
    assert rewrite_request["path"] == expected_path
    assert rewrite_request["payload"]["model"] == "fake-model"
    if provider_type == "openai_chat_completions":
        assert (
            rewrite_request["payload"]["response_format"]["type"]
            == "json_schema"
        )
    elif provider_type == "openai_responses":
        assert (
            rewrite_request["payload"]["text"]["format"]["type"]
            == "json_schema"
        )
    else:
        assert (
            rewrite_request["payload"]["tool_choice"]["name"]
            == "submit_query_rewrite"
        )
    assert provider_request["path"] == expected_path
    if provider_type == "anthropic_messages":
        assert provider_request["headers"]["x-api-key"] == "sk-e2e"
        assert (
            provider_request["headers"]["anthropic-version"]
            == "2023-06-01"
        )
    else:
        assert provider_request["headers"]["Authorization"] == "Bearer sk-e2e"
    assert provider_request["payload"]["model"] == "fake-model"
    assert provider_request["payload"]["stream"] is stream
    if prompt_location == "input":
        prompt = provider_request["payload"]["input"]
    else:
        prompt = provider_request["payload"]["messages"][0]["content"]
    assert "Virtual threads are lightweight Java threads." in prompt
