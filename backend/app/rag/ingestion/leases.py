"""Database leases serialize team index publication across worker processes."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from backend.app.db.models import ProcessingLease
from backend.app.rag.embedding.service import EmbeddingError


class IngestionBusy(EmbeddingError):
    """Index contention requires rescheduling, not a processing failure."""

    def __init__(self):
        super().__init__("INGESTION_BUSY", "Another index operation is running for this team.")
        self.retryable = True


@contextmanager
def team_lease(session, team_id):
    now = datetime.now(timezone.utc)
    owner = uuid4().hex
    session.execute(delete(ProcessingLease).where(ProcessingLease.team_id == team_id, ProcessingLease.expires_at < now))
    session.add(ProcessingLease(team_id=team_id, owner=owner, expires_at=now + timedelta(seconds=3700)))
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise IngestionBusy() from error
    try:
        yield
    finally:
        session.rollback()
        session.execute(delete(ProcessingLease).where(ProcessingLease.team_id == team_id, ProcessingLease.owner == owner))
        session.commit()
