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


class EmbeddingError(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.retryable = code in {"TOKENIZER_UNAVAILABLE", "EMBEDDING_UNAVAILABLE"}


def validate_vectors(vectors, expected_count, dimension):
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Embedding count mismatch.")
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimension:
            raise EmbeddingError("EMBEDDING_DIMENSION_MISMATCH")
        if any(isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) for value in vector):
            raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Vectors must contain finite numbers.")
        if not any(value != 0 for value in vector):
            raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Zero vectors are forbidden.")


class EmbeddingClient:
    def __init__(self, base_url: str, dimension: int = 1024, timeout: float = 30.0,
                 *, transport=None, allow_hash_fallback=True, model="BAAI/bge-m3", batch_size=64):
        if not 1 <= batch_size <= 256:
            raise ValueError("Invalid embedding batch size")
        self._base = base_url.rstrip("/")
        self._dimension = dimension
        self._timeout = timeout
        self._transport = transport
        self._allow_hash_fallback = allow_hash_fallback
        self.model = model
        self.batch_size = batch_size

    def _request(self, path, texts):
        unavailable = "TOKENIZER_UNAVAILABLE" if path == "/tokenize" else "EMBEDDING_UNAVAILABLE"
        invalid = "TOKENIZER_RESPONSE_INVALID" if path == "/tokenize" else "EMBEDDING_RESPONSE_INVALID"
        for attempt in range(3):
            try:
                with httpx.Client(base_url=self._base, timeout=self._timeout,
                                  transport=self._transport, trust_env=False) as client:
                    response = client.post(path, json={"texts": texts})
                    response.raise_for_status()
                    payload = response.json()
                if not isinstance(payload, dict) or payload.get("model") != self.model:
                    raise EmbeddingError(invalid, "Unexpected model identity.")
                return payload
            except EmbeddingError:
                raise
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                transient = not isinstance(error, httpx.HTTPStatusError) or error.response.status_code in {408, 429, 500, 502, 503, 504}
                if not transient or attempt == 2:
                    raise EmbeddingError(unavailable) from error
            except (ValueError, KeyError, TypeError) as error:
                raise EmbeddingError(invalid) from error

    def tokenize(self, texts: List[str]) -> List[int]:
        counts = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            payload = self._request("/tokenize", batch)
            values = payload.get("counts")
            if not isinstance(values, list) or len(values) != len(batch) or any(type(n) is not int or n < 0 for n in values):
                raise EmbeddingError("TOKENIZER_RESPONSE_INVALID")
            counts.extend(values)
        return counts

    def embed(self, texts: List[str]) -> List[List[float]]:
        vectors = []
        try:
            for start in range(0, len(texts), self.batch_size):
                batch = texts[start:start + self.batch_size]
                payload = self._request("/embed", batch)
                if payload.get("dimension") != self._dimension:
                    raise EmbeddingError("EMBEDDING_DIMENSION_MISMATCH")
                values = payload.get("vectors")
                validate_vectors(values, len(batch), self._dimension)
                vectors.extend(values)
            return vectors
        except EmbeddingError:
            if not self._allow_hash_fallback:
                raise
            return [hash_embedding(text, self._dimension) for text in texts]
