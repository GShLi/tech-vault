import asyncio
import json
from typing import Mapping, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import paginate_scalars
from backend.app.core.config import Settings
from backend.app.core.secrets import decrypt_secret
from backend.app.api.v1.chats import (
    _classification_for_chunks,
    _persist_model_calls,
    _policy_decision,
)
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.api.v1.documents import _granted_document_ids
from backend.app.db.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    IndexGenerationRecord,
    User,
)
from backend.app.modules.audit.service import write_audit
from backend.app.modules.providers.resolution import resolve_provider
from backend.app.rag.domain.models import DataClassification, RetrievalFilters, SearchRequest
from backend.app.rag.embedding.service import EmbeddingClient
from backend.app.rag.evaluation.runner import (
    EvaluationInput,
    EvaluationObservation,
    evaluate_ranked_cases,
    evaluate_release_gate,
)
from backend.app.rag.llm_gateway import GatewayAudit, LlmGateway
from backend.app.rag.llm_gateway.providers import (
    ProviderAdapterError,
    build_provider_adapter,
)
from backend.app.rag.rerank.service import RerankerClient
from backend.app.rag.retrieval.config import EngineMode
from backend.app.rag.retrieval.factory import build_retriever
from backend.app.workers.dispatch import TaskDispatchError, dispatch_evaluation_run

router = APIRouter(tags=["evals"])

_EVALUATION_TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
_EVALUATION_TERMINAL_EVENTS = {
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}
_EVALUATION_STAGES = {
    "queued": "queued",
    "running": "evaluating",
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}


def _evaluation_policy_decision(session, dataset, cases, user_id):
    knowledge_base_ids = sorted(
        {
            knowledge_base_id
            for case in cases
            for knowledge_base_id in json.loads(
                case.filters or "{}"
            ).get("knowledge_base_ids", [])
        }
    )
    return _policy_decision(
        session,
        dataset.team_id,
        knowledge_base_ids,
        user_id,
        "inherit",
        DataClassification.INTERNAL,
    )


class EvaluationRunStartRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    dataset_id: str = Field(min_length=1, max_length=26)
    provider_id: str = Field(min_length=1, max_length=26)
    model_id: str = Field(min_length=1, max_length=120)
    engine_mode: str = "dual_engine"
    judge_mode: str = "rules_and_manual"
    baseline_run_id: Optional[str] = Field(default=None, max_length=26)

    @field_validator(
        "team_id",
        "dataset_id",
        "provider_id",
        "model_id",
        "baseline_run_id",
        mode="before",
    )
    @classmethod
    def normalize_identifiers(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("engine_mode")
    @classmethod
    def validate_engine_mode(cls, value: str) -> str:
        if value not in {mode.value for mode in EngineMode}:
            raise ValueError("invalid engine mode")
        return value

    @field_validator("judge_mode")
    @classmethod
    def validate_judge_mode(cls, value: str) -> str:
        if value not in {"rules", "rules_and_manual"}:
            raise ValueError("invalid judge mode")
        return value


def _build_evaluation_answer_provider(settings, resolved_provider):
    try:
        api_key = decrypt_secret(
            resolved_provider.encrypted_api_key,
            settings,
        )
    except Exception:
        raise ApiError(
            409,
            "RESOURCE_STATE_CONFLICT",
            "Provider credentials are unavailable.",
        ) from None
    if not api_key.strip():
        raise ApiError(
            409,
            "RESOURCE_STATE_CONFLICT",
            "Provider credentials are unavailable.",
        )
    try:
        answer_provider = build_provider_adapter(
            provider_type=resolved_provider.provider_type,
            provider_id=resolved_provider.provider_id,
            base_url=resolved_provider.base_url,
            api_key=api_key,
            model_id=resolved_provider.model_id,
        )
    except ProviderAdapterError as error:
        raise ApiError(error.status_code, error.code, str(error)) from error
    return answer_provider, api_key


@router.get("/evals/datasets")
def list_datasets(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    query = select(EvaluationDataset).where(
        EvaluationDataset.team_id == team_id,
        EvaluationDataset.status == "active",
    )
    return paginate_scalars(
        session,
        query,
        timestamp_column=EvaluationDataset.created_at,
        id_column=EvaluationDataset.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda row: {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "case_count": row.case_count,
            "version": row.version,
            "created_at": row.created_at.isoformat(),
        },
    )


@router.post("/evals/datasets/create", status_code=201)
def create_dataset(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    ds = EvaluationDataset(team_id=team_id, name=body.get("name", "").strip(), description=body.get("description"), created_by=user.id)
    session.add(ds)
    session.flush()
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="evaluation.dataset.create",
        resource_type="evaluation_dataset",
        resource_id=ds.id,
        details={"name": ds.name, "status": ds.status, "version": ds.version},
    )
    session.commit()
    return envelope({ "id": ds.id, "name": ds.name, "case_count": 0, "version": 1, "created_at": ds.created_at.isoformat() }, request.state.request_id)


@router.get("/evals/runs")
def list_runs(
    request: Request,
    team_id: str,
    dataset_id: str = "",
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    query = select(EvaluationRun).join(EvaluationDataset).where(EvaluationDataset.team_id == team_id)
    if dataset_id:
        query = query.where(EvaluationRun.dataset_id == dataset_id)
    return paginate_scalars(
        session,
        query,
        timestamp_column=EvaluationRun.created_at,
        id_column=EvaluationRun.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda row: {
            "id": row.id,
            "dataset_id": row.dataset_id,
            "engine_mode": row.engine_mode,
            "status": row.status,
            "baseline_run_id": row.baseline_run_id,
            "provider_id": row.provider_id,
            "model_id": row.model_id,
            "created_at": row.created_at.isoformat(),
        },
    )


@router.post("/evals/runs/start", status_code=202)
def start_run(
    body: EvaluationRunStartRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.team_id
    _leader_or_error(session, team_id, user.id)
    dataset = _dataset_or_error(session, team_id, body.dataset_id)
    engine_mode = body.engine_mode
    judge_mode = body.judge_mode
    cases = session.scalars(
        select(EvaluationCase)
        .where(EvaluationCase.dataset_id == dataset.id)
        .order_by(EvaluationCase.created_at.asc())
    ).all()
    if not cases:
        raise ApiError(409, "EMPTY_DATASET", "The evaluation dataset has no cases.")
    policy = _evaluation_policy_decision(session, dataset, cases, user.id)
    resolved_provider = resolve_provider(
        session,
        team_id,
        body.provider_id,
        body.model_id,
        policy,
    )
    _build_evaluation_answer_provider(
        request.app.state.settings,
        resolved_provider,
    )

    baseline_metrics = {}
    if body.baseline_run_id:
        baseline = _run_or_error(session, team_id, body.baseline_run_id)
        if baseline.dataset_id != dataset.id:
            raise ApiError(
                400,
                "INVALID_ARGUMENT",
                "Baseline run must use the same dataset.",
            )
        baseline_result = session.scalar(
            select(EvaluationResult).where(EvaluationResult.run_id == baseline.id)
        )
        if baseline_result is not None:
            baseline_metrics = json.loads(baseline_result.metrics or "{}")
    run = EvaluationRun(
        dataset_id=dataset.id,
        engine_mode=engine_mode,
        baseline_run_id=body.baseline_run_id,
        provider_id=resolved_provider.provider_id,
        model_id=resolved_provider.model_id,
        created_by=user.id,
        status="queued",
    )
    session.add(run)
    session.flush()
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="evaluation.run.start",
        resource_type="evaluation_run",
        resource_id=run.id,
        details={
            "dataset_id": dataset.id,
            "engine_mode": engine_mode,
            "judge_mode": judge_mode,
            "baseline_run_id": run.baseline_run_id,
            "provider_id": run.provider_id,
            "model_id": run.model_id,
            "status": run.status,
        },
    )
    session.commit()
    try:
        dispatch_evaluation_run(
            session,
            run.id,
            request.app.state.settings,
            judge_mode,
            baseline_metrics,
        )
    except TaskDispatchError as error:
        session.refresh(run)
        if run.status not in _EVALUATION_TERMINAL_STATUSES:
            run.status = "failed"
            session.add(
                EvaluationResult(
                    run_id=run.id,
                    metrics="{}",
                    report=json.dumps(
                        {
                            "error": "The evaluation task queue is unavailable.",
                            "error_code": "TASK_QUEUE_UNAVAILABLE",
                            "engine_mode": engine_mode,
                            "judge_mode": judge_mode,
                            "provider_id": run.provider_id,
                            "model_id": run.model_id,
                        },
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                )
            )
            session.commit()
        raise ApiError(
            503,
            "TASK_QUEUE_UNAVAILABLE",
            "The evaluation task queue is unavailable.",
            {"run_id": run.id},
        ) from error
    session.refresh(run)
    return envelope(
        {
            "id": run.id,
            "status": run.status,
            "provider_id": run.provider_id,
            "model_id": run.model_id,
        },
        request.state.request_id,
    )


@router.get("/evals/runs/detail")
def get_run(request: Request, team_id: str, run_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    run = _run_or_error(session, team_id, run_id)
    return envelope({ "id": run.id, "dataset_id": run.dataset_id, "engine_mode": run.engine_mode, "status": run.status, "baseline_run_id": run.baseline_run_id, "provider_id": run.provider_id, "model_id": run.model_id, "created_at": run.created_at.isoformat() }, request.state.request_id)


def _dataset_or_error(session: Session, team_id: str, dataset_id: str) -> EvaluationDataset:
    dataset = session.get(EvaluationDataset, dataset_id)
    if dataset is None or dataset.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Dataset was not found.")
    return dataset


def _run_or_error(session: Session, team_id: str, run_id: str) -> EvaluationRun:
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise ApiError(404, "NOT_FOUND", "Run was not found.")
    _dataset_or_error(session, team_id, run.dataset_id)
    return run


def execute_evaluation_run_record(
    session: Session,
    run_id: str,
    settings: Settings,
    judge_mode: str,
    baseline_metrics: Mapping[str, float],
) -> dict:
    """Execute and persist an evaluation run without an API request context."""
    run = session.get(EvaluationRun, run_id)
    if run is None:
        return {"id": run_id, "status": "not_found"}
    if run.status in _EVALUATION_TERMINAL_STATUSES:
        return {"id": run.id, "status": run.status}

    if run.status == "queued":
        transitioned = session.execute(
            update(EvaluationRun)
            .where(EvaluationRun.id == run_id, EvaluationRun.status == "queued")
            .values(status="running")
            .execution_options(synchronize_session=False)
        ).rowcount
        session.commit()
        if not transitioned:
            session.expire_all()
            current = session.get(EvaluationRun, run_id)
            return {
                "id": run_id,
                "status": current.status if current is not None else "not_found",
            }

    session.expire_all()
    run = session.get(EvaluationRun, run_id)
    if run is None:
        return {"id": run_id, "status": "not_found"}
    if run.status in _EVALUATION_TERMINAL_STATUSES:
        return {"id": run.id, "status": run.status}
    if run.status != "running":
        raise RuntimeError("evaluation run is not executable in its current state")

    dataset = session.get(EvaluationDataset, run.dataset_id)
    if dataset is None:
        return _persist_evaluation_failure(
            session,
            run_id,
            judge_mode,
            "evaluation dataset is not available",
        )
    cases = session.scalars(
        select(EvaluationCase)
        .where(EvaluationCase.dataset_id == dataset.id)
        .order_by(EvaluationCase.created_at.asc())
    ).all()
    user = session.get(User, run.created_by)
    if user is None:
        return _persist_evaluation_failure(
            session,
            run_id,
            judge_mode,
            "evaluation owner is not available",
        )

    try:
        result = _collect_evaluation_result(
            session,
            run,
            dataset,
            cases,
            user,
            settings,
        )
        report = result["report"]
        report["judge_mode"] = judge_mode
        report["release_gate"] = evaluate_release_gate(
            result["metrics"], baseline_metrics
        )
        transitioned = session.execute(
            update(EvaluationRun)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.status == "running",
            )
            .values(status="succeeded")
            .execution_options(synchronize_session=False)
        ).rowcount
        if not transitioned:
            session.rollback()
            current = session.get(EvaluationRun, run_id)
            return {
                "id": run_id,
                "status": current.status if current is not None else "not_found",
            }
        session.add(
            EvaluationResult(
                run_id=run_id,
                metrics=json.dumps(
                    result["metrics"], separators=(",", ":")
                ),
                report=json.dumps(
                    report, separators=(",", ":"), ensure_ascii=False
                ),
            )
        )
        session.commit()
        return {"id": run_id, "status": "succeeded"}
    except Exception as error:  # noqa: BLE001
        session.rollback()
        return _persist_evaluation_failure(
            session,
            run_id,
            judge_mode,
            str(error) or error.__class__.__name__,
            getattr(error, "code", None),
        )


def _persist_evaluation_failure(
    session: Session,
    run_id: str,
    judge_mode: str,
    error_message: str,
    error_code: Optional[str] = None,
) -> dict:
    run = session.get(EvaluationRun, run_id)
    if run is None:
        return {"id": run_id, "status": "not_found"}
    if run.status == "cancelled":
        return {"id": run_id, "status": "cancelled"}
    if run.status in _EVALUATION_TERMINAL_STATUSES:
        return {"id": run_id, "status": run.status}

    transitioned = session.execute(
        update(EvaluationRun)
        .where(
            EvaluationRun.id == run_id,
            EvaluationRun.status.in_(("queued", "running")),
        )
        .values(status="failed")
        .execution_options(synchronize_session=False)
    ).rowcount
    if not transitioned:
        session.rollback()
        current = session.get(EvaluationRun, run_id)
        return {
            "id": run_id,
            "status": current.status if current is not None else "not_found",
        }
    report = {
        "error": error_message,
        "engine_mode": run.engine_mode,
        "judge_mode": judge_mode,
        "provider_id": run.provider_id,
        "model_id": run.model_id,
    }
    if error_code:
        report["error_code"] = error_code
    session.add(
        EvaluationResult(
            run_id=run_id,
            metrics="{}",
            report=json.dumps(
                report,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )
    )
    session.commit()
    return {"id": run_id, "status": "failed"}


def _build_evaluation_gateway(settings, policy, resolved_provider):
    answer_provider, api_key = _build_evaluation_answer_provider(
        settings,
        resolved_provider,
    )
    audits: list[GatewayAudit] = []
    return (
        LlmGateway(
            decision=policy,
            external_answer_provider=answer_provider,
            external_api_key=api_key,
            local_embed_provider=EmbeddingClient(settings.embedding_url),
            local_rerank_provider=RerankerClient(settings.rerank_url),
            audit_sink=audits.append,
        ),
        audits,
    )


def _collect_evaluation_result(session, run, dataset, cases, user, settings):
    generation = session.scalar(
        select(IndexGenerationRecord)
        .where(
            IndexGenerationRecord.team_id == dataset.team_id,
            IndexGenerationRecord.status == "active",
        )
        .order_by(IndexGenerationRecord.activated_at.desc())
    )
    if generation is None:
        raise RuntimeError("active index generation is not available")

    case_filters = [json.loads(case.filters or "{}") for case in cases]
    policy = _evaluation_policy_decision(session, dataset, cases, user.id)
    resolved_provider = resolve_provider(
        session,
        dataset.team_id,
        run.provider_id,
        run.model_id,
        policy,
    )
    gateway, gateway_audits = _build_evaluation_gateway(
        settings,
        policy,
        resolved_provider,
    )
    retriever = build_retriever(
        settings,
        generation.id,
        EngineMode(run.engine_mode),
    )

    async def retrieve_all():
        observations = {}
        for case, filters in zip(cases, case_filters):
            rewrite = gateway.rewrite(
                question=case.query,
                product=filters.get("product"),
                version_values=tuple(filters.get("version_values", [])),
                classification=DataClassification.INTERNAL,
            )
            vectors = gateway.embed(
                [rewrite.rewritten_query],
                classification=DataClassification.INTERNAL,
            )
            if not vectors:
                raise RuntimeError("embedding provider returned no vectors")
            result = await retriever.search(
                SearchRequest(
                    query=case.query,
                    rewritten_query=rewrite.rewritten_query,
                    query_vector=vectors[0],
                    filters=RetrievalFilters(
                        team_id=dataset.team_id,
                        knowledge_base_ids=tuple(filters.get("knowledge_base_ids", [])),
                        viewer_user_id=user.id,
                        product=filters.get("product"),
                        version_values=tuple(filters.get("version_values", [])),
                        explicit_document_grants=_granted_document_ids(
                            session, dataset.team_id, user.id
                        ),
                    ),
                    final_top_n=20,
                )
            )
            rerank_input = list(result.rrf_candidates or result.chunks)
            classification = _classification_for_chunks(session, rerank_input)
            reranked = gateway.rerank(
                rewrite.rewritten_query,
                rerank_input,
                top_n=10,
                classification=classification,
            )
            context_chunks = reranked[:8]
            answer = gateway.generate(
                question=rewrite.rewritten_query,
                chunks=context_chunks,
                classification=classification,
                max_chunks=8,
            )
            context_ids = {chunk.chunk_id for chunk in context_chunks}
            citation_ids = tuple(
                chunk_id
                for chunk_id in answer.citation_chunk_ids
                if chunk_id in context_ids
            )
            ranking = list(
                dict.fromkeys(
                    [chunk.chunk_id for chunk in reranked]
                    + [chunk.chunk_id for chunk in result.rrf_candidates]
                )
            )
            observations[case.query_id] = EvaluationObservation(
                ranked_chunk_ids=tuple(ranking),
                citation_chunk_ids=citation_ids,
                grounded=bool(citation_ids) and answer.status == "completed",
                latency_ms=sum(result.stage_latency.values())
                + sum(audit.latency_ms for audit in gateway.audits[-4:]),
            )
        return observations

    observations = asyncio.run(retrieve_all())
    inputs = [
        EvaluationInput(
            query_id=case.query_id,
            query_type=case.query_type,
            relevant_chunk_ids=tuple(json.loads(case.relevant_chunk_ids or "[]")),
            relevance=json.loads(case.relevance or "{}"),
            forbidden_chunk_ids=tuple(filters.get("forbidden_chunk_ids", [])),
            expected_citation_chunk_ids=tuple(
                filters.get("expected_citation_chunk_ids", [])
            ),
        )
        for case, filters in zip(cases, case_filters)
    ]
    evaluated = evaluate_ranked_cases(
        inputs,
        lambda case: observations.get(
            case.query_id, EvaluationObservation(())
        ),
        k=10,
    )
    evaluated.report["engine_mode"] = run.engine_mode
    evaluated.report["provider_id"] = resolved_provider.provider_id
    evaluated.report["model_id"] = resolved_provider.model_id
    evaluated.report["policy"] = {
        "reason_code": policy.reason_code,
        "policy_version": policy.policy_version,
    }
    _persist_model_calls(
        session,
        dataset.team_id,
        "evaluation:{0}".format(run.id),
        gateway_audits,
    )
    return {"metrics": evaluated.metrics, "report": evaluated.report}


def _case_view(case: EvaluationCase) -> dict:
    return {
        "id": case.id,
        "dataset_id": case.dataset_id,
        "query_id": case.query_id,
        "query_type": case.query_type,
        "query": case.query,
        "relevant_chunk_ids": json.loads(case.relevant_chunk_ids or "[]"),
        "filters": json.loads(case.filters or "{}"),
        "relevance": json.loads(case.relevance or "{}"),
        "created_at": case.created_at.isoformat(),
    }


@router.get("/evals/datasets/detail")
def get_dataset(request: Request, team_id: str, dataset_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    dataset = _dataset_or_error(session, team_id, dataset_id)
    return envelope({"id": dataset.id, "name": dataset.name, "description": dataset.description, "case_count": dataset.case_count, "version": dataset.version}, request.state.request_id)


@router.post("/evals/datasets/update")
def update_dataset(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    dataset = _dataset_or_error(session, team_id, body.get("dataset_id", ""))
    if body.get("name"):
        dataset.name = body["name"].strip()
    if "description" in body:
        dataset.description = body.get("description")
    dataset.version += 1
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="evaluation.dataset.update",
        resource_type="evaluation_dataset",
        resource_id=dataset.id,
        details={"name": dataset.name, "version": dataset.version},
    )
    session.commit()
    return envelope({"id": dataset.id, "name": dataset.name, "version": dataset.version}, request.state.request_id)


@router.post("/evals/datasets/archive")
def archive_dataset(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    dataset = _dataset_or_error(session, team_id, body.get("dataset_id", ""))
    dataset.status = "archived"
    dataset.version += 1
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="evaluation.dataset.archive",
        resource_type="evaluation_dataset",
        resource_id=dataset.id,
        details={"status": dataset.status, "version": dataset.version},
    )
    session.commit()
    return envelope({"id": dataset.id, "status": dataset.status}, request.state.request_id)


@router.get("/evals/datasets/cases")
def list_cases(
    request: Request,
    team_id: str,
    dataset_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _dataset_or_error(session, team_id, dataset_id)
    return paginate_scalars(
        session,
        select(EvaluationCase).where(EvaluationCase.dataset_id == dataset_id),
        timestamp_column=EvaluationCase.created_at,
        id_column=EvaluationCase.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=_case_view,
        descending=False,
    )


@router.post("/evals/datasets/cases/create", status_code=201)
def create_case(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    dataset = _dataset_or_error(session, team_id, body.get("dataset_id", ""))
    case = EvaluationCase(
        dataset_id=dataset.id,
        query_id=body.get("query_id", ""),
        query_type=body.get("query_type", "concept"),
        query=body.get("query", ""),
        relevant_chunk_ids=json.dumps(body.get("relevant_chunk_ids", [])),
        filters=json.dumps(body.get("filters", {})),
        relevance=json.dumps(body.get("relevance", {})),
    )
    session.add(case)
    session.flush()
    dataset.case_count += 1
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="evaluation.case.create",
        resource_type="evaluation_case",
        resource_id=case.id,
        details={
            "dataset_id": dataset.id,
            "query_id": case.query_id,
            "query_type": case.query_type,
        },
    )
    session.commit()
    return envelope(_case_view(case), request.state.request_id)


@router.post("/evals/datasets/cases/update")
def update_case(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    case = session.get(EvaluationCase, body.get("case_id", ""))
    if case is None:
        raise ApiError(404, "NOT_FOUND", "Case was not found.")
    _dataset_or_error(session, team_id, case.dataset_id)
    for field in ("query_id", "query_type", "query"):
        if body.get(field) is not None:
            setattr(case, field, body[field])
    for field in ("relevant_chunk_ids", "filters", "relevance"):
        if body.get(field) is not None:
            setattr(case, field, json.dumps(body[field]))
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="evaluation.case.update",
        resource_type="evaluation_case",
        resource_id=case.id,
        details={
            "dataset_id": case.dataset_id,
            "query_id": case.query_id,
            "query_type": case.query_type,
        },
    )
    session.commit()
    return envelope(_case_view(case), request.state.request_id)


@router.post("/evals/datasets/cases/delete")
def delete_case(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    case = session.get(EvaluationCase, body.get("case_id", ""))
    if case is None:
        raise ApiError(404, "NOT_FOUND", "Case was not found.")
    dataset = _dataset_or_error(session, team_id, case.dataset_id)
    session.delete(case)
    dataset.case_count = max(0, dataset.case_count - 1)
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="evaluation.case.delete",
        resource_type="evaluation_case",
        resource_id=case.id,
        details={"dataset_id": dataset.id, "query_id": case.query_id},
    )
    session.commit()
    return envelope({"deleted": case.id}, request.state.request_id)


@router.post("/evals/datasets/import", status_code=201)
def import_cases(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    dataset = _dataset_or_error(session, team_id, body.get("dataset_id", ""))
    rows = body.get("cases", [])
    if body.get("content"):
        rows = [json.loads(line) for line in body["content"].splitlines() if line.strip()]
    created = []
    for row in rows:
        case = EvaluationCase(
            dataset_id=dataset.id,
            query_id=row.get("query_id", ""),
            query_type=row.get("query_type", "concept"),
            query=row.get("query", ""),
            relevant_chunk_ids=json.dumps(row.get("relevant_chunk_ids", [])),
            filters=json.dumps(row.get("filters", {})),
            relevance=json.dumps(row.get("relevance", {})),
        )
        session.add(case)
        dataset.case_count += 1
        created.append(case)
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="evaluation.case.import",
        resource_type="evaluation_dataset",
        resource_id=dataset.id,
        details={"dataset_id": dataset.id, "imported_count": len(created)},
    )
    session.commit()
    return envelope({"imported": len(created)}, request.state.request_id)


@router.get("/evals/runs/events")
def run_events(request: Request, team_id: str, run_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    _run_or_error(session, team_id, run_id)
    session_factory = request.app.state.session_factory

    async def events():
        previous = None
        while True:
            with session_factory() as event_session:
                current = event_session.get(EvaluationRun, run_id)
                if current is None:
                    return
                payload = {
                    "run_id": current.id,
                    "status": current.status,
                    "stage": _EVALUATION_STAGES.get(current.status, current.status),
                }
                status = current.status

            if payload != previous:
                event = _EVALUATION_TERMINAL_EVENTS.get(status, "progress")
                yield "event: {0}\ndata: {1}\n\n".format(
                    event,
                    json.dumps(payload, ensure_ascii=False),
                )
                previous = payload
            if status in _EVALUATION_TERMINAL_STATUSES:
                return
            await _wait_for_evaluation_poll()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _wait_for_evaluation_poll():
    await asyncio.sleep(1)


@router.post("/evals/runs/cancel", status_code=202)
def cancel_run(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    run = _run_or_error(session, team_id, body.get("run_id", ""))
    if run.status == "cancelled":
        return envelope({"id": run.id, "status": run.status}, request.state.request_id)
    if run.status in {"succeeded", "failed"}:
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Run is already finished.")

    transitioned = session.execute(
        update(EvaluationRun)
        .where(
            EvaluationRun.id == run.id,
            EvaluationRun.status.in_(("queued", "running")),
        )
        .values(status="cancelled")
        .execution_options(synchronize_session=False)
    ).rowcount
    if not transitioned:
        session.rollback()
        current = session.get(EvaluationRun, run.id)
        if current is None:
            raise ApiError(404, "NOT_FOUND", "Run was not found.")
        if current.status == "cancelled":
            return envelope(
                {"id": current.id, "status": current.status},
                request.state.request_id,
            )
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Run is already finished.")
    session.expire_all()
    run = session.get(EvaluationRun, run.id)
    write_audit(
        session,
        team_id=team_id,
        actor_id=user.id,
        action="evaluation.run.cancel",
        resource_type="evaluation_run",
        resource_id=run.id,
        details={"dataset_id": run.dataset_id, "status": run.status},
    )
    session.commit()
    return envelope({"id": run.id, "status": run.status}, request.state.request_id)


@router.get("/evals/runs/report")
def run_report(request: Request, team_id: str, run_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    run = _run_or_error(session, team_id, run_id)
    result = session.scalar(select(EvaluationResult).where(EvaluationResult.run_id == run_id))
    return envelope(
        {
            "run_id": run.id,
            "status": run.status,
            "provider_id": run.provider_id,
            "model_id": run.model_id,
            "metrics": json.loads(result.metrics or "{}") if result else {},
            "report": json.loads(result.report or "{}") if result else {},
        },
        request.state.request_id,
    )
