import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError
from backend.app.core.config import Settings
from backend.app.core.llm_policy import assert_external_call_allowed
from backend.app.db.models import ModelProvider
from backend.app.rag.domain.models import DataClassification, ModelPolicyDecision


@dataclass(frozen=True)
class ResolvedProvider:
    provider_id: str
    provider_type: str
    base_url: str
    model_id: str
    encrypted_api_key: str


def _invalid(message: str) -> ApiError:
    return ApiError(400, "INVALID_ARGUMENT", message)


def resolve_provider(
    session: Session,
    team_id: str,
    provider_id: str,
    model_id: str,
    decision: ModelPolicyDecision,
    settings: Settings,
) -> ResolvedProvider:
    normalized_provider_id = provider_id.strip()
    normalized_model_id = model_id.strip()
    if not normalized_provider_id or not normalized_model_id:
        raise _invalid("Provider and model are required.")

    provider = session.get(ModelProvider, normalized_provider_id)
    if provider is None:
        raise _invalid("Provider was not found.")
    if provider.team_id not in {None, team_id}:
        raise _invalid("Provider is not available to this team.")
    if provider.status != "active":
        raise _invalid("Provider is not active.")

    try:
        model_ids = json.loads(provider.model_ids or "[]")
    except (TypeError, json.JSONDecodeError) as error:
        raise _invalid("Provider model configuration is invalid.") from error
    if not isinstance(model_ids, list) or normalized_model_id not in model_ids:
        raise _invalid("Model is not configured on the selected provider.")
    if not provider.api_key_encrypted.strip():
        raise ApiError(
            503,
            "MODEL_UNAVAILABLE",
            "Provider credentials are unavailable.",
        )

    if (
        decision.allowed_provider_ids
        and provider.id not in decision.allowed_provider_ids
    ):
        raise ApiError(
            403,
            "POLICY_DENIED",
            "Provider is not approved by policy.",
        )
    if (
        decision.allowed_model_ids
        and normalized_model_id not in decision.allowed_model_ids
    ):
        raise ApiError(
            403,
            "POLICY_DENIED",
            "Model is not approved by policy.",
        )
    try:
        assert_external_call_allowed(decision, DataClassification.INTERNAL)
    except PermissionError as error:
        raise ApiError(
            403,
            "POLICY_DENIED",
            "External answer generation is forbidden by policy.",
        ) from error

    return ResolvedProvider(
        provider_id=provider.id,
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        model_id=normalized_model_id,
        encrypted_api_key=provider.api_key_encrypted,
    )
