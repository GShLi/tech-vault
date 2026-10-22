"""Explicit local model doubles for API/index integration tests."""
import re

import pytest


@pytest.fixture(autouse=True)
def local_ingestion_models(request, monkeypatch):
    # These suites exercise orchestration; strict HTTP contracts have their own suite.
    if not any(part in request.node.path.parts for part in ("api", "indexing", "sources", "e2e")):
        return
    from backend.app.rag.embedding.service import EmbeddingClient, hash_embedding
    monkeypatch.setattr(EmbeddingClient, "tokenize", lambda self, texts: [
        len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", text)) + 2 for text in texts
    ])
    monkeypatch.setattr(EmbeddingClient, "embed", lambda self, texts: [hash_embedding(text, self._dimension) for text in texts])
