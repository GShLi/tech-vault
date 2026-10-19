import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


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


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)

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


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> object:
        return _normalize_email(value)


class UserView(BaseModel):
    id: str
    email: str
    display_name: str
    status: str
    created_at: datetime


class MembershipView(BaseModel):
    team_id: str
    team_name: str
    role: str
    status: str


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
    version: int
    created_at: datetime
    updated_at: datetime


class DocumentDetailView(DocumentView):
    owner_user_id: str
    current_version_id: Optional[str]
    source_uri: Optional[str]
    version_family: Optional[str]


class IngestionRunView(BaseModel):
    id: str
    document_version_id: str
    status: str
    current_stage: Optional[str]
    stage_progress_pct: int
    error_code: Optional[str]
    retryable: bool
    created_at: datetime
    updated_at: datetime
