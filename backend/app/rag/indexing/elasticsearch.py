"""Elasticsearch index writer for chunk documents."""

from __future__ import annotations

import json
from typing import Iterable, List

import httpx

from backend.app.rag.domain.models import Chunk, ValidationResult


def _index_name(generation_id: str) -> str:
    return "techvault-chunks-{0}".format(generation_id)


def index_name_for_generation(generation_id: str) -> str:
    return _index_name(generation_id)


class ElasticsearchIndexWriter:
    """Staging/validation/activation writer for a single index generation."""

    def __init__(self, base_url: str, dimension: int = 1024) -> None:
        self._base = base_url.rstrip("/")
        self._dimension = dimension
        self._staged: set = set()
        self._validated: set = set()
        self._active: str = ""

    async def _request(self, method: str, path: str, **kwargs):
        async with httpx.AsyncClient(base_url=self._base, timeout=30.0) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

    async def _ensure_index(self, generation_id: str) -> None:
        index = _index_name(generation_id)
        try:
            await self._request("HEAD", "/" + index)
            return
        except httpx.HTTPStatusError:
            pass

        body = {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "chunk_id": {"type": "keyword"},
                    "document_id": {"type": "keyword"},
                    "document_version_id": {"type": "keyword"},
                    "team_id": {"type": "keyword"},
                    "knowledge_base_id": {"type": "keyword"},
                    "owner_user_id": {"type": "keyword"},
                    "visibility": {"type": "keyword"},
                    "data_classification": {"type": "keyword"},
                    "doc_status": {"type": "keyword"},
                    "chunk_status": {"type": "keyword"},
                    "product": {"type": "keyword"},
                    "version_values": {"type": "keyword"},
                    "index_generation": {"type": "keyword"},
                    "logical_chunk_key": {"type": "keyword"},
                    "heading_path": {"type": "keyword"},
                    "content": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "content_vector": {
                        "type": "dense_vector",
                        "dims": self._dimension,
                        "index": True,
                        "similarity": "cosine",
                    },
                }
            },
        }
        await self._request("PUT", "/" + index, json=body)

    async def stage(self, generation_id: str, chunks: Iterable[Chunk]) -> None:
        if generation_id == self._active:
            raise ValueError("cannot stage into the active generation")
        await self._ensure_index(generation_id)
        index = _index_name(generation_id)

        actions: List[dict] = []
        for chunk in chunks:
            actions.append({"index": {"_id": chunk.chunk_id}})
            actions.append(self._document(chunk))

        for start in range(0, len(actions), 200):
            batch = actions[start : start + 200]
            await self._request(
                "POST",
                "/" + index + "/_bulk",
                content=self._bulk_body(batch),
                headers={"Content-Type": "application/x-ndjson"},
            )

        await self._request("POST", "/" + index + "/_refresh")
        self._staged.add(generation_id)
        self._validated.discard(generation_id)

    @staticmethod
    def _bulk_body(actions: List[dict]) -> str:
        return "".join(json.dumps(action, separators=(",", ":")) + "\n" for action in actions)

    def _document(self, chunk: Chunk) -> dict:
        vector = getattr(chunk, "content_vector", None) or []
        return {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "document_version_id": chunk.document_version_id,
            "team_id": chunk.team_id,
            "knowledge_base_id": chunk.knowledge_base_id,
            "owner_user_id": chunk.owner_user_id,
            "visibility": chunk.visibility.value
            if hasattr(chunk.visibility, "value")
            else str(chunk.visibility),
            "data_classification": chunk.data_classification.value
            if hasattr(chunk.data_classification, "value")
            else str(chunk.data_classification),
            "doc_status": chunk.doc_status.value
            if hasattr(chunk.doc_status, "value")
            else str(chunk.doc_status),
            "chunk_status": chunk.chunk_status.value
            if hasattr(chunk.chunk_status, "value")
            else str(chunk.chunk_status),
            "product": chunk.product,
            "version_values": list(chunk.version_values),
            "index_generation": chunk.index_generation or "",
            "logical_chunk_key": chunk.logical_chunk_key,
            "heading_path": list(chunk.heading_path),
            "content": chunk.content,
            "content_vector": list(vector),
        }

    async def validate(self, generation_id: str) -> ValidationResult:
        if generation_id not in self._staged:
            return ValidationResult(False, ("generation not staged",), 0)

        index = _index_name(generation_id)
        response = await self._request("GET", "/" + index + "/_count")
        total = int(response.json().get("count", 0))
        errors: tuple = ()
        if total == 0:
            errors = ("index contains no documents",)

        result = ValidationResult(not errors, errors, total)
        if result.passed:
            self._validated.add(generation_id)
        return result

    async def activate(self, generation_id: str) -> None:
        if generation_id not in self._validated:
            raise ValueError("cannot activate an unvalidated generation")
        self._active = generation_id

    def deactivate(self) -> None:
        self._active = ""

    async def cleanup(self, generation_id: str) -> None:
        if generation_id == self._active:
            raise ValueError("cannot cleanup the active generation")
        try:
            await self._request("DELETE", "/" + _index_name(generation_id))
        except httpx.HTTPStatusError:
            pass
        self._staged.discard(generation_id)
        self._validated.discard(generation_id)

    @property
    def active_generation(self) -> str:
        return self._active

    @property
    def index_name(self) -> str:
        return _index_name(self._active)
