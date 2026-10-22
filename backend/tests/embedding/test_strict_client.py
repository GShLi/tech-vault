import httpx
import pytest
from backend.app.rag.embedding.service import EmbeddingClient, EmbeddingError


def client(payload, status=200):
    return EmbeddingClient("http://embedding", dimension=2, allow_hash_fallback=False,
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)))


def test_tokenizer_model_and_response_validation():
    assert client({"counts": [3], "model": "BAAI/bge-m3"}).tokenize(["abc"]) == [3]
    for payload in ({"counts": [True], "model": "BAAI/bge-m3"}, {"counts": [3], "model": "wrong"}):
        with pytest.raises(EmbeddingError, match="Unexpected model|TOKENIZER_RESPONSE_INVALID"):
            client(payload).tokenize(["abc"])


def test_strict_embedding_never_falls_back():
    with pytest.raises(EmbeddingError, match="EMBEDDING_UNAVAILABLE"):
        client({}, 503).embed(["text"])
    with pytest.raises(EmbeddingError, match="EMBEDDING_DIMENSION_MISMATCH"):
        client({"vectors": [[1]], "model": "BAAI/bge-m3", "dimension": 1}).embed(["text"])
    with pytest.raises(EmbeddingError, match="Zero vectors"):
        client({"vectors": [[0, 0]], "model": "BAAI/bge-m3", "dimension": 2}).embed(["text"])
    assert client({"vectors": [[1, 0]], "model": "BAAI/bge-m3", "dimension": 2}).embed(["text"]) == [[1, 0]]
