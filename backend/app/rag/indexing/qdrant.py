"""Qdrant index writer for dense vector retrieval."""

from __future__ import annotations

import uuid
from typing import Iterable, List

import httpx

from backend.app.rag.domain.models import Chunk, ValidationResult


def _collection_name(generation_id: str) -> str:
    return "techvault_chunks_{0}".format(generation_id)


def collection_name_for_generation(generation_id: str) -> str:
    return _collection_name(generation_id)


def _value(field) -> str:
    return field.value if hasattr(field, "value") else str(field)


def _point_id(chunk_id: str) -> str:
    """Qdrant accepts UUIDs or integers, while chunk IDs are ULIDs."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


class QdrantIndexWriter:
    """Staging/validation/activation writer for a Qdrant collection."""

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

    async def _ensure_collection(self, generation_id: str) -> None:
        name = _collection_name(generation_id)
        try:
            await self._request("GET", "/collections/" + name)
            return
        except httpx.HTTPStatusError:
            pass

        body = {
            "vectors": {"size": self._dimension, "distance": "Cosine"},
        }
        await self._request("PUT", "/collections/" + name, json=body)

        for field in (
            "team_id",
            "chunk_level",
            "knowledge_base_id",
            "owner_user_id",
            "visibility",
            "data_classification",
            "doc_status",
            "chunk_status",
            "product",
            "document_id",
            "document_version_id",
            "version_values",
            "index_generation",
        ):
            await self._request(
                "PUT",
                "/collections/{0}/index".format(name),
                json={"field_name": field, "field_schema": "keyword"},
            )

    async def stage(self, generation_id: str, chunks: Iterable[Chunk]) -> None:
        if generation_id == self._active:
            raise ValueError("cannot stage into the active generation")
        await self._ensure_collection(generation_id)
        name = _collection_name(generation_id)

        points: List[dict] = []
        for chunk in chunks:
            if chunk.chunk_level != "child":
                continue
            vector = getattr(chunk, "content_vector", None) or [0.0] * self._dimension
            points.append(
                {
                    "id": _point_id(chunk.chunk_id),
                    "vector": list(vector),
                    "payload": {
                        "chunk_id": chunk.chunk_id,
                        "document_id": chunk.document_id,
                        "document_version_id": chunk.document_version_id,
                        "team_id": chunk.team_id,
                        "knowledge_base_id": chunk.knowledge_base_id,
                        "owner_user_id": chunk.owner_user_id,
                        "visibility": _value(chunk.visibility),
                        "data_classification": _value(chunk.data_classification),
                        "doc_status": _value(chunk.doc_status),
                        "chunk_status": _value(chunk.chunk_status),
                        "product": chunk.product,
                        "version_values": list(chunk.version_values),
                        "index_generation": chunk.index_generation or generation_id,
                        "content": chunk.content,
                        "source_locator": dict(chunk.source_locator),
                        **{name: getattr(chunk, name) for name in (
                            "parent_chunk_id", "chunk_level", "child_order", "node_type", "token_count", "page_no",
                            "parse_version", "chunking_version", "embedding_model", "tokenizer_model",
                        )},
                    },
                }
            )

        for start in range(0, len(points), 100):
            batch = points[start : start + 100]
            await self._request(
                "PUT",
                "/collections/{0}/points?wait=true".format(name),
                json={"points": batch},
            )

        self._staged.add(generation_id)
        self._validated.discard(generation_id)

    async def delete_document(self, generation_id: str, document_id: str) -> None:
        """Remove every dense-vector point for a document."""

        try:
            await self._request(
                "POST",
                "/collections/{0}/points/delete".format(_collection_name(generation_id)),
                params={"wait": "true"},
                json={
                    "filter": {
                        "must": [
                            {"key": "document_id", "match": {"value": document_id}}
                        ]
                    }
                },
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise

    async def delete_chunks(
        self,
        generation_id: str,
        chunk_ids: Iterable[str],
    ) -> None:
        ids = [_point_id(chunk_id) for chunk_id in chunk_ids if chunk_id]
        if not ids:
            return
        try:
            await self._request(
                "POST",
                "/collections/{0}/points/delete".format(
                    _collection_name(generation_id)
                ),
                params={"wait": "true"},
                json={"points": ids},
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise

    async def set_document_status(
        self,
        generation_id: str,
        document_id: str,
        status: str,
    ) -> None:
        try:
            await self._request(
                "POST",
                "/collections/{0}/points/payload".format(
                    _collection_name(generation_id)
                ),
                params={"wait": "true"},
                json={
                    "payload": {"doc_status": status},
                    "filter": {
                        "must": [
                            {"key": "document_id", "match": {"value": document_id}}
                        ]
                    },
                },
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise

    async def set_chunk_status(
        self, generation_id: str, chunk_id: str, status: str
    ) -> None:
        """Update retrieval status without rebuilding the chunk vector."""

        try:
            await self._request(
                "POST",
                "/collections/{0}/points/payload".format(_collection_name(generation_id)),
                params={"wait": "true"},
                json={
                    "payload": {"chunk_status": status},
                    "points": [_point_id(chunk_id)],
                },
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise

    async def update_chunk(
        self,
        generation_id: str,
        chunk_id: str,
        content: str,
        content_vector: List[float],
    ) -> None:
        name = _collection_name(generation_id)
        point_id = _point_id(chunk_id)
        try:
            await self._request(
                "PUT",
                "/collections/{0}/points/vectors".format(name),
                params={"wait": "true"},
                json={"points": [{"id": point_id, "vector": list(content_vector)}]},
            )
            await self._request(
                "POST",
                "/collections/{0}/points/payload".format(name),
                params={"wait": "true"},
                json={"payload": {"content": content}, "points": [point_id]},
            )
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise

    async def validate(self, generation_id: str) -> ValidationResult:
        if generation_id not in self._staged:
            return ValidationResult(False, ("generation not staged",), 0)

        name = _collection_name(generation_id)
        response = await self._request(
            "POST", "/collections/{0}/points/count".format(name), json={"exact": True}
        )
        total = int(response.json().get("result", {}).get("count", 0))
        errors: tuple = ("collection contains no points",) if total == 0 else ()

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
            await self._request("DELETE", "/collections/" + _collection_name(generation_id))
        except httpx.HTTPStatusError:
            pass
        self._staged.discard(generation_id)
        self._validated.discard(generation_id)

    @property
    def active_generation(self) -> str:
        return self._active

    @property
    def collection_name(self) -> str:
        return _collection_name(self._active)
