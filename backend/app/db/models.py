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


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    name: Mapped[str] = mapped_column(String(120))
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

