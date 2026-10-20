"""Keep incrementally updated documents consistent across index engines."""

from __future__ import annotations

from backend.app.core.config import Settings
from backend.app.rag.retrieval.config import EngineMode
from backend.app.rag.retrieval.factory import build_index_writers


class IndexMaintenanceError(RuntimeError):
    """Raised after a partial index mutation has been compensated."""


async def delete_document_from_indexes(
    settings: Settings, generation_id: str, document_id: str
) -> None:
    if not settings.enable_indexing:
        return
    writers = build_index_writers(settings, EngineMode(settings.engine_mode))
    for writer in writers:
        await writer.delete_document(generation_id, document_id)


async def set_chunk_status_in_indexes(
    settings: Settings,
    generation_id: str,
    chunk_id: str,
    status: str,
    *,
    previous_status: str | None = None,
) -> None:
    if not settings.enable_indexing:
        return
    writers = build_index_writers(settings, EngineMode(settings.engine_mode))
    applied = []
    try:
        for writer in writers:
            await writer.set_chunk_status(generation_id, chunk_id, status)
            applied.append(writer)
    except Exception as error:  # noqa: BLE001
        if previous_status is not None:
            for writer in reversed(applied):
                try:
                    await writer.set_chunk_status(
                        generation_id,
                        chunk_id,
                        previous_status,
                    )
                except Exception:  # noqa: BLE001
                    pass
        raise IndexMaintenanceError(
            "chunk status could not be synchronized to every index"
        ) from error


async def update_chunk_in_indexes(
    settings: Settings,
    generation_id: str,
    chunk_id: str,
    content: str,
    content_vector,
    *,
    previous_content: str | None = None,
    previous_vector=None,
) -> None:
    if not settings.enable_indexing:
        return
    writers = build_index_writers(settings, EngineMode(settings.engine_mode))
    applied = []
    try:
        for writer in writers:
            await writer.update_chunk(generation_id, chunk_id, content, content_vector)
            applied.append(writer)
    except Exception as error:  # noqa: BLE001
        if previous_content is not None and previous_vector is not None:
            for writer in reversed(applied):
                try:
                    await writer.update_chunk(
                        generation_id,
                        chunk_id,
                        previous_content,
                        previous_vector,
                    )
                except Exception:  # noqa: BLE001
                    pass
        raise IndexMaintenanceError(
            "chunk content could not be synchronized to every index"
        ) from error
