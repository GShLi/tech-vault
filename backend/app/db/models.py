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
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"), index=True)
    refresh_jti: Mapped[str] = mapped_column(String(26), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
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
    model_policy_mode: Mapped[str] = mapped_column(String(24), default="local_only")
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
    team_id: Mapped[str] = mapped_column(String(26), default="", index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(26), default="", index=True)
    owner_user_id: Mapped[str] = mapped_column(String(26), default="")
    visibility: Mapped[str] = mapped_column(String(16), default="team_shared")
    data_classification: Mapped[str] = mapped_column(String(16), default="internal")
    doc_status: Mapped[str] = mapped_column(String(16), default="active")
    chunk_status: Mapped[str] = mapped_column(String(16), default="enabled")
    content: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[str] = mapped_column(Text, default="[]")
    source_locator: Mapped[str] = mapped_column(Text, default="{}")
    version_values: Mapped[str] = mapped_column(Text, default="[]")
    logical_chunk_key: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(128), default="")
    source_path: Mapped[str] = mapped_column(String(500), default="")
    index_generation: Mapped[str] = mapped_column(String(26), default="")
    status: Mapped[str] = mapped_column(String(16), default="enabled")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )


class DocumentGrant(Base):
    __tablename__ = "document_grants"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    document_id: Mapped[str] = mapped_column(String(26), ForeignKey("documents.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"), index=True)
    granted_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    dataset_id: Mapped[str] = mapped_column(String(26), ForeignKey("evaluation_datasets.id"), index=True)
    engine_mode: Mapped[str] = mapped_column(String(20), default="dual_engine")
    status: Mapped[str] = mapped_column(String(16), default="queued")
    baseline_run_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    created_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    invited_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ModelProvider(Base):
    __tablename__ = "model_providers"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[Optional[str]] = mapped_column(
        String(26), ForeignKey("teams.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    provider_type: Mapped[str] = mapped_column(String(40))
    base_url: Mapped[str] = mapped_column(String(500))
    model_ids: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class ModelPolicyRecord(Base):
    __tablename__ = "model_policies"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    mode: Mapped[str] = mapped_column(String(24), default="local_only")
    allowed_provider_ids: Mapped[str] = mapped_column(Text, default="[]")
    max_data_classification: Mapped[str] = mapped_column(String(16), default="internal")
    allow_chat_history: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_document_metadata: Mapped[bool] = mapped_column(Boolean, default=False)
    require_redaction: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    provider_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    model_id: Mapped[str] = mapped_column(String(120), default="")
    purpose: Mapped[str] = mapped_column(String(40), default="answer")
    classification: Mapped[str] = mapped_column(String(16), default="internal")
    external: Mapped[bool] = mapped_column(Boolean, default=False)
    request_id: Mapped[str] = mapped_column(String(80), default="")
    cost_micros: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    dataset_id: Mapped[str] = mapped_column(String(26), ForeignKey("evaluation_datasets.id"), index=True)
    query_id: Mapped[str] = mapped_column(String(120))
    query_type: Mapped[str] = mapped_column(String(40))
    query: Mapped[str] = mapped_column(Text)
    relevant_chunk_ids: Mapped[str] = mapped_column(Text, default="[]")
    filters: Mapped[str] = mapped_column(Text, default="{}")
    relevance: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    run_id: Mapped[str] = mapped_column(String(26), ForeignKey("evaluation_runs.id"), index=True)
    metrics: Mapped[str] = mapped_column(Text, default="{}")
    report: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class TraceRecord(Base):
    __tablename__ = "retrieval_traces"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    chat_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    engine_mode: Mapped[str] = mapped_column(String(24), default="dual_engine")
    original_query: Mapped[str] = mapped_column(Text)
    rewritten_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filters: Mapped[str] = mapped_column(Text, default="{}")
    bm25_candidates: Mapped[str] = mapped_column(Text, default="[]")
    dense_candidates: Mapped[str] = mapped_column(Text, default="[]")
    rrf_candidates: Mapped[str] = mapped_column(Text, default="[]")
    rerank_candidates: Mapped[str] = mapped_column(Text, default="[]")
    final_context: Mapped[str] = mapped_column(Text, default="[]")
    stage_latency_ms: Mapped[str] = mapped_column(Text, default="{}")
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    model: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    message_id: Mapped[str] = mapped_column(String(26), ForeignKey("messages.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    feedback_type: Mapped[str] = mapped_column(String(24))
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class SourceConnection(Base):
    __tablename__ = "source_connections"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    kb_id: Mapped[str] = mapped_column(String(26), ForeignKey("knowledge_bases.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(24), default="github")
    repo_url: Mapped[str] = mapped_column(String(500))
    branch: Mapped[str] = mapped_column(String(120), default="main")
    path_filters: Mapped[str] = mapped_column(Text, default="[]")
    credentials_id: Mapped[Optional[str]] = mapped_column(String(26), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    sync_cursor: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    secret_masked: Mapped[str] = mapped_column(String(40))
    created_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class IndexGenerationRecord(Base):
    __tablename__ = "index_generations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="staging")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str] = mapped_column(String(120), default="bge-m3")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    validation_errors: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    validated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime(), nullable=True)


class ChunkHistory(Base):
    __tablename__ = "chunk_history"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    chunk_id: Mapped[str] = mapped_column(String(26), ForeignKey("chunks.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    old_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
