import json
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session, require_super_admin
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import paginate_items, paginate_scalars
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.core.secrets import encrypt_secret
from backend.app.db.models import (
    DeploymentModelPolicyRecord,
    ModelCall,
    ModelPolicyRecord,
    ModelProvider,
    User,
    utc_now,
)
from backend.app.modules.providers.discovery import (
    ModelDiscoveryError,
    discover_models,
)
from backend.app.modules.audit.service import write_audit


router = APIRouter(tags=["policies"])

_MODE_RANK = {"local_only": 0, "external_allowed": 1, "external_required": 2}
_CLASSIFICATION_RANK = {"public": 0, "internal": 1, "private": 2, "restricted": 3}

Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=26)
]
ProviderName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
ProviderType = Literal[
    "openai_responses",
    "openai_chat_completions",
    "anthropic_messages",
]
ProviderBaseUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
ModelId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ProviderStatus = Literal["active", "disabled"]


class ProviderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: Identifier
    name: ProviderName
    provider_type: ProviderType
    base_url: ProviderBaseUrl = Field(min_length=1)
    api_key: SecretStr
    model_ids: list[ModelId] = Field(default_factory=list)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("API Key must not be empty.")
        return value


class AdminProviderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProviderName
    provider_type: ProviderType
    base_url: ProviderBaseUrl = Field(min_length=1)
    api_key: SecretStr
    model_ids: list[ModelId] = Field(default_factory=list)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("API Key must not be empty.")
        return value


class AdminProviderUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: Identifier
    status: Optional[ProviderStatus] = None
    provider_type: Optional[ProviderType] = None
    base_url: Optional[ProviderBaseUrl] = None
    api_key: Optional[SecretStr] = None
    model_ids: Optional[list[ModelId]] = None

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: Optional[SecretStr]) -> Optional[SecretStr]:
        if value is not None and not value.get_secret_value().strip():
            raise ValueError("API Key must not be empty.")
        return value


class ProviderModelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: Identifier
    provider_type: ProviderType
    base_url: ProviderBaseUrl = Field(min_length=1)
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("API Key must not be empty.")
        return value


class AdminProviderModelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    base_url: ProviderBaseUrl = Field(min_length=1)
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("API Key must not be empty.")
        return value


