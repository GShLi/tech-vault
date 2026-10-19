import pytest

from backend.app.rag.domain.models import DataClassification


def test_default_policy_blocks_external_calls():
    from backend.app.core.llm_policy import (
        assert_external_call_allowed,
        resolve_model_policy,
    )

    decision = resolve_model_policy(
        deployment_mode="local_only",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is False
    with pytest.raises(PermissionError):
        assert_external_call_allowed(decision, DataClassification.PUBLIC)


def test_external_allowed_policy_allows_public_data():
    from backend.app.core.llm_policy import (
        assert_external_call_allowed,
        resolve_model_policy,
    )

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        requested_classification=DataClassification.PUBLIC,
        allowed_provider_ids=("provider-a",),
        allowed_model_ids=("model-a",),
    )

    assert decision.allow_external is True
    assert decision.allowed_provider_ids == ("provider-a",)
    assert decision.allowed_model_ids == ("model-a",)
    assert_external_call_allowed(decision, DataClassification.PUBLIC)


@pytest.mark.parametrize(
    "policy_argument",
    ["team_mode", "knowledge_base_mode", "request_mode"],
)
def test_any_local_only_level_is_strictest(policy_argument):
    from backend.app.core.llm_policy import resolve_model_policy

    arguments = {
        "deployment_mode": "external_allowed",
        "requested_classification": DataClassification.PUBLIC,
        policy_argument: "local_only",
    }
    decision = resolve_model_policy(**arguments)

    assert decision.allow_external is False


def test_request_cannot_relax_team_policy():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        team_mode="local_only",
        request_mode="external_required",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is False


def test_inherit_request_mode_uses_the_remaining_policy_layers():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        request_mode="inherit",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is True


def test_missing_deployment_policy_fails_closed():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode=None,
        team_mode="external_allowed",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is False


@pytest.mark.parametrize("mode", ["external_allowed", "external_required"])
def test_restricted_data_is_never_sent_externally(mode):
    from backend.app.core.llm_policy import (
        assert_external_call_allowed,
        resolve_model_policy,
    )

    decision = resolve_model_policy(
        deployment_mode=mode,
        requested_classification=DataClassification.RESTRICTED,
    )

    assert decision.allow_external is False
    with pytest.raises(PermissionError):
        assert_external_call_allowed(decision, DataClassification.RESTRICTED)


def test_private_data_requires_local_model_even_when_external_is_allowed():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        requested_classification=DataClassification.PRIVATE,
    )

    assert decision.allow_external is False
    assert decision.fallback_mode == "local_model"


def test_policy_service_failure_fails_closed():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_required",
        requested_classification=DataClassification.PUBLIC,
        policy_available=False,
    )

    assert decision.allow_external is False
    assert decision.reason_code == "policy_unavailable"


def test_unknown_policy_mode_fails_closed():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="unexpected_mode",
        requested_classification=DataClassification.PUBLIC,
    )

    assert decision.allow_external is False


def test_external_call_rechecks_data_classification():
    from backend.app.core.llm_policy import (
        assert_external_call_allowed,
        resolve_model_policy,
    )

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        requested_classification=DataClassification.PUBLIC,
    )

    with pytest.raises(PermissionError):
        assert_external_call_allowed(decision, DataClassification.RESTRICTED)


def test_policy_uses_chat_naming_only():
    from backend.app.core.llm_policy import resolve_model_policy

    decision = resolve_model_policy(
        deployment_mode="external_allowed",
        requested_classification=DataClassification.PUBLIC,
        allow_chat_history=True,
    )

    assert decision.allow_chat_history is True
    assert not hasattr(decision, "allow_conversation_history")
