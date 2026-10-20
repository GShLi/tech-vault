import asyncio
import json
import uuid

import httpx
import pytest

from backend.app.rag.indexing.elasticsearch import (
    ElasticsearchIndexWriter,
    index_name_for_generation,
)
from backend.app.rag.indexing.qdrant import QdrantIndexWriter, _point_id


def test_elasticsearch_bulk_body_is_newline_delimited_json():
    body = ElasticsearchIndexWriter._bulk_body(
        [{"index": {"_id": "chunk-1"}}, {"chunk_id": "chunk-1"}]
    )
    lines = body.splitlines()

    assert body.endswith("\n")
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"index": {"_id": "chunk-1"}}
    assert json.loads(lines[1]) == {"chunk_id": "chunk-1"}


def test_elasticsearch_index_name_lowercases_ulid_generation_ids():
    assert (
        index_name_for_generation("01M5A1TMFHTAMADZY2B8M0RFCX")
        == "techvault-chunks-01m5a1tmfhtamadzy2b8m0rfcx"
    )


def test_elasticsearch_index_uses_search_time_java_jdk_synonyms(monkeypatch):
    writer = ElasticsearchIndexWriter("http://elasticsearch")
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "HEAD":
            request_value = httpx.Request("HEAD", "http://elasticsearch/" + path)
            response = httpx.Response(404, request=request_value)
            raise httpx.HTTPStatusError(
                "not found",
                request=request_value,
                response=response,
            )
        return None

    monkeypatch.setattr(writer, "_request", request)

    asyncio.run(writer._ensure_index("generation-synonyms"))

    body = calls[-1][2]["json"]
    assert body["settings"]["analysis"]["filter"]["tech_synonyms"]["type"] == (
        "synonym_graph"
    )
    assert "java 11, java11, jdk 11, jdk11" in body["settings"]["analysis"][
        "filter"
    ]["tech_synonyms"]["synonyms"]
    assert (
        body["settings"]["analysis"]["analyzer"]["tech_search"][
            "tokenizer"
        ]
        == "standard"
    )
    assert body["mappings"]["properties"]["content"]["analyzer"] == "standard"
    assert (
        body["mappings"]["properties"]["content"]["search_analyzer"]
        == "tech_search"
    )
    assert body["mappings"]["_meta"]["synonym_version"]


def test_qdrant_point_id_is_a_deterministic_uuid():
    first = _point_id("chunk-1")
    second = _point_id("chunk-1")

    assert first == second
    assert str(uuid.UUID(first)) == first


def test_elasticsearch_delete_document_removes_all_document_chunks(monkeypatch):
    writer = ElasticsearchIndexWriter("http://elasticsearch")
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))

    monkeypatch.setattr(writer, "_request", request)

    asyncio.run(writer.delete_document("generation-1", "document-1"))

    assert calls == [
        (
            "POST",
            "/techvault-chunks-generation-1/_delete_by_query",
            {
                "params": {"refresh": "true", "conflicts": "proceed"},
                "json": {"query": {"term": {"document_id": "document-1"}}},
            },
        )
    ]


def test_qdrant_delete_document_removes_all_document_points(monkeypatch):
    writer = QdrantIndexWriter("http://qdrant")
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))

    monkeypatch.setattr(writer, "_request", request)

    asyncio.run(writer.delete_document("generation-1", "document-1"))

    assert calls == [
        (
            "POST",
            "/collections/techvault_chunks_generation-1/points/delete",
            {
                "params": {"wait": "true"},
                "json": {
                    "filter": {
                        "must": [
                            {"key": "document_id", "match": {"value": "document-1"}}
                        ]
                    }
                },
            },
        )
    ]


@pytest.mark.parametrize(
    ("writer", "expected"),
    [
        (
            ElasticsearchIndexWriter("http://elasticsearch"),
            (
                "POST",
                "/techvault-chunks-generation-1/_update/chunk-1",
                {"json": {"doc": {"chunk_status": "disabled"}}},
            ),
        ),
        (
            QdrantIndexWriter("http://qdrant"),
            (
                "POST",
                "/collections/techvault_chunks_generation-1/points/payload",
                {
                    "params": {"wait": "true"},
                    "json": {
                        "payload": {"chunk_status": "disabled"},
                        "points": [str(uuid.uuid5(uuid.NAMESPACE_URL, "chunk-1"))],
                    },
                },
            ),
        ),
    ],
)
def test_writers_update_chunk_status(monkeypatch, writer, expected):
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))

    monkeypatch.setattr(writer, "_request", request)

    asyncio.run(writer.set_chunk_status("generation-1", "chunk-1", "disabled"))

    assert calls == [expected]


def test_elasticsearch_updates_chunk_content_and_vector(monkeypatch):
    writer = ElasticsearchIndexWriter("http://elasticsearch")
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))

    monkeypatch.setattr(writer, "_request", request)

    asyncio.run(
        writer.update_chunk(
            "generation-1", "chunk-1", "Updated content", [0.1, 0.2]
        )
    )

    assert calls == [
        (
            "POST",
            "/techvault-chunks-generation-1/_update/chunk-1",
            {"json": {"doc": {"content": "Updated content", "content_vector": [0.1, 0.2]}}},
        )
    ]


def test_qdrant_updates_chunk_vector_and_payload(monkeypatch):
    writer = QdrantIndexWriter("http://qdrant")
    calls = []

    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))

    monkeypatch.setattr(writer, "_request", request)

    asyncio.run(
        writer.update_chunk(
            "generation-1", "chunk-1", "Updated content", [0.1, 0.2]
        )
    )

    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "chunk-1"))
    assert calls == [
        (
            "PUT",
            "/collections/techvault_chunks_generation-1/points/vectors",
            {
                "params": {"wait": "true"},
                "json": {"points": [{"id": point_id, "vector": [0.1, 0.2]}]},
            },
        ),
        (
            "POST",
            "/collections/techvault_chunks_generation-1/points/payload",
            {
                "params": {"wait": "true"},
                "json": {"payload": {"content": "Updated content"}, "points": [point_id]},
            },
        ),
    ]
