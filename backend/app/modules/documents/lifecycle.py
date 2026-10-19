"""Document retention and physical purge lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.storage import ObjectStorageUnavailable, delete_s3_object
from backend.app.core.config import Settings
from backend.app.db.models import ChunkRecord, Document, IndexGenerationRecord, KnowledgeBase
from backend.app.modules.audit.service import write_audit
from backend.app.rag.indexing.maintenance import delete_document_from_indexes


class DocumentPurgeError(RuntimeError):
    """Raised when a document's physical resources cannot be purged safely."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def retention_expires_at(
    document: Document,
    settings: Settings,
) -> Optional[datetime]:
    if document.deleted_at is None:
        return None
    deleted_at = document.deleted_at
    if deleted_at.tzinfo is None:
        deleted_at = deleted_at.replace(tzinfo=timezone.utc)
    return deleted_at.astimezone(timezone.utc) + timedelta(
        days=settings.document_retention_days
    )


def retention_expired(
    document: Document,
    settings: Settings,
    *,
    now: Optional[datetime] = None,
) -> bool:
    if document.purged_at is not None:
        return True
    expires_at = retention_expires_at(document, settings)
    if expires_at is None:
        return False
    current = now or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) >= expires_at


def _managed_local_path(upload_dir: str, value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    root = Path(upload_dir).expanduser().resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def _generation_ids(session: Session, document: Document) -> list[str]:
    generations = set(
        session.scalars(
            select(ChunkRecord.index_generation).where(
                ChunkRecord.document_id == document.id,
                ChunkRecord.index_generation != "",
            )
        ).all()
    )
    knowledge_base = session.get(KnowledgeBase, document.knowledge_base_id)
    if knowledge_base is not None:
        active_generation = session.scalar(
            select(IndexGenerationRecord.id).where(
                IndexGenerationRecord.team_id == knowledge_base.team_id,
                IndexGenerationRecord.status == "active",
            )
        )
        if active_generation:
            generations.add(active_generation)
    return sorted(item for item in generations if item)


def _remove_local_resources(document: Document, settings: Settings) -> None:
    source_path = _managed_local_path(settings.upload_dir, document.source_uri)
    if source_path is not None:
        source_path.unlink(missing_ok=True)
    cache_path = _managed_local_path(
        settings.upload_dir,
        str(Path(settings.upload_dir) / "cache" / (document.id + ".download")),
    )
    if cache_path is not None:
        cache_path.unlink(missing_ok=True)


def purge_document_record(
    session: Session,
    document: Document,
    settings: Settings,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Purge indexes and physical resources for one soft-deleted document."""

    if document.purged_at is not None:
        return True
    if document.deleted_at is None:
        raise DocumentPurgeError("The document has no delete timestamp.")

    try:
        if settings.enable_indexing:
            for generation_id in _generation_ids(session, document):
                asyncio.run(
                    delete_document_from_indexes(
                        settings,
                        generation_id,
                        document.id,
                    )
                )
        object_uri = document.object_uri
        if not object_uri and (document.source_uri or "").startswith("s3://"):
            object_uri = document.source_uri
        if object_uri:
            delete_s3_object(object_uri, settings)
    except Exception as error:  # noqa: BLE001
        raise DocumentPurgeError(
            "Document indexes or object storage could not be purged."
        ) from error

    _remove_local_resources(document, settings)
    document.purged_at = now or _utc_now()
    knowledge_base = session.get(KnowledgeBase, document.knowledge_base_id)
    write_audit(
        session,
        team_id=knowledge_base.team_id if knowledge_base is not None else None,
        actor_id=None,
        action="document.purge",
        resource_type="document",
        resource_id=document.id,
        details={"purged_at": document.purged_at},
    )
    return True


def purge_expired_documents_record(
    session: Session,
    settings: Settings,
    *,
    now: Optional[datetime] = None,
    limit: int = 100,
) -> dict:
    current = now or _utc_now()
    cutoff = current - timedelta(days=settings.document_retention_days)
    documents = session.scalars(
        select(Document)
        .where(
            Document.doc_status.in_(["deleted", "deleting"]),
            Document.deleted_at.is_not(None),
            Document.deleted_at <= cutoff,
            Document.purged_at.is_(None),
        )
        .order_by(Document.deleted_at.asc())
        .limit(max(1, min(limit, 1000)))
    ).all()
    purged: list[str] = []
    failed: list[dict[str, str]] = []
    for document in documents:
        try:
            purge_document_record(session, document, settings, now=current)
            session.commit()
            purged.append(document.id)
        except DocumentPurgeError as error:
            session.rollback()
            failed.append({"document_id": document.id, "error": str(error)})
    return {
        "scanned": len(documents),
        "purged": purged,
        "failed": failed,
    }
