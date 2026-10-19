import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session, require_super_admin
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import ModelCall, ModelPolicyRecord, ModelProvider, User


router = APIRouter(tags=["policies"])


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
    return envelope(
        _policy_view(policy) if policy else _default_policy(),
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
    mode = body.get("mode", "local_only")
    if mode not in {"local_only", "external_allowed", "external_required"}:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid model policy mode.")
    policy = session.scalar(
        select(ModelPolicyRecord).where(ModelPolicyRecord.team_id == team_id)
    )
    if policy is None:
        policy = ModelPolicyRecord(team_id=team_id)
        session.add(policy)
    policy.mode = mode
    if body.get("allowed_provider_ids") is not None:
        policy.allowed_provider_ids = json.dumps(body["allowed_provider_ids"])
    if body.get("max_data_classification"):
        policy.max_data_classification = body["max_data_classification"]
    policy.allow_chat_history = bool(body.get("allow_chat_history", policy.allow_chat_history))
    policy.allow_document_metadata = bool(
        body.get("allow_document_metadata", policy.allow_document_metadata)
    )
    policy.version += 1
    session.commit()
    return envelope(_policy_view(policy), request.state.request_id)


@router.get("/providers")
def list_providers(
    request: Request,
    team_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    rows = session.scalars(
        select(ModelProvider).where(
            (ModelProvider.team_id == team_id) | (ModelProvider.team_id.is_(None))
        )
    ).all()
    return page_envelope(
        [
            {
                "id": row.id,
                "name": row.name,
                "provider_type": row.provider_type,
                "base_url": row.base_url,
                "model_ids": json.loads(row.model_ids or "[]"),
                "status": row.status,
            }
            for row in rows
        ],
        request.state.request_id,
    )


@router.post("/providers/create", status_code=201)
def create_provider(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    provider = ModelProvider(
        team_id=team_id,
        name=body.get("name", "provider"),
        provider_type=body.get("provider_type", "openai_compatible"),
        base_url=body.get("base_url", ""),
        model_ids=json.dumps(body.get("model_ids", [])),
        created_by=user.id,
    )
    session.add(provider)
    session.commit()
    return envelope({"id": provider.id, "name": provider.name}, request.state.request_id)


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
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    rows = session.scalars(
        select(ModelCall)
        .where(ModelCall.team_id == team_id)
        .order_by(ModelCall.created_at.desc())
        .limit(200)
    ).all()
    return page_envelope(
        [
            {
                "id": row.id,
                "provider_id": row.provider_id,
                "model_id": row.model_id,
                "purpose": row.purpose,
                "classification": row.classification,
                "external": row.external,
                "cost_micros": row.cost_micros,
                "latency_ms": row.latency_ms,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        request.state.request_id,
    )


@router.get("/admin/model-policy")
def admin_policy(
    request: Request,
    admin: User = Depends(require_super_admin),
):
    return envelope(_default_policy(), request.state.request_id)


@router.post("/admin/model-policy/update")
def admin_update_policy(
    body: dict,
    request: Request,
    admin: User = Depends(require_super_admin),
):
    policy = _default_policy()
    policy["mode"] = body.get("mode", "local_only")
    return envelope(policy, request.state.request_id)


@router.get("/admin/providers")
def admin_list_providers(
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    rows = session.scalars(select(ModelProvider).order_by(ModelProvider.created_at.desc())).all()
    return page_envelope(
        [{"id": row.id, "name": row.name, "provider_type": row.provider_type, "status": row.status} for row in rows],
        request.state.request_id,
    )


@router.post("/admin/providers/create", status_code=201)
def admin_create_provider(
    body: dict,
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    provider = ModelProvider(
        team_id=None,
        name=body.get("name", "provider"),
        provider_type=body.get("provider_type", "openai_compatible"),
        base_url=body.get("base_url", ""),
        model_ids=json.dumps(body.get("model_ids", [])),
        created_by=admin.id,
    )
    session.add(provider)
    session.commit()
    return envelope({"id": provider.id, "name": provider.name}, request.state.request_id)


@router.post("/admin/providers/update")
def admin_update_provider(
    body: dict,
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    provider = session.get(ModelProvider, body.get("provider_id", ""))
    if provider is None:
        raise ApiError(404, "NOT_FOUND", "Provider was not found.")
    if body.get("status") is not None:
        provider.status = body["status"]
    if body.get("model_ids") is not None:
        provider.model_ids = json.dumps(body["model_ids"])
    session.commit()
    return envelope({"id": provider.id, "status": provider.status}, request.state.request_id)


@router.get("/admin/models")
def admin_models(
    request: Request,
    admin: User = Depends(require_super_admin),
    session: Session = Depends(get_session),
):
    providers = session.scalars(select(ModelProvider)).all()
    return page_envelope(
        [
            {"provider_id": provider.id, "model_id": model_id, "status": provider.status}
            for provider in providers
            for model_id in json.loads(provider.model_ids or "[]")
        ],
        request.state.request_id,
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
        session.commit()
    return envelope({"provider_id": provider.id, "model_ids": json.loads(provider.model_ids or "[]")}, request.state.request_id)
