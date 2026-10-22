import re
from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    if _EMAIL_PATTERN.fullmatch(normalized) is None:
        raise ValueError("A valid email address is required.")
    return normalized


def _normalize_required_name(value: object) -> object:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        raise ValueError("Name must not be empty.")
    return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return _normalize_email(value)


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UserUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name must not be empty.")
        return normalized


class InvitationCreateRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(min_length=1, max_length=16)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return _normalize_email(value)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"leader", "member", "viewer"}:
            raise ValueError("role must be leader, member, or viewer")
        return value


class InvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=16, max_length=128)


class AdminUserCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    team_id: str = Field(min_length=1, max_length=26)
    role: str = Field(min_length=1, max_length=16)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return _normalize_email(value)

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name must not be empty.")
        return normalized

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"leader", "member", "viewer"}:
            raise ValueError("role must be leader, member, or viewer")
        return value


class AdminUserUpdateRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=26)
    status: Optional[str] = Field(default=None, min_length=1, max_length=16)
    team_id: Optional[str] = Field(default=None, min_length=1, max_length=26)
    role: Optional[str] = Field(default=None, min_length=1, max_length=16)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"active", "disabled"}:
            raise ValueError("status must be active or disabled")
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in {"leader", "member", "viewer"}:
            raise ValueError("role must be leader, member, or viewer")
        return value

    @model_validator(mode="after")
    def validate_update_fields(self):
        if self.status is None and self.team_id is None and self.role is None:
            raise ValueError("At least one of status, team_id, or role is required.")
        if (self.team_id is None) != (self.role is None):
            raise ValueError("team_id and role must be provided together.")
        return self


class UserView(BaseModel):
    id: str
    email: str
    display_name: str
    status: str
    is_super_admin: bool
    is_builtin: bool
    created_at: datetime


class MembershipView(BaseModel):
    team_id: str
    team_name: str
    role: str
    status: str


class AdminUserView(UserView):
    memberships: List[MembershipView]


class MeView(BaseModel):
    user: UserView
    memberships: List[MembershipView]


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return _normalize_required_name(value)


class TeamUpdateRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return _normalize_required_name(value)


class KnowledgeBaseCreateRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return _normalize_required_name(value)


class KnowledgeBaseUpdateRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    kb_id: str = Field(min_length=1, max_length=26)
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return _normalize_required_name(value)


class KnowledgeBaseArchiveRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    kb_id: str = Field(min_length=1, max_length=26)


class DocumentView(BaseModel):
    id: str
    knowledge_base_id: str
    file_name: str
    source_type: str
    product: Optional[str]
    version_values: List[str]
    visibility: str
    data_classification: str
    doc_status: str
    deleted_at: Optional[datetime]
    purged_at: Optional[datetime]
    version: int
    created_at: datetime
    updated_at: datetime


class DocumentDetailView(DocumentView):
    parse_metadata: dict = Field(default_factory=dict)
    chunking_metadata: dict = Field(default_factory=dict)
    quality_metrics: dict = Field(default_factory=dict)
    failure_details: dict = Field(default_factory=dict)
    owner_user_id: str
    current_version_id: Optional[str]
    source_uri: Optional[str]
    version_family: Optional[str]


class IngestionRunView(BaseModel):
    file_name: Optional[str] = None
    quality_metrics: dict = Field(default_factory=dict)
    failure_details: dict = Field(default_factory=dict)
    id: str
    document_version_id: str
    status: str
    current_stage: Optional[str]
    stage_progress_pct: int
    error_code: Optional[str]
    retryable: bool
    created_at: datetime
    updated_at: datetime


class ChatView(BaseModel):
    id: str
    team_id: str
    user_id: str
    title: str
    knowledge_base_ids: List[str]
    version: int
    created_at: datetime
    updated_at: datetime


class AskFilters(BaseModel):
    knowledge_base_ids: List[str] = Field(default_factory=list)
    product: Optional[str] = Field(default=None, max_length=120)
    version_values: List[str] = Field(default_factory=list)

    @field_validator("knowledge_base_ids", "version_values")
    @classmethod
    def validate_string_lists(cls, value: List[str]) -> List[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class AskRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    chat_id: str = Field(min_length=1, max_length=26)
    question: str = Field(min_length=1, max_length=4000)
    provider_id: str = Field(min_length=1, max_length=26)
    model_id: str = Field(min_length=1, max_length=120)
    filters: AskFilters = Field(default_factory=AskFilters)
    # Kept for older clients; nested filters are the canonical contract.
    knowledge_base_ids: List[str] = Field(default_factory=list)
    model_policy: str = "inherit"
    stream: bool = True

    @field_validator("question", "provider_id", "model_id")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("knowledge_base_ids")
    @classmethod
    def validate_legacy_knowledge_base_ids(cls, value: List[str]) -> List[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))

    @field_validator("model_policy")
    @classmethod
    def validate_model_policy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {
            "inherit",
            "local_only",
            "external_allowed",
            "external_required",
        }:
            raise ValueError("invalid model_policy")
        return normalized

    def selected_knowledge_base_ids(self) -> List[str]:
        return self.filters.knowledge_base_ids or self.knowledge_base_ids


class MessageView(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    status: str
    trace_id: Optional[str]
    citation_ids: List[Dict[str, object]]
    refusal_reason: Optional[str]
    created_at: datetime
