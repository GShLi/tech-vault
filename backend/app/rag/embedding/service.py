"""Embedding client with a deterministic local fallback."""

from __future__ import annotations

import hashlib
import math
import re
from typing import List

import httpx


_TOKEN_RE = re.compile(r"[A-Za-z0-9_.:/#-]+|[\u4e00-\u9fff]+")


def hash_embedding(text: str, dimension: int = 1024) -> List[float]:
    """Deterministic feature-hashing vector used when no model server is up."""
    vector = [0.0] * dimension
    for token in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % dimension
        sign = 1.0 if (value >> 63) & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0:
        return vector
    return [item / norm for item in vector]


class EmbeddingClient:
    def __init__(self, base_url: str, dimension: int = 1024, timeout: float = 30.0):
        self._base = base_url.rstrip("/")
        self._dimension = dimension
        self._timeout = timeout

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        try:
            with httpx.Client(
                base_url=self._base,
                timeout=self._timeout,
                trust_env=False,
            ) as client:
                response = client.post("/embed", json={"texts": texts})
                response.raise_for_status()
                vectors = response.json()["vectors"]
                if len(vectors) == len(texts):
                    return vectors
        except Exception:
            pass
        return [hash_embedding(text, self._dimension) for text in texts]
