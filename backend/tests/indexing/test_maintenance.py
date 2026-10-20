import asyncio

import pytest

import backend.app.rag.indexing.maintenance as maintenance_module
from backend.app.core.config import Settings


class _Writer:
    def __init__(self):
        self.documents = []
        self.statuses = []
        self.updates = []

    async def delete_document(self, generation_id, document_id):
        self.documents.append((generation_id, document_id))

    async def set_chunk_status(self, generation_id, chunk_id, status):
        self.statuses.append((generation_id, chunk_id, status))

    async def update_chunk(self, generation_id, chunk_id, content, vector):
        self.updates.append((generation_id, chunk_id, content, vector))


def _settings():
    return Settings(
        environment="test",
        jwt_secret="test-secret-at-least-32-bytes-long",
        enable_indexing=True,
    )


def test_delete_document_from_all_configured_indexes(monkeypatch):
    writers = [_Writer(), _Writer()]
    monkeypatch.setattr(maintenance_module, "build_index_writers", lambda *_: writers)

    asyncio.run(
        maintenance_module.delete_document_from_indexes(
            _settings(), "generation-1", "document-1"
        )
    )

    assert [writer.documents for writer in writers] == [
        [("generation-1", "document-1")],
        [("generation-1", "document-1")],
    ]


def test_set_chunk_status_in_all_configured_indexes(monkeypatch):
    writers = [_Writer(), _Writer()]
    monkeypatch.setattr(maintenance_module, "build_index_writers", lambda *_: writers)

    asyncio.run(
        maintenance_module.set_chunk_status_in_indexes(
            _settings(), "generation-1", "chunk-1", "disabled"
        )
    )

    assert [writer.statuses for writer in writers] == [
        [("generation-1", "chunk-1", "disabled")],
        [("generation-1", "chunk-1", "disabled")],
    ]


def test_update_chunk_content_in_all_configured_indexes(monkeypatch):
    writers = [_Writer(), _Writer()]
    monkeypatch.setattr(maintenance_module, "build_index_writers", lambda *_: writers)

    asyncio.run(
        maintenance_module.update_chunk_in_indexes(
            _settings(), "generation-1", "chunk-1", "Updated", [0.1, 0.2]
        )
    )

    assert [writer.updates for writer in writers] == [
        [("generation-1", "chunk-1", "Updated", [0.1, 0.2])],
        [("generation-1", "chunk-1", "Updated", [0.1, 0.2])],
    ]


def test_chunk_status_update_compensates_engines_written_before_failure(monkeypatch):
    class FailingWriter(_Writer):
        async def set_chunk_status(self, generation_id, chunk_id, status):
            if status == "disabled":
                raise RuntimeError("qdrant unavailable")
            self.statuses.append((generation_id, chunk_id, status))

    first = _Writer()
    failing = FailingWriter()
    monkeypatch.setattr(
        maintenance_module,
        "build_index_writers",
        lambda *_: [first, failing],
    )

    with pytest.raises(maintenance_module.IndexMaintenanceError):
        asyncio.run(
            maintenance_module.set_chunk_status_in_indexes(
                _settings(),
                "generation-1",
                "chunk-1",
                "disabled",
                previous_status="enabled",
            )
        )

    assert first.statuses == [
        ("generation-1", "chunk-1", "disabled"),
        ("generation-1", "chunk-1", "enabled"),
    ]


def test_chunk_update_compensates_engines_written_before_failure(monkeypatch):
    class FailingWriter(_Writer):
        async def update_chunk(self, generation_id, chunk_id, content, vector):
            if content == "Updated":
                raise RuntimeError("qdrant unavailable")
            self.updates.append((generation_id, chunk_id, content, vector))

    first = _Writer()
    failing = FailingWriter()
    monkeypatch.setattr(
        maintenance_module,
        "build_index_writers",
        lambda *_: [first, failing],
    )

    with pytest.raises(maintenance_module.IndexMaintenanceError):
        asyncio.run(
            maintenance_module.update_chunk_in_indexes(
                _settings(),
                "generation-1",
                "chunk-1",
                "Updated",
                [0.1, 0.2],
                previous_content="Original",
                previous_vector=[0.3, 0.4],
            )
        )

    assert first.updates == [
        ("generation-1", "chunk-1", "Updated", [0.1, 0.2]),
        ("generation-1", "chunk-1", "Original", [0.3, 0.4]),
    ]
