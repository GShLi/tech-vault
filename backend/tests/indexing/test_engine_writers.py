import json
import uuid

from backend.app.rag.indexing.elasticsearch import ElasticsearchIndexWriter
from backend.app.rag.indexing.qdrant import _point_id


def test_elasticsearch_bulk_body_is_newline_delimited_json():
    body = ElasticsearchIndexWriter._bulk_body(
        [{"index": {"_id": "chunk-1"}}, {"chunk_id": "chunk-1"}]
    )
    lines = body.splitlines()

    assert body.endswith("\n")
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"index": {"_id": "chunk-1"}}
    assert json.loads(lines[1]) == {"chunk_id": "chunk-1"}


def test_qdrant_point_id_is_a_deterministic_uuid():
    first = _point_id("chunk-1")
    second = _point_id("chunk-1")

    assert first == second
    assert str(uuid.UUID(first)) == first
