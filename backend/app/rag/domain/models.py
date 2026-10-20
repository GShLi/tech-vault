from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class DataClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    RESTRICTED = "restricted"


class Role(str, Enum):
    ADMIN = "admin"
    LEADER = "leader"
    MEMBER = "member"
    VIEWER = "viewer"


class Visibility(str, Enum):
    PRIVATE = "private"
    TEAM_SHARED = "team_shared"


class DocumentStatus(str, Enum):
    ACTIVE = "active"
    BUILDING = "building"
    DELETING = "deleting"
    DELETED = "deleted"
    FAILED = "failed"


class ChunkStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class AuthorizationContext:
    user_id: str
    team_ids: Tuple[str, ...]
    knowledge_base_ids: Tuple[str, ...]
    role: Role
    explicit_document_grants: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalFilters:
    team_id: str
    knowledge_base_ids: Tuple[str, ...]
    viewer_user_id: str
    product: Optional[str] = None
    version_values: Tuple[str, ...] = ()
    include_private_owned_by_viewer: bool = True
    explicit_document_grants: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    document_version_id: str
    team_id: str
    knowledge_base_id: str
    owner_user_id: str
    visibility: Visibility
    data_classification: DataClassification
    source_path: str
    heading_path: Tuple[str, ...]
    content: str
    logical_chunk_key: str
    content_hash: str
    source_locator: Dict[str, Any] = field(default_factory=dict)
    content_vector: List[float] = field(default_factory=list)
    product: Optional[str] = None
    version_values: Tuple[str, ...] = ()
    doc_status: DocumentStatus = DocumentStatus.ACTIVE
    chunk_status: ChunkStatus = ChunkStatus.ENABLED
    index_generation: str = ""


@dataclass(frozen=True)
class SearchRequest:
    query: str
    rewritten_query: Optional[str]
    query_vector: List[float]
    filters: RetrievalFilters
    bm25_top_k: int = 50
    dense_top_k: int = 50
    rrf_k: int = 60
    rerank_input_size: int = 50
    final_top_n: int = 10


@dataclass(frozen=True)
class FusedCandidate:
    chunk_id: str
    fused_score: float
    fused_rank: int
    bm25_rank: Optional[int] = None
    dense_rank: Optional[int] = None


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    document_version_id: str
    content: str
    fused_rank: int
    bm25_rank: Optional[int] = None
    dense_rank: Optional[int] = None
    rerank_score: Optional[float] = None
    matched_terms: Tuple[str, ...] = ()
    source_locator: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    chunks: List[RetrievedChunk]
    stage_latency: Dict[str, float]
    degraded: bool
    trace_id: str
    bm25_candidates: Tuple[RetrievedChunk, ...] = ()
    dense_candidates: Tuple[RetrievedChunk, ...] = ()
    rrf_candidates: Tuple[RetrievedChunk, ...] = ()
    rerank_candidates: Tuple[RetrievedChunk, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    errors: Tuple[str, ...] = ()
    checked_chunks: int = 0


@dataclass(frozen=True)
class ModelPolicyDecision:
    allow_external: bool
    allowed_provider_ids: Tuple[str, ...]
    max_data_classification: DataClassification
    allowed_model_ids: Tuple[str, ...]
    allow_chat_history: bool
    allow_document_metadata: bool
    require_redaction: bool
    fallback_mode: str
    reason_code: str
    policy_version: str