def _masked_secret(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    return "****" + (normalized[-4:] if len(normalized) > 4 else "")


def _set_provider_api_key(provider: ModelProvider, value: SecretStr, settings) -> None:
    api_key = value.get_secret_value().strip()
    provider.api_key_masked = _masked_secret(api_key)
    provider.api_key_encrypted = encrypt_secret(api_key, settings)
    provider.api_key_updated_at = utc_now()


def _provider_view(provider: ModelProvider, *, include_endpoint: bool = True) -> dict:
    data = {
        "id": provider.id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "status": provider.status,
        "api_key_masked": provider.api_key_masked,
        "has_api_key": bool(provider.api_key_encrypted.strip()),
        "api_key_updated_at": (
            provider.api_key_updated_at.isoformat()
            if provider.api_key_updated_at is not None
            else None
        ),
    }
    if include_endpoint:
        data.update(
            {
                "base_url": provider.base_url,
                "model_ids": json.loads(provider.model_ids or "[]"),
            }
        )
    return data


def _discover_provider_models(
    *,
    provider_type: str,
    base_url: str,
    api_key: SecretStr,
) -> list[str]:
    try:
        return discover_models(
            provider_type=provider_type,
            base_url=base_url,
            api_key=api_key.get_secret_value(),
        )
    except ModelDiscoveryError as error:
        raise ApiError(error.status_code, error.code, str(error)) from error


def _policy_view(policy: ModelPolicyRecord) -> dict:
    return {
        "mode": policy.mode,
        "allowed_provider_ids": json.loads(policy.allowed_provider_ids or "[]"),
        "max_data_classification": policy.max_data_classification,
        "allow_chat_history": policy.allow_chat_history,
        "allow_document_metadata": policy.allow_document_metadata,
        "require_redaction": policy.require_redaction,
        "version": policy.version,
    }


def _default_policy() -> dict:
    return {
        "mode": "local_only",
        "allowed_provider_ids": [],
        "max_data_classification": "internal",
        "allow_chat_history": False,
        "allow_document_metadata": False,
        "require_redaction": True,
        "version": 1,
    }


def _deployment_policy(session: Session) -> DeploymentModelPolicyRecord:
    policy = session.scalar(
        select(DeploymentModelPolicyRecord).order_by(
            DeploymentModelPolicyRecord.created_at.asc()
        )
    )
    if policy is None:
        policy = DeploymentModelPolicyRecord()
        session.add(policy)
        session.commit()
    return policy


def policy_mode_ceiling(session: Session, team_id: str) -> str:
    """Return the strictest mode allowed by deployment and team policy."""
    deployment = _deployment_policy(session)
    team_policy = session.scalar(
        select(ModelPolicyRecord).where(ModelPolicyRecord.team_id == team_id)
    )
    candidates = [deployment.mode]
    if team_policy is not None:
        candidates.append(team_policy.mode)
    return min(candidates, key=lambda mode: _MODE_RANK[mode])


def _deployment_view(policy: DeploymentModelPolicyRecord) -> dict:
    return {
        "mode": policy.mode,
        "allowed_provider_ids": json.loads(policy.allowed_provider_ids or "[]"),
        "max_data_classification": policy.max_data_classification,
        "allow_chat_history": policy.allow_chat_history,
        "allow_document_metadata": policy.allow_document_metadata,
        "require_redaction": policy.require_redaction,
        "version": policy.version,
    }


def _validate_policy_values(body: dict) -> None:
    mode = body.get("mode")
    if mode is not None and mode not in _MODE_RANK:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid model policy mode.")
    classification = body.get("max_data_classification")
    if classification is not None:
        normalized = "restricted" if classification == "confidential" else classification
        if normalized not in _CLASSIFICATION_RANK:
            raise ApiError(400, "INVALID_ARGUMENT", "Invalid data classification.")
        body["max_data_classification"] = normalized


def _provider_ids(value) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ApiError(
            400,
            "INVALID_ARGUMENT",
            "allowed_provider_ids must be an array of strings.",
        )
    return list(dict.fromkeys(value))


@router.get("/model-policy")
def get_policy(
    request: Request,
    team_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    policy = session.scalar(
        select(ModelPolicyRecord).where(ModelPolicyRecord.team_id == team_id)
    )
    deployment = _deployment_policy(session)
    if policy is None:
        data = _default_policy()
        data["mode"] = "local_only"
        return envelope(data, request.state.request_id)
    if _MODE_RANK[policy.mode] > _MODE_RANK[deployment.mode]:
        policy.mode = deployment.mode
    if (
        _CLASSIFICATION_RANK[policy.max_data_classification]
        > _CLASSIFICATION_RANK[deployment.max_data_classification]
    ):
        policy.max_data_classification = deployment.max_data_classification
    deployment_providers = set(json.loads(deployment.allowed_provider_ids or "[]"))
    policy_providers = json.loads(policy.allowed_provider_ids or "[]")
    policy.allowed_provider_ids = json.dumps(
        [provider_id for provider_id in policy_providers if provider_id in deployment_providers]
    )
    session.commit()
    return envelope(
        _policy_view(policy),
        request.state.request_id,
    )


@router.post("/model-policy/update")
def update_policy(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    _validate_policy_values(body)
    deployment = _deployment_policy(session)
    policy = session.scalar(
        select(ModelPolicyRecord).where(ModelPolicyRecord.team_id == team_id)
    )
    mode = body.get("mode", policy.mode if policy is not None else "local_only")
    if _MODE_RANK[mode] > _MODE_RANK[deployment.mode]:
        raise ApiError(
            409,
            "DEPLOYMENT_POLICY_LIMIT",
            "Team policy cannot be wider than the deployment policy.",
        )
    requested_classification = body.get(
        "max_data_classification",
        policy.max_data_classification
        if policy is not None
        else deployment.max_data_classification,
    )
    if (
        _CLASSIFICATION_RANK[requested_classification]
        > _CLASSIFICATION_RANK[deployment.max_data_classification]
    ):
        raise ApiError(
            409,
            "DEPLOYMENT_POLICY_LIMIT",
            "Team policy cannot be wider than the deployment policy.",
        )
    requested_provider_ids = _provider_ids(
        body.get(
            "allowed_provider_ids",
            json.loads(policy.allowed_provider_ids or "[]")
            if policy is not None
            else [],
        )
    )
    deployment_provider_ids = set(
        json.loads(deployment.allowed_provider_ids or "[]")
    )
    if not set(requested_provider_ids).issubset(deployment_provider_ids):
        raise ApiError(
            409,
            "DEPLOYMENT_POLICY_LIMIT",
            "Team providers must be allowed by the deployment policy.",
        )
    if policy is not None:
        if _MODE_RANK[mode] > _MODE_RANK[policy.mode]:
            raise ApiError(
                409,
                "TEAM_POLICY_LIMIT",
                "Team policy updates can only tighten the existing policy.",
            )
        if (
            _CLASSIFICATION_RANK[requested_classification]
            > _CLASSIFICATION_RANK[policy.max_data_classification]
        ):
            raise ApiError(
                409,
                "TEAM_POLICY_LIMIT",
                "Team policy updates can only tighten the existing policy.",
            )
        if not set(requested_provider_ids).issubset(
            set(json.loads(policy.allowed_provider_ids or "[]"))
        ):
            raise ApiError(
                409,
                "TEAM_POLICY_LIMIT",
                "Team policy updates can only tighten the existing policy.",
            )
    requested_chat_history = bool(
        body.get(
            "allow_chat_history",
            policy.allow_chat_history if policy is not None else False,
        )
    )
    requested_document_metadata = bool(
        body.get(
            "allow_document_metadata",
            policy.allow_document_metadata if policy is not None else False,
        )
    )
    if requested_chat_history and not deployment.allow_chat_history:
        raise ApiError(
            409,
            "DEPLOYMENT_POLICY_LIMIT",
            "Chat history cannot exceed the deployment policy.",
        )
    if requested_document_metadata and not deployment.allow_document_metadata:
        raise ApiError(
            409,
            "DEPLOYMENT_POLICY_LIMIT",
            "Document metadata cannot exceed the deployment policy.",
        )
    if policy is not None and requested_chat_history and not policy.allow_chat_history:
        raise ApiError(
            409,
            "TEAM_POLICY_LIMIT",
            "Team policy updates can only tighten the existing policy.",
        )
    if (
        policy is not None
        and requested_document_metadata
        and not policy.allow_document_metadata
    ):
        raise ApiError(
            409,
            "TEAM_POLICY_LIMIT",
            "Team policy updates can only tighten the existing policy.",
        )
    if policy is None:
        policy = ModelPolicyRecord(
            team_id=team_id,
            mode="local_only",
            allowed_provider_ids="[]",
            max_data_classification="internal",
            allow_chat_history=False,
            allow_document_metadata=False,
            require_redaction=True,
            version=1,
        )
        session.add(policy)
    policy.mode = mode
    if body.get("allowed_provider_ids") is not None:
        policy.allowed_provider_ids = json.dumps(requested_provider_ids)
    if body.get("max_data_classification"):
        policy.max_data_classification = requested_classification
    policy.allow_chat_history = requested_chat_history
    policy.allow_document_metadata = requested_document_metadata
    policy.version += 1
    session.flush()
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="model_policy.team.update",
        resource_type="model_policy",
        resource_id=policy.id,
        details={
            "mode": policy.mode,
            "allowed_provider_ids": json.loads(policy.allowed_provider_ids or "[]"),
            "max_data_classification": policy.max_data_classification,
            "allow_chat_history": policy.allow_chat_history,
            "allow_document_metadata": policy.allow_document_metadata,
            "require_redaction": policy.require_redaction,
            "version": policy.version,
        },
    )
    session.commit()
    return envelope(_policy_view(policy), request.state.request_id)


@router.get("/providers")
def list_providers(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    query = (
        select(ModelProvider).where(
            (ModelProvider.team_id == team_id) | (ModelProvider.team_id.is_(None))
        )
    )
    return paginate_scalars(
        session,
        query,
        timestamp_column=ModelProvider.created_at,
        id_column=ModelProvider.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=_provider_view,
    )


@router.post("/providers/create", status_code=201)
def create_provider(
    body: ProviderCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.team_id
    _leader_or_error(session, team_id, user.id)
    provider = ModelProvider(
        team_id=team_id,
        name=body.name,
        provider_type=body.provider_type,
        base_url=body.base_url,
        model_ids=json.dumps(body.model_ids),
        created_by=user.id,
    )
    _set_provider_api_key(provider, body.api_key, request.app.state.settings)
    session.add(provider)
    session.flush()
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="provider.team.create",
        resource_type="model_provider",
        resource_id=provider.id,
        details={
            "name": provider.name,
            "provider_type": provider.provider_type,
            "model_ids": json.loads(provider.model_ids or "[]"),
        },
    )
    session.commit()
    return envelope(_provider_view(provider), request.state.request_id)


@router.post("/providers/models")
def discover_team_provider_models(
    body: ProviderModelsRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, body.team_id, user.id)
    models = _discover_provider_models(
        provider_type=body.provider_type,
        base_url=body.base_url,
        api_key=body.api_key,
    )
    return envelope(
        {"provider_type": body.provider_type, "models": models},
        request.state.request_id,
    )


@router.post("/providers/test")
def test_provider(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, body.get("team_id", ""), user.id)
    return envelope({"provider_id": body.get("provider_id"), "status": "ok"}, request.state.request_id)


@router.get("/model-calls")
def list_model_calls(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    return paginate_scalars(
        session,
        select(ModelCall).where(ModelCall.team_id == team_id),
        timestamp_column=ModelCall.created_at,
        id_column=ModelCall.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda row: {
            "id": row.id,
            "provider_id": row.provider_id,
            "model_id": row.model_id,
            "purpose": row.purpose,
            "classification": row.classification,
            "external": row.external,
            "cost_micros": row.cost_micros,
            "latency_ms": row.latency_ms,
            "created_at": row.created_at.isoformat(),
        },
    )


@router.get("/admin/model-policy")
def admin_policy(
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    return envelope(_deployment_view(_deployment_policy(session)), request.state.request_id)


@router.post("/admin/model-policy/update")
def admin_update_policy(
    body: dict,
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    _validate_policy_values(body)
    policy = _deployment_policy(session)
    if body.get("mode") is not None:
        policy.mode = body["mode"]
    if body.get("max_data_classification") is not None:
        policy.max_data_classification = body["max_data_classification"]
    if body.get("allowed_provider_ids") is not None:
        provider_ids = _provider_ids(body["allowed_provider_ids"])
        existing_ids = set(
            session.scalars(select(ModelProvider.id)).all()
        )
        if not set(provider_ids).issubset(existing_ids):
            raise ApiError(400, "INVALID_ARGUMENT", "Provider does not exist.")
        policy.allowed_provider_ids = json.dumps(provider_ids)
    policy.allow_chat_history = bool(
        body.get("allow_chat_history", policy.allow_chat_history)
    )
    policy.allow_document_metadata = bool(
        body.get("allow_document_metadata", policy.allow_document_metadata)
    )
    policy.require_redaction = True
    policy.version += 1

    for team_policy in session.scalars(select(ModelPolicyRecord)).all():
        if _MODE_RANK[team_policy.mode] > _MODE_RANK[policy.mode]:
            team_policy.mode = policy.mode
        if (
            _CLASSIFICATION_RANK[team_policy.max_data_classification]
            > _CLASSIFICATION_RANK[policy.max_data_classification]
        ):
            team_policy.max_data_classification = policy.max_data_classification
        allowed = set(json.loads(policy.allowed_provider_ids or "[]"))
        team_policy.allowed_provider_ids = json.dumps(
            [
                provider_id
                for provider_id in json.loads(team_policy.allowed_provider_ids or "[]")
                if provider_id in allowed
            ]
        )
    write_audit(
        session,
        team_id=None,
        actor_id=admin.id,
        action="model_policy.deployment.update",
        resource_type="deployment_model_policy",
        resource_id=policy.id,
        details={
            "scope": "deployment",
            "mode": policy.mode,
            "allowed_provider_ids": json.loads(policy.allowed_provider_ids or "[]"),
            "max_data_classification": policy.max_data_classification,
            "allow_chat_history": policy.allow_chat_history,
            "allow_document_metadata": policy.allow_document_metadata,
            "require_redaction": policy.require_redaction,
            "version": policy.version,
        },
    )
    session.commit()
    return envelope(_deployment_view(policy), request.state.request_id)


@router.get("/admin/providers")
def admin_list_providers(
    request: Request,
    limit: int = 20,
    cursor: Optional[str] = None,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    return paginate_scalars(
        session,
        select(ModelProvider),
        timestamp_column=ModelProvider.created_at,
        id_column=ModelProvider.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=_provider_view,
    )


@router.post("/admin/providers/create", status_code=201)
def admin_create_provider(
    body: AdminProviderCreateRequest,
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    provider = ModelProvider(
        team_id=None,
        name=body.name,
        provider_type=body.provider_type,
        base_url=body.base_url,
        model_ids=json.dumps(body.model_ids),
        created_by=admin.id,
    )
    _set_provider_api_key(provider, body.api_key, request.app.state.settings)
    session.add(provider)
    session.flush()
    write_audit(
        session,
        team_id=None,
        actor_id=admin.id,
        action="provider.admin.create",
        resource_type="model_provider",
        resource_id=provider.id,
        details={
            "scope": "deployment",
            "name": provider.name,
            "provider_type": provider.provider_type,
            "model_ids": json.loads(provider.model_ids or "[]"),
        },
    )
    session.commit()
    return envelope(_provider_view(provider), request.state.request_id)


@router.post("/admin/providers/models")
def discover_admin_provider_models(
    body: AdminProviderModelsRequest,
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    models = _discover_provider_models(
        provider_type=body.provider_type,
        base_url=body.base_url,
        api_key=body.api_key,
    )
    return envelope(
        {"provider_type": body.provider_type, "models": models},
        request.state.request_id,
    )


@router.post("/admin/providers/update")
def admin_update_provider(
    body: AdminProviderUpdateRequest,
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    provider = session.get(ModelProvider, body.provider_id)
    if provider is None:
        raise ApiError(404, "NOT_FOUND", "Provider was not found.")
    if body.status is not None:
        provider.status = body.status
    if body.provider_type is not None:
        provider.provider_type = body.provider_type
    if body.base_url is not None:
        provider.base_url = body.base_url
    if body.api_key is not None:
        _set_provider_api_key(provider, body.api_key, request.app.state.settings)
    if body.model_ids is not None:
        provider.model_ids = json.dumps(body.model_ids)
    write_audit(
        session,
        team_id=None,
        actor_id=admin.id,
        action="provider.admin.update",
        resource_type="model_provider",
        resource_id=provider.id,
        details={
            "scope": "deployment",
            "status": provider.status,
            "provider_type": provider.provider_type,
            "api_key_masked": provider.api_key_masked,
            "model_ids": json.loads(provider.model_ids or "[]"),
        },
    )
    session.commit()
    return envelope(_provider_view(provider), request.state.request_id)


@router.get("/admin/models")
def admin_models(
    request: Request,
    limit: int = 20,
    cursor: Optional[str] = None,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    providers = session.scalars(
        select(ModelProvider).order_by(
            ModelProvider.created_at.desc(), ModelProvider.id.desc()
        )
    ).all()
    models = [
        {"provider_id": provider.id, "model_id": model_id, "status": provider.status}
        for provider in providers
        for model_id in json.loads(provider.model_ids or "[]")
    ]
    return paginate_items(
        models,
        limit=limit,
        request_id=request.state.request_id,
        cursor=cursor,
        view=lambda item: item,
    )


@router.post("/admin/models/update")
def admin_update_model(
    body: dict,
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    provider = session.get(ModelProvider, body.get("provider_id", ""))
    if provider is None:
        raise ApiError(404, "NOT_FOUND", "Provider was not found.")
    if body.get("model_ids") is not None:
        provider.model_ids = json.dumps(body["model_ids"])
        write_audit(
            session,
            team_id=None,
            actor_id=admin.id,
            action="model.admin.update",
            resource_type="model",
            resource_id=provider.id,
            details={
                "scope": "deployment",
                "provider_id": provider.id,
                "model_ids": json.loads(provider.model_ids or "[]"),
                "status": provider.status,
            },
        )
        session.commit()
    return envelope({"provider_id": provider.id, "model_ids": json.loads(provider.model_ids or "[]")}, request.state.request_id)
