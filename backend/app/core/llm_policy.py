from typing import Optional, Tuple

from backend.app.rag.domain.models import DataClassification, ModelPolicyDecision


_LOCAL_ONLY = "local_only"
_EXTERNAL_ALLOWED = "external_allowed"
_EXTERNAL_REQUIRED = "external_required"
_VALID_MODES = (_LOCAL_ONLY, _EXTERNAL_ALLOWED, _EXTERNAL_REQUIRED)
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.PRIVATE: 2,
    DataClassification.RESTRICTED: 3,
}


def _normalize_mode(mode: Optional[str]) -> Optional[str]:
    if mode is None:
        return None
    if not isinstance(mode, str):
        return "__invalid__"
    normalized = mode.strip().lower()
    if normalized == "inherit":
        return None
    if normalized not in _VALID_MODES:
        return "__invalid__"
    return normalized


def _normalize_classification(
    classification: DataClassification,
) -> DataClassification:
    try:
        return DataClassification(classification)
    except (TypeError, ValueError):
        return DataClassification.RESTRICTED


def normalize_classification(value: object) -> DataClassification:
    normalized = str(value or "").strip().lower()
    if normalized == "confidential":
        normalized = DataClassification.RESTRICTED.value
    try:
        return DataClassification(normalized)
    except ValueError:
        return DataClassification.RESTRICTED


def resolve_model_policy(
    deployment_mode: str = _LOCAL_ONLY,
    *,
    team_mode: Optional[str] = None,
    knowledge_base_mode: Optional[str] = None,
    request_mode: Optional[str] = None,
    requested_classification: DataClassification = DataClassification.RESTRICTED,
    allowed_provider_ids: Tuple[str, ...] = (),
    allowed_model_ids: Tuple[str, ...] = (),
    allow_chat_history: bool = False,
    allow_document_metadata: bool = False,
    require_redaction: bool = True,
    max_data_classification: Optional[DataClassification] = None,
    policy_available: bool = True,
    policy_version: str = "p0",
) -> ModelPolicyDecision:
    """Resolve layered policy to the least permissive effective decision."""
    classification = _normalize_classification(requested_classification)

    if not policy_available:
        return _deny_decision(
            reason_code="policy_unavailable",
            fallback_mode="local_model",
            policy_version=policy_version,
        )

    deployment = _normalize_mode(deployment_mode)
    if deployment is None:
        return _deny_decision(
            reason_code="invalid_policy",
            fallback_mode="local_model",
            policy_version=policy_version,
        )

    modes = tuple(
        _normalize_mode(mode)
        for mode in (
            deployment,
            team_mode,
            knowledge_base_mode,
            request_mode,
        )
    )
    if "__invalid__" in modes:
        return _deny_decision(
            reason_code="invalid_policy",
            fallback_mode="local_model",
            policy_version=policy_version,
        )

    effective_modes = tuple(mode for mode in modes if mode is not None)
    if _LOCAL_ONLY in effective_modes:
        return _deny_decision(
            reason_code="local_only",
            fallback_mode="local_model",
            policy_version=policy_version,
        )

    if classification is DataClassification.RESTRICTED:
        fallback_mode = (
            "reject" if _EXTERNAL_REQUIRED in effective_modes else "local_model"
        )
        return _deny_decision(
            reason_code="restricted_classification",
            fallback_mode=fallback_mode,
            policy_version=policy_version,
        )

    if classification is DataClassification.PRIVATE:
        fallback_mode = (
            "reject" if _EXTERNAL_REQUIRED in effective_modes else "local_model"
        )
        return _deny_decision(
            reason_code="private_classification_local_only",
            fallback_mode=fallback_mode,
            policy_version=policy_version,
        )

    maximum = _normalize_classification(
        max_data_classification or DataClassification.INTERNAL
    )
    if (
        _CLASSIFICATION_RANK[classification]
        > _CLASSIFICATION_RANK[maximum]
    ):
        fallback_mode = (
            "reject" if _EXTERNAL_REQUIRED in effective_modes else "local_model"
        )
        return _deny_decision(
            reason_code="classification_above_policy",
            fallback_mode=fallback_mode,
            policy_version=policy_version,
        )

    requires_external = _EXTERNAL_REQUIRED in effective_modes
    if not effective_modes or all(mode == _LOCAL_ONLY for mode in effective_modes):
        return _deny_decision(
            reason_code="local_only",
            fallback_mode="local_model",
            policy_version=policy_version,
        )

    return ModelPolicyDecision(
        allow_external=True,
        allowed_provider_ids=tuple(allowed_provider_ids),
        max_data_classification=maximum,
        allowed_model_ids=tuple(allowed_model_ids),
        allow_chat_history=bool(allow_chat_history),
        allow_document_metadata=bool(allow_document_metadata),
        require_redaction=True,
        fallback_mode="reject" if requires_external else "local_model",
        reason_code=(
            "external_required" if requires_external else "external_allowed"
        ),
        policy_version=str(policy_version),
    )


def assert_external_call_allowed(
    decision: ModelPolicyDecision,
    classification: DataClassification,
) -> None:
    """Raise PermissionError unless this exact data classification may egress."""
    normalized_classification = _normalize_classification(classification)

    if normalized_classification is DataClassification.RESTRICTED:
        raise PermissionError("external calls are forbidden for restricted data")
    if not decision.allow_external:
        raise PermissionError("external model policy is disabled")

    maximum = _normalize_classification(decision.max_data_classification)
    if _CLASSIFICATION_RANK[normalized_classification] > _CLASSIFICATION_RANK[maximum]:
        raise PermissionError("data classification exceeds external policy")


def _deny_decision(
    *,
    reason_code: str,
    fallback_mode: str,
    policy_version: str,
) -> ModelPolicyDecision:
    return ModelPolicyDecision(
        allow_external=False,
        allowed_provider_ids=(),
        max_data_classification=DataClassification.PUBLIC,
        allowed_model_ids=(),
        allow_chat_history=False,
        allow_document_metadata=False,
        require_redaction=True,
        fallback_mode=fallback_mode,
        reason_code=reason_code,
        policy_version=str(policy_version),
    )
