from backend.app.rag.embedding import service as embedding_service


def test_embedding_client_bypasses_system_proxy_for_local_model_service(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"vectors": [[0.1, 0.2]]}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(embedding_service.httpx, "Client", Client)

    vectors = embedding_service.EmbeddingClient(
        "http://127.0.0.1:58001"
    ).embed(["virtual threads"])

    assert vectors == [[0.1, 0.2]]
    assert captured["trust_env"] is False
