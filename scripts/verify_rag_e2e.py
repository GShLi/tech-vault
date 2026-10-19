"""Live verification of upload, retrieval, provider generation and traces.

Requires Elasticsearch on :59200 and Qdrant on :56333.
Run: .venv/bin/python scripts/verify_rag_e2e.py
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.session import (
    build_engine,
    build_session_factory,
    create_schema,
)
from backend.app.main import create_app


FAKE_ANSWER = "Answer from fake provider [c1]."


class _FastThreadingHTTPServer(ThreadingHTTPServer):
    """Bind without a reverse-DNS lookup, which can stall script startup."""

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


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

                if payload.get("stream"):
                    body = (
                        'data: {"choices":[{"delta":{"content":"Answer from "}}]}\n\n'
                        'data: {"choices":[{"delta":{"content":"fake provider [c1]."}}]}\n\n'
                        "data: [DONE]\n\n"
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                body = json.dumps(
                    {
                        "choices": [
                            {"message": {"content": FAKE_ANSWER}},
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, _error_type, _error, _traceback) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


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


def _configure_provider(client, headers, team, knowledge_base, provider):
    deployment_policy = client.post(
        "/api/v1/admin/model-policy/update",
        json={
            "mode": "external_allowed",
            "allowed_provider_ids": [provider["id"]],
            "max_data_classification": "internal",
        },
        headers=headers,
    )
    assert deployment_policy.status_code == 200, deployment_policy.text

    team_policy = client.post(
        "/api/v1/model-policy/update",
        json={
            "team_id": team["id"],
            "mode": "external_allowed",
            "allowed_provider_ids": [provider["id"]],
            "max_data_classification": "internal",
        },
        headers=headers,
    )
    assert team_policy.status_code == 200, team_policy.text

    knowledge_base_policy = client.get(
        "/api/v1/kbs/policy",
        params={"team_id": team["id"], "kb_id": knowledge_base["id"]},
        headers=headers,
    )
    assert knowledge_base_policy.status_code == 200, knowledge_base_policy.text
    updated = client.post(
        "/api/v1/kbs/policy/update",
        json={
            "team_id": team["id"],
            "kb_id": knowledge_base["id"],
            "mode": "external_allowed",
        },
        headers={
            **headers,
            "If-Match": str(knowledge_base_policy.json()["data"]["version"]),
        },
    )
    assert updated.status_code == 200, updated.text


def _assert_provider_call(provider_server, stream):
    assert len(provider_server.requests) == 1
    request = provider_server.requests.pop(0)
    assert request["path"] == "/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer sk-e2e"
    assert request["payload"]["model"] == "fake-model"
    assert request["payload"]["stream"] is stream
    prompt = request["payload"]["messages"][0]["content"]
    assert "Virtual threads are lightweight Java threads." in prompt


def main() -> None:
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    session_factory = build_session_factory(engine)
    settings = Settings(
        environment="test",
        jwt_secret="test-secret-at-least-32-bytes-long",
        enable_indexing=True,
        task_execution_mode="inline",
        es_url="http://127.0.0.1:59200",
        qdrant_url="http://127.0.0.1:56333",
        embedding_url="http://127.0.0.1:58001",
    )
    app = create_app(settings=settings, session_factory=session_factory)

    with _FakeProviderServer() as provider_server:
        with TestClient(app) as client:
            login = client.post(
                "/api/v1/auth/login",
                json={
                    "email": "admin@techvault.local",
                    "password": "ChangeMe-123!",
                },
            )
            assert login.status_code == 200, login.text
            headers = {
                "Authorization": "Bearer "
                + login.json()["data"]["access_token"]
            }
            team = client.post(
                "/api/v1/teams/create",
                json={"name": "E2E"},
                headers=headers,
            ).json()["data"]
            knowledge_base = client.post(
                "/api/v1/kbs/create",
                json={"team_id": team["id"], "name": "E2E KB"},
                headers=headers,
            ).json()["data"]
            provider_response = client.post(
                "/api/v1/providers/create",
                json={
                    "team_id": team["id"],
                    "name": "E2E Provider",
                    "provider_type": "openai_chat_completions",
                    "base_url": provider_server.base_url,
                    "api_key": "sk-e2e",
                    "model_ids": ["fake-model"],
                },
                headers=headers,
            )
            assert provider_response.status_code == 201, provider_response.text
            provider = provider_response.json()["data"]
            _configure_provider(
                client,
                headers,
                team,
                knowledge_base,
                provider,
            )

            upload = client.post(
                "/api/v1/docs/upload",
                data={"team_id": team["id"], "kb_id": knowledge_base["id"]},
                files={
                    "file": (
                        "guide.md",
                        b"# Virtual Threads\n\n"
                        b"Virtual threads are lightweight Java threads.\n\n"
                        b"## Scheduling\n\n"
                        b"The JVM schedules virtual threads on carrier threads.\n",
                    )
                },
                headers=headers,
            )
            print("upload", upload.status_code, upload.text[:300])
            assert upload.status_code == 202, upload.text
            document = upload.json()["data"]["document"]
            chunks = client.get(
                "/api/v1/chunks",
                params={
                    "team_id": team["id"],
                    "document_id": document["id"],
                },
                headers=headers,
            )
            print("chunks", chunks.status_code, len(chunks.json().get("data", [])))
            assert chunks.status_code == 200, chunks.text
            assert chunks.json()["data"], "expected document chunks"
            chat = client.post(
                "/api/v1/chats/create",
                json={
                    "team_id": team["id"],
                    "title": "E2E chat",
                    "knowledge_base_ids": [knowledge_base["id"]],
                },
                headers=headers,
            ).json()["data"]

            for stream in (False, True):
                ask = client.post(
                    "/api/v1/chats/ask",
                    json={
                        "team_id": team["id"],
                        "chat_id": chat["id"],
                        "question": "What are virtual threads?",
                        "provider_id": provider["id"],
                        "model_id": "fake-model",
                        "stream": stream,
                    },
                    headers=headers,
                )
                print("ask", stream, ask.status_code, ask.text[:600])
                assert ask.status_code == 200, ask.text

                if stream:
                    events = _sse_events(ask.text)
                    streamed_text = "".join(
                        event["data"]["text"]
                        for event in events
                        if event["event"] == "delta"
                    )
                    assert streamed_text == FAKE_ANSWER
                    done = next(
                        event for event in events if event["event"] == "done"
                    )
                    message = client.get(
                        "/api/v1/messages/detail",
                        params={
                            "team_id": team["id"],
                            "message_id": done["data"]["message_id"],
                        },
                        headers=headers,
                    )
                    assert message.status_code == 200, message.text
                    trace_id = message.json()["data"]["trace_id"]
                else:
                    payload = ask.json()["data"]
                    assert payload["content"] == FAKE_ANSWER
                    assert payload["citations"], "expected citations"
                    trace_id = payload["trace_id"]

                trace = client.get(
                    "/api/v1/traces/detail",
                    params={"team_id": team["id"], "trace_id": trace_id},
                    headers=headers,
                )
                assert trace.status_code == 200, trace.text
                model = trace.json()["data"]["model"]
                assert model["provider_id"] == provider["id"]
                assert model["model_id"] == "fake-model"
                assert model["route"] == "openai_chat_completions"
                assert model["external"] is True
                assert "sk-e2e" not in ask.text
                _assert_provider_call(provider_server, stream)

    print("e2e OK stream/non-stream provider and trace")


if __name__ == "__main__":
    main()
