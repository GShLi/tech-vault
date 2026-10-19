from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.ids import new_ulid
from backend.app.db.base import Base, UTCDateTime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    knowledge_base_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("knowledge_bases.id"), index=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id")
    )
    file_name: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(20), default="upload")
    source_uri: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    product: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    version_family: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    version_values: Mapped[str] = mapped_column(Text, default="[]")
    visibility: Mapped[str] = mapped_column(String(16), default="team_shared")
    data_classification: Mapped[str] = mapped_column(String(16), default="internal")
    doc_status: Mapped[str] = mapped_column(String(16), default="building")
    current_version_id: Mapped[Optional[str]] = mapped_column(
        String(26), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    document_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("documents.id"), index=True
    )
    content_fingerprint: Mapped[str] = mapped_column(String(128))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="building")
    index_generation: Mapped[Optional[str]] = mapped_column(
        String(26), nullable=True
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    document_version_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("document_versions.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued")
    current_stage: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    stage_progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("teams.id"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_knowledge_base_team_name"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )



class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    knowledge_base_ids: Mapped[str] = mapped_column(Text, default="[]")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    chat_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("chats.id"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), default="user")
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="generating")
    trace_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    citation_ids: Mapped[str] = mapped_column(Text, default="[]")
    refusal_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ChunkRecord(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    document_id: Mapped[str] = mapped_column(String(26), ForeignKey("documents.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[str] = mapped_column(Text, default="[]")
    source_locator: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="enabled")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )
