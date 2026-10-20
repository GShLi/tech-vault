import asyncio
import json
import time
import uuid
from dataclasses import replace
from typing import Any, List, Optional, Sequence

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor, paginate_scalars
from backend.app.api.v1.schemas import AskRequest, ChatView, MessageView
from backend.app.api.v1.documents import _granted_document_ids
from backend.app.api.v1.kbs import readable_document_facets
from backend.app.api.v1.kb_access import (
    knowledge_base_member_ids,
    knowledge_base_or_error,
)
from backend.app.api.v1.teams import _membership_or_error, _if_match_version
from backend.app.core.llm_policy import normalize_classification, resolve_model_policy
from backend.app.core.ids import new_ulid
from backend.app.core.secrets import decrypt_secret
from backend.app.db.models import (
    Chat,
    ChunkRecord,
    DeploymentModelPolicyRecord,
    Feedback,
    IndexGenerationRecord,
    KnowledgeBase,
    Message,
    ModelCall,
    ModelPolicyRecord,
    TraceRecord,
    User,
)
from backend.app.modules.providers.resolution import ResolvedProvider, resolve_provider
from backend.app.rag.domain.models import (
    DataClassification,
    ModelPolicyDecision,
    RetrievalFilters,
    SearchRequest,
    SearchResult,
)
from backend.app.rag.embedding.service import EmbeddingClient
from backend.app.rag.llm_gateway import (
    GatewayAudit,
    LlmGateway,
    ModelUnavailableError,
    PolicyDeniedError,
)
from backend.app.rag.llm_gateway.providers import (
    ProviderAdapterError,
    build_provider_adapter,
)
from backend.app.rag.retrieval.config import EngineMode
from backend.app.rag.retrieval.factory import build_retriever
from backend.app.rag.rerank.service import RerankerClient


router = APIRouter(tags=["chats"])


class _StreamCancelled(Exception):
    pass

_MODE_RANK = {"local_only": 0, "external_allowed": 1, "external_required": 2}
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.PRIVATE: 2,
    DataClassification.RESTRICTED: 3,
}


def _normalize_citations(value: Any) -> List[dict]:
    rows = value if isinstance(value, list) else []
    normalized = []
    for item in rows:
        if isinstance(item, dict):
            citation = dict(item)
        else:
            citation = {"citation_id": str(item)}
        if citation.get("citation_id"):
            normalized.append(citation)
    return normalized


def _chat_view(chat: Chat) -> dict:
    return ChatView(
        id=chat.id,
        team_id=chat.team_id,
        user_id=chat.user_id,
        title=chat.title,
        knowledge_base_ids=json.loads(chat.knowledge_base_ids) if chat.knowledge_base_ids else [],
        version=chat.version,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    ).model_dump()


def _message_view(msg: Message) -> dict:
    raw_citations = json.loads(msg.citation_ids) if msg.citation_ids else []
    return MessageView(
        id=msg.id,
        chat_id=msg.chat_id,
        role=msg.role,
        content=msg.content,
        status=msg.status,
        trace_id=msg.trace_id,
        citation_ids=_normalize_citations(raw_citations),
        refusal_reason=msg.refusal_reason,
        created_at=msg.created_at,
    ).model_dump()


def _chat_owner_or_error(
    session: Session, team_id: str, chat_id: str, user_id: str
) -> Chat:
    chat = session.get(Chat, chat_id)
    if chat is None or chat.team_id != team_id or chat.user_id != user_id:
        raise ApiError(403, "PERMISSION_DENIED", "Chat is not accessible.")
    return chat


def _message_or_error(
    session: Session, team_id: str, message_id: str, user_id: str
) -> Message:
    message = session.get(Message, message_id)
    if message is None:
        raise ApiError(404, "NOT_FOUND", "Message was not found.")
    _chat_owner_or_error(session, team_id, message.chat_id, user_id)
    return message


@router.get("/chats")
def list_chats(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    page_limit = max(1, min(limit, 100))
    query = select(Chat).where(Chat.team_id == team_id, Chat.user_id == user.id)
    if cursor is not None:
        after_created, after_id = decode_cursor(cursor)
        query = query.where(
            or_(Chat.updated_at < after_created,
                and_(Chat.updated_at == after_created, Chat.id < after_id))
        )
    rows = session.scalars(query.order_by(Chat.updated_at.desc(), Chat.id.desc()).limit(page_limit + 1)).all()
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    next_cursor = encode_cursor(page_rows[-1].updated_at, page_rows[-1].id) if has_more and page_rows else None
    return page_envelope([_chat_view(c) for c in page_rows], request.state.request_id, next_cursor)


@router.post("/chats/create", status_code=201)
def create_chat(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _membership_or_error(session, team_id, user.id)
    requested_title = body.get("title")
    if requested_title is None:
        title = "新对话"
    elif isinstance(requested_title, str):
        title = requested_title.strip()[:200] or "新对话"
    else:
        raise ApiError(400, "INVALID_ARGUMENT", "Title must be a string.")
    chat = Chat(
        team_id=team_id,
        user_id=user.id,
        title=title,
        knowledge_base_ids=json.dumps(body.get("knowledge_base_ids", [])),
    )
    session.add(chat)
    session.commit()
    return envelope(_chat_view(chat), request.state.request_id)


@router.get("/chats/detail")
def get_chat(
    request: Request,
    team_id: str,
    chat_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    chat = _chat_owner_or_error(session, team_id, chat_id, user.id)
    return envelope(_chat_view(chat), request.state.request_id)


@router.post("/chats/delete")
def delete_chat(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    chat_id = body.get("chat_id", "")
    _membership_or_error(session, team_id, user.id)
    chat = _chat_owner_or_error(session, team_id, chat_id, user.id)

    # Serialize chat deletion with message inserts on PostgreSQL before detaching
    # audit traces and explicitly removing dependent feedback rows.
    session.execute(
        select(Chat.id).where(Chat.id == chat_id).with_for_update()
    ).scalar_one()
    message_ids = tuple(
        session.scalars(select(Message.id).where(Message.chat_id == chat_id)).all()
    )
    trace_filter = TraceRecord.chat_id == chat_id
    if message_ids:
        trace_filter = or_(
            trace_filter,
            TraceRecord.message_id.in_(message_ids),
        )
    session.execute(
        update(TraceRecord)
        .where(trace_filter)
        .values(chat_id=None, message_id=None)
    )
    if message_ids:
        session.execute(
            delete(Feedback).where(Feedback.message_id.in_(message_ids))
        )
    session.execute(delete(Message).where(Message.chat_id == chat_id))
    session.delete(chat)
    session.commit()
    return envelope({"deleted": chat_id}, request.state.request_id)


@router.get("/chats/messages")
def list_messages(
    request: Request,
    team_id: str,
    chat_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _chat_owner_or_error(session, team_id, chat_id, user.id)
    return paginate_scalars(
        session,
        select(Message).where(Message.chat_id == chat_id),
        timestamp_column=Message.created_at,
        id_column=Message.id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=_message_view,
        descending=False,
    )


def _candidate_rows(chunks) -> list:
    return [
        {
            "chunk_id": chunk.chunk_id,
            "rank": chunk.fused_rank,
            "score": chunk.rerank_score,
            "bm25_rank": chunk.bm25_rank,
            "dense_rank": chunk.dense_rank,
        }
        for chunk in chunks
    ]


def _rewrite_trace_payload(rewrite: Optional[Any]) -> dict:
    if rewrite is None:
        return {}
    return {
        "original_query": rewrite.original_query,
        "rewritten_query": rewrite.rewritten_query,
        "changed": rewrite.changed,
        "route": rewrite.route,
        "provider_id": rewrite.provider_id,
        "model_id": rewrite.model_id,
        "structured_mode": rewrite.structured_mode,
        "extracted_filters": rewrite.extracted_filters,
        "applied_filters": rewrite.applied_filters,
        "dropped_filters": rewrite.dropped_filters,
        "fallback_reason": rewrite.fallback_reason,
        "validation_error": rewrite.validation_error,
        "latency_ms": rewrite.latency_ms,
        "input_tokens": rewrite.input_tokens,
        "output_tokens": rewrite.output_tokens,
    }


def _rewrite_json(rewrite: Optional[Any]) -> str:
    return json.dumps(
        _rewrite_trace_payload(rewrite),
        ensure_ascii=False,
    )


def _applied_filter_values(
    rewrite: Optional[Any],
    fallback_product: Optional[str],
    fallback_versions: Sequence[str],
) -> tuple[Optional[str], tuple[str, ...]]:
    filters = rewrite.applied_filters if rewrite is not None else {}
    product = filters.get("product", fallback_product)
    versions = tuple(
        filters.get("version_values", list(fallback_versions)) or ()
    )
    return product, versions


def _recent_chat_history(session: Session, chat_id: str) -> List[dict]:
    rows = session.scalars(
        select(Message)
        .where(
            Message.chat_id == chat_id,
            Message.role.in_(("user", "assistant")),
            Message.status.in_(("completed", "refused")),
        )
        .order_by(Message.created_at.desc())
        .limit(6)
    ).all()
    return [
        {"role": message.role, "content": message.content}
        for message in reversed(rows)
    ]


def _strictest_mode(modes: Sequence[Optional[str]]) -> Optional[str]:
    valid = [mode for mode in modes if mode in _MODE_RANK]
    if not valid:
        return None
    return min(valid, key=lambda mode: _MODE_RANK[str(mode)])


def _policy_decision(
    session: Session,
    team_id: str,
    knowledge_base_ids: Sequence[str],
    user_id: str,
    request_mode: str,
    classification: DataClassification,
) -> ModelPolicyDecision:
    deployment = session.scalar(
        select(DeploymentModelPolicyRecord).order_by(
            DeploymentModelPolicyRecord.created_at.asc()
        )
    )
    team_policy = session.scalar(
        select(ModelPolicyRecord).where(ModelPolicyRecord.team_id == team_id)
    )
    knowledge_bases = session.scalars(
        select(KnowledgeBase).where(
            KnowledgeBase.team_id == team_id,
            KnowledgeBase.id.in_(tuple(knowledge_base_ids)),
            KnowledgeBase.id.in_(
                knowledge_base_member_ids(session, team_id, user_id)
            ),
        )
    ).all()
    if len(knowledge_bases) != len(set(knowledge_base_ids)):
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    if any(kb.status != "active" for kb in knowledge_bases):
        raise ApiError(
            409,
            "RESOURCE_STATE_CONFLICT",
            "Archived knowledge bases cannot be queried.",
        )

    deployment_mode = deployment.mode if deployment is not None else "local_only"
    team_mode = team_policy.mode if team_policy is not None else None
    knowledge_base_mode = _strictest_mode(
        [kb.model_policy_mode for kb in knowledge_bases]
    )
    deployment_classification = normalize_classification(
        deployment.max_data_classification if deployment is not None else "internal"
    )
    classification_cap = deployment_classification
    if team_policy is not None:
        team_classification = normalize_classification(
            team_policy.max_data_classification
        )
        if (
            _CLASSIFICATION_RANK[team_classification]
            < _CLASSIFICATION_RANK[deployment_classification]
        ):
            classification_cap = team_classification

    deployment_providers = set(
        json.loads(deployment.allowed_provider_ids or "[]")
        if deployment is not None
        else []
    )
    if team_policy is None:
        allowed_providers = deployment_providers
    else:
        allowed_providers = deployment_providers.intersection(
            json.loads(team_policy.allowed_provider_ids or "[]")
        )
    allow_history = bool(deployment.allow_chat_history) if deployment else False
    allow_metadata = bool(deployment.allow_document_metadata) if deployment else False
    if team_policy is not None:
        allow_history = allow_history and team_policy.allow_chat_history
        allow_metadata = allow_metadata and team_policy.allow_document_metadata

    versions = []
    if deployment is not None:
        versions.append("deployment:{0}".format(deployment.version))
    if team_policy is not None:
        versions.append("team:{0}".format(team_policy.version))
    return resolve_model_policy(
        deployment_mode=deployment_mode,
        team_mode=team_mode,
        knowledge_base_mode=knowledge_base_mode,
        request_mode=None if request_mode == "inherit" else request_mode,
        requested_classification=classification,
        allowed_provider_ids=tuple(sorted(allowed_providers)),
        allow_chat_history=allow_history,
        allow_document_metadata=allow_metadata,
        max_data_classification=classification_cap,
        policy_version=";".join(versions) or "default",
    )


def _classification_for_chunks(
    session: Session, chunks: Sequence[Any]
) -> DataClassification:
    chunk_ids = [chunk.chunk_id for chunk in chunks if chunk.chunk_id]
    if not chunk_ids:
        return DataClassification.INTERNAL
    classifications = session.scalars(
        select(ChunkRecord.data_classification).where(ChunkRecord.id.in_(chunk_ids))
    ).all()
    maximum = DataClassification.PUBLIC
    for value in classifications:
        try:
            classification = DataClassification(value)
        except ValueError:
            classification = DataClassification.RESTRICTED
        if (
            _CLASSIFICATION_RANK[classification]
            > _CLASSIFICATION_RANK[maximum]
        ):
            maximum = classification
    return maximum if classifications else DataClassification.INTERNAL


def _build_gateway(
    request: Request,
    decision: ModelPolicyDecision,
    resolved_provider: ResolvedProvider,
) -> LlmGateway:
    try:
        api_key = decrypt_secret(
            resolved_provider.encrypted_api_key,
            request.app.state.settings,
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
    audits: List[GatewayAudit] = []
    return LlmGateway(
        decision=decision,
        external_answer_provider=answer_provider,
        external_api_key=api_key,
        local_embed_provider=EmbeddingClient(request.app.state.settings.embedding_url),
        local_rerank_provider=RerankerClient(request.app.state.settings.rerank_url),
        audit_sink=audits.append,
    )


def _persist_model_calls(
    session: Session,
    team_id: str,
    request_id: str,
    audits: Sequence[GatewayAudit],
) -> None:
    for audit in audits:
        session.add(
            ModelCall(
                team_id=team_id,
                provider_id=audit.provider_id,
                model_id=audit.model_id,
                purpose=audit.purpose,
                classification=audit.classification,
                external=audit.external,
                request_id=request_id,
                cost_micros=audit.cost_micros,
                latency_ms=audit.latency_ms,
            )
        )


def _citation_rows(
    chunks: Sequence[Any],
    context_chunks: Sequence[Any],
) -> List[dict]:
    source_indexes = {
        chunk.chunk_id: index
        for index, chunk in enumerate(context_chunks, start=1)
    }
    rows = []
    for chunk in chunks:
        source_index = source_indexes.get(chunk.chunk_id)
        if source_index is None:
            continue
        rows.append(
            {
                "citation_id": "c{0}".format(source_index),
                "chunk_id": chunk.chunk_id,
                "document_version_id": chunk.document_version_id,
                "excerpt": chunk.content[:500],
                "source_locator": chunk.source_locator,
            }
        )
    return rows


def _hydrate_source_locators(session: Session, chunks: Sequence[Any]) -> List[Any]:
    """Use persisted chunk metadata when a retrieval engine omits locator fields."""

    chunk_ids = [chunk.chunk_id for chunk in chunks if chunk.chunk_id]
    if not chunk_ids:
        return list(chunks)
    rows = session.execute(
        select(ChunkRecord.id, ChunkRecord.source_locator).where(
            ChunkRecord.id.in_(chunk_ids)
        )
    ).all()
    persisted = {}
    for chunk_id, raw_locator in rows:
        try:
            locator = json.loads(raw_locator or "{}")
        except (TypeError, json.JSONDecodeError):
            locator = {}
        if isinstance(locator, dict):
            persisted[chunk_id] = locator
    hydrated = []
    for chunk in chunks:
        locator = persisted.get(chunk.chunk_id)
        if not locator:
            hydrated.append(chunk)
            continue
        hydrated.append(
            replace(chunk, source_locator={**locator, **dict(chunk.source_locator)})
        )
    return hydrated


def _stream_answer_response(
    request: Request,
    *,
    team_id: str,
    user_id: str,
    chat_id: str,
    question: str,
    history: Sequence[dict],
    knowledge_base_ids: Sequence[str],
    decision: ModelPolicyDecision,
    resolved_provider: ResolvedProvider,
    product: Optional[str],
    version_values: Sequence[str],
    generation_id: str,
    engine_mode: EngineMode,
    explicit_document_grants: Sequence[str],
    message_id: str,
    policy_latency_ms: float,
    facet_catalog: dict,
) -> StreamingResponse:
    session_factory = request.app.state.session_factory

    def message_status() -> str:
        with session_factory() as stream_session:
            message = stream_session.get(Message, message_id)
            return message.status if message is not None else "missing"

    def persist_message(
        next_status: str,
        content: str,
        *,
        trace_id: Optional[str] = None,
        citations: Optional[List[dict]] = None,
        refusal_reason: Optional[str] = None,
    ) -> None:
        with session_factory() as stream_session:
            message = stream_session.get(Message, message_id)
            if message is None:
                return
            if message.status == "cancelled" and next_status != "cancelled":
                return
            message.content = content
            message.status = next_status
            if trace_id is not None:
                message.trace_id = trace_id
            if citations is not None:
                message.citation_ids = json.dumps(citations, ensure_ascii=False)
            if refusal_reason is not None:
                message.refusal_reason = refusal_reason
            stream_session.commit()

    def effective_stage_latency(
        *,
        result: Optional[SearchResult],
        stage_latency: Optional[dict[str, float]],
        gateway_instance: Optional[LlmGateway],
    ) -> dict[str, float]:
        latency = dict(result.stage_latency) if result is not None else {}
        if stage_latency:
            latency.update(stage_latency)
        if gateway_instance is not None:
            latency.update(
                {
                    "gateway_{0}_ms".format(audit.purpose): float(
                        audit.latency_ms
                    )
                    for audit in gateway_instance.audits
                }
            )
        return latency

    def persist_trace(
        *,
        result: Optional[SearchResult],
        rewrite: Optional[Any],
        answer: Optional[Any],
        policy: Optional[ModelPolicyDecision],
        gateway_instance: Optional[LlmGateway],
        classification: Optional[DataClassification],
        terminal_status: str,
        error_code: Optional[str] = None,
        trace_id: Optional[str] = None,
        stage_latency: Optional[dict[str, float]] = None,
        degraded: Optional[bool] = None,
    ) -> None:
        effective_trace_id = (
            result.trace_id if result is not None and result.trace_id else trace_id
        )
        if not effective_trace_id:
            return
        with session_factory() as stream_session:
            message = stream_session.get(Message, message_id)
            if message is not None:
                message.trace_id = effective_trace_id
            trace = stream_session.scalar(
                select(TraceRecord).where(TraceRecord.message_id == message_id)
            )
            if trace is None:
                trace = TraceRecord(
                    team_id=team_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    trace_id=effective_trace_id,
                    engine_mode=engine_mode.value,
                    original_query=question,
                )
                stream_session.add(trace)
            trace.trace_id = effective_trace_id
            trace.rewritten_query = (
                rewrite.rewritten_query if rewrite is not None else None
            )
            trace.rewrite = _rewrite_json(rewrite)
            trace_product, trace_versions = _applied_filter_values(
                rewrite,
                product,
                version_values,
            )
            trace.filters = json.dumps(
                {
                    "team_id": team_id,
                    "knowledge_base_ids": list(knowledge_base_ids),
                    "viewer_user_id": user_id,
                    "product": trace_product,
                    "version_values": list(trace_versions),
                    "explicit_document_grant_count": len(explicit_document_grants),
                }
            )
            trace.bm25_candidates = json.dumps(
                _candidate_rows(result.bm25_candidates if result is not None else ()),
                ensure_ascii=False,
            )
            trace.dense_candidates = json.dumps(
                _candidate_rows(result.dense_candidates if result is not None else ()),
                ensure_ascii=False,
            )
            trace.rrf_candidates = json.dumps(
                _candidate_rows(result.rrf_candidates if result is not None else ()),
                ensure_ascii=False,
            )
            trace.rerank_candidates = json.dumps(
                _candidate_rows(result.rerank_candidates if result is not None else ()),
                ensure_ascii=False,
            )
            trace.final_context = json.dumps(
                [
                    {
                        "chunk_id": chunk.chunk_id,
                        "document_version_id": chunk.document_version_id,
                        "rank": chunk.fused_rank,
                        "score": chunk.rerank_score,
                    }
                    for chunk in (result.chunks if result is not None else ())
                ],
                ensure_ascii=False,
            )
            latency = effective_stage_latency(
                result=result,
                stage_latency=stage_latency,
                gateway_instance=gateway_instance,
            )
            trace.stage_latency_ms = json.dumps(latency)
            trace.degraded = bool(
                (result is not None and result.degraded)
                or (answer is not None and answer.degraded)
                or (
                    gateway_instance is not None
                    and any(audit.degraded for audit in gateway_instance.audits)
                )
                or bool(degraded)
            )
            trace.error_code = error_code
            trace.model = json.dumps(
                {
                    "status": terminal_status,
                    "provider_id": resolved_provider.provider_id,
                    "model_id": (
                        answer.model_id
                        if answer is not None
                        else resolved_provider.model_id
                    ),
                    "route": (
                        answer.route
                        if answer is not None
                        else resolved_provider.provider_type
                    ),
                    "external": True,
                    "policy": policy.reason_code if policy is not None else None,
                    "policy_version": (
                        policy.policy_version if policy is not None else None
                    ),
                    "classification": (
                        classification.value
                        if classification is not None
                        else DataClassification.INTERNAL.value
                    ),
                    "input_tokens": answer.input_tokens if answer is not None else 0,
                    "output_tokens": answer.output_tokens if answer is not None else 0,
                    "cost_micros": answer.cost_micros if answer is not None else 0,
                },
                ensure_ascii=False,
            )
            stream_session.commit()

    def persist_audits(gateway_instance: Optional[LlmGateway]) -> None:
        if gateway_instance is None or not gateway_instance.audits:
            return
        with session_factory() as stream_session:
            existing = stream_session.scalar(
                select(ModelCall.id)
                .where(ModelCall.request_id == request.state.request_id)
                .limit(1)
            )
            if existing is not None:
                return
            _persist_model_calls(
                stream_session,
                team_id,
                request.state.request_id,
                gateway_instance.audits,
            )
            stream_session.commit()

    def sse(event_name: str, data: dict) -> str:
        return "event: {0}\ndata: {1}\n\n".format(
            event_name, json.dumps(data, ensure_ascii=False)
        )

    def background_cancel() -> None:
        if message_status() == "generating":
            persist_message("cancelled", "")

    async def stream_events():
        sent_text = ""
        terminal = False
        result = None
        rewrite = None
        answer = None
        policy = decision
        gateway = None
        classification = DataClassification.INTERNAL
        stage_latency: dict[str, float] = {"policy_ms": policy_latency_ms}
        fallback_trace_id = str(uuid.uuid4())

        async def ensure_active() -> None:
            if await request.is_disconnected() or message_status() == "cancelled":
                persist_message("cancelled", sent_text)
                raise _StreamCancelled()

        try:
            await ensure_active()
            yield sse(
                "meta",
                {
                    "message_id": message_id,
                    "trace_id": "",
                    "engine_mode": engine_mode.value,
                    "status": "generating",
                },
            )
            await asyncio.sleep(0)

            await ensure_active()
            gateway = _build_gateway(request, decision, resolved_provider)

            await ensure_active()
            started = time.perf_counter()
            rewrite = await asyncio.to_thread(
                gateway.rewrite,
                question=question,
                history=history,
                product=product,
                version_values=version_values,
                allowed_products=tuple(facet_catalog["products"]),
                allowed_versions=tuple(facet_catalog["versions"]),
                allow_chat_history=decision.allow_chat_history,
                classification=DataClassification.INTERNAL,
            )
            stage_latency["rewrite_ms"] = (time.perf_counter() - started) * 1000.0
            if rewrite.changed:
                yield sse(
                    "rewrite",
                    {
                        "original": rewrite.original_query,
                        "rewritten": rewrite.rewritten_query,
                    },
                )

            await ensure_active()
            started = time.perf_counter()
            vectors = await asyncio.to_thread(
                gateway.embed,
                [rewrite.rewritten_query],
                classification=DataClassification.INTERNAL,
            )
            stage_latency["embedding_ms"] = (time.perf_counter() - started) * 1000.0
            if not vectors:
                raise RuntimeError("embedding provider returned no vectors")

            await ensure_active()
            started = time.perf_counter()
            applied_product = rewrite.applied_filters.get("product")
            applied_versions = tuple(
                rewrite.applied_filters.get("version_values") or ()
            )
            try:
                retriever = build_retriever(
                    request.app.state.settings,
                    generation_id,
                    engine_mode,
                )
                result = await retriever.search(
                    SearchRequest(
                        query=question,
                        rewritten_query=rewrite.rewritten_query,
                        query_vector=vectors[0],
                        filters=RetrievalFilters(
                            team_id=team_id,
                            knowledge_base_ids=tuple(knowledge_base_ids),
                            viewer_user_id=user_id,
                            product=applied_product,
                            version_values=applied_versions,
                            explicit_document_grants=tuple(explicit_document_grants),
                        ),
                        final_top_n=10,
                    )
                )
            finally:
                stage_latency["retrieval_ms"] = (
                    time.perf_counter() - started
                ) * 1000.0

            await ensure_active()
            started = time.perf_counter()
            rerank_input = list(result.rrf_candidates or result.chunks)
            with session_factory() as stream_session:
                classification = _classification_for_chunks(
                    stream_session, rerank_input
                )
            reranked = await asyncio.to_thread(
                gateway.rerank,
                rewrite.rewritten_query,
                rerank_input,
                top_n=10,
                classification=classification,
            )
            context_chunks = reranked[:8]
            with session_factory() as stream_session:
                context_chunks = _hydrate_source_locators(
                    stream_session, context_chunks
                )
            stage_latency["rerank_ms"] = (time.perf_counter() - started) * 1000.0
            result = replace(
                result,
                chunks=context_chunks,
                rerank_candidates=tuple(reranked),
                stage_latency={
                    **result.stage_latency,
                    **{
                        "gateway_{0}_ms".format(audit.purpose): float(
                            audit.latency_ms
                        )
                        for audit in gateway.audits
                    },
                },
                degraded=result.degraded
                or any(audit.degraded for audit in gateway.audits),
            )
            persist_trace(
                result=result,
                rewrite=rewrite,
                answer=None,
                policy=policy,
                gateway_instance=gateway,
                classification=classification,
                terminal_status="running",
            )

            await ensure_active()
            answer_stream = await asyncio.to_thread(
                gateway.generate_stream,
                question=rewrite.rewritten_query,
                chunks=context_chunks,
                classification=classification,
                max_chunks=8,
            )

            try:
                async for piece in answer_stream:
                    await ensure_active()
                    sent_text += piece
                    persist_message("generating", sent_text)
                    yield sse("delta", {"text": piece})
            finally:
                await answer_stream.aclose()

            await ensure_active()
            answer = answer_stream.result
            if answer is None:
                raise RuntimeError("answer stream completed without a result")
            chunk_by_id = {chunk.chunk_id: chunk for chunk in context_chunks}
            citation_chunks = [
                chunk_by_id[chunk_id]
                for chunk_id in answer.citation_chunk_ids
                if answer.status == "completed" and chunk_id in chunk_by_id
            ]
            if answer.status == "completed" and not citation_chunks:
                if context_chunks:
                    answer = replace(
                        answer,
                        status="refused",
                        citation_chunk_ids=(),
                        refusal_reason="INSUFFICIENT_EVIDENCE",
                        degraded=True,
                    )
                else:
                    answer = replace(
                        answer,
                        text="知识库中没有足够依据。",
                        status="refused",
                        citation_chunk_ids=(),
                        refusal_reason="INSUFFICIENT_EVIDENCE",
                    )
                    sent_text = answer.text
            citations = _citation_rows(citation_chunks, context_chunks)

            result = replace(
                result,
                chunks=context_chunks,
                degraded=result.degraded or answer.degraded,
            )
            persist_trace(
                result=result,
                rewrite=rewrite,
                answer=answer,
                policy=policy,
                gateway_instance=gateway,
                classification=classification,
                terminal_status=answer.status,
                stage_latency=stage_latency,
            )
            persist_audits(gateway)

            if answer.status == "refused":
                persist_message(
                    "refused",
                    answer.text,
                    trace_id=result.trace_id,
                    citations=[],
                    refusal_reason=answer.refusal_reason,
                )
                terminal = True
                yield sse(
                    "refused",
                    {
                        "message_id": message_id,
                        "status": "refused",
                        "reason_code": answer.refusal_reason,
                        "message": answer.text,
                    },
                )
                return

            persist_message(
                answer.status,
                answer.text,
                trace_id=result.trace_id,
                citations=citations,
                refusal_reason=answer.refusal_reason,
            )
            for citation in citations:
                locator = citation["source_locator"] or {}
                yield sse(
                    "citation",
                    {
                        "citation_id": citation["citation_id"],
                        "chunk_id": citation["chunk_id"],
                        "document_id": locator.get("document_id", ""),
                        "document_version_id": citation["document_version_id"],
                        "document_name": locator.get("file_name", ""),
                        "page_no": locator.get("page_no"),
                        "heading_path": locator.get("heading_path", []),
                        "source_url": locator.get("source_url", ""),
                        "excerpt": citation["excerpt"],
                    },
                )
            terminal = True
            yield sse(
                "done",
                {
                    "message_id": message_id,
                    "status": answer.status,
                    "citation_ids": [
                        citation["citation_id"] for citation in citations
                    ],
                    "model_id": answer.model_id,
                    "route": answer.route,
                    "policy": policy.reason_code,
                    "policy_version": policy.policy_version,
                    "classification": classification.value,
                    "degraded": result.degraded,
                    "input_tokens": answer.input_tokens,
                    "output_tokens": answer.output_tokens,
                    "cost_micros": answer.cost_micros,
                    "latency_ms": int(
                        sum(
                            effective_stage_latency(
                                result=result,
                                stage_latency=stage_latency,
                                gateway_instance=gateway,
                            ).values()
                        )
                    ),
                },
            )
        except _StreamCancelled:
            terminal = True
            persist_trace(
                result=result,
                rewrite=rewrite,
                answer=answer,
                policy=policy,
                gateway_instance=gateway,
                classification=classification,
                terminal_status="cancelled",
                error_code="CLIENT_CANCELLED",
                trace_id=fallback_trace_id,
                stage_latency=stage_latency,
            )
            persist_audits(gateway)
        except Exception as error:
            code = "STREAM_ERROR"
            if isinstance(error, PolicyDeniedError):
                code = "POLICY_DENIED"
            elif isinstance(error, ModelUnavailableError):
                code = "MODEL_UNAVAILABLE"
            elif isinstance(error, ProviderAdapterError):
                code = error.code
            elif isinstance(error, ApiError):
                code = error.code
            persist_message("failed", sent_text)
            persist_trace(
                result=result,
                rewrite=rewrite,
                answer=answer,
                policy=policy,
                gateway_instance=gateway,
                classification=classification,
                terminal_status="failed",
                error_code=code,
                trace_id=fallback_trace_id,
                stage_latency=stage_latency,
                degraded=True,
            )
            persist_audits(gateway)
            terminal = True
            yield sse(
                "error",
                {
                    "code": code,
                    "message": str(error) or error.__class__.__name__,
                    "retryable": code == "STREAM_ERROR",
                    "request_id": request.state.request_id,
                },
            )
        finally:
            if not terminal:
                persist_message("cancelled", sent_text)
                persist_trace(
                    result=result,
                    rewrite=rewrite,
                    answer=answer,
                    policy=policy,
                    gateway_instance=gateway,
                    classification=classification,
                    terminal_status="cancelled",
                    error_code="CLIENT_CANCELLED",
                    trace_id=fallback_trace_id,
                    stage_latency=stage_latency,
                )

    return StreamingResponse(
        stream_events(),
        media_type="text/event-stream",
        background=BackgroundTask(background_cancel),
    )


@router.post("/chats/ask")
async def ask(
    body: AskRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, body.team_id, user.id)
    stage_latency: dict[str, float] = {}
    chat = _chat_owner_or_error(session, body.team_id, body.chat_id, user.id)
    knowledge_base_ids = body.selected_knowledge_base_ids() or json.loads(
        chat.knowledge_base_ids or "[]"
    )
    if not knowledge_base_ids:
        raise ApiError(400, "INVALID_ARGUMENT", "Select at least one knowledge base.")
    for knowledge_base_id in knowledge_base_ids:
        knowledge_base_or_error(
            session,
            body.team_id,
            knowledge_base_id,
            user.id,
        )
    started = time.perf_counter()
    policy = _policy_decision(
        session,
        body.team_id,
        knowledge_base_ids,
        user.id,
        body.model_policy,
        DataClassification.INTERNAL,
    )
    resolved_provider = resolve_provider(
        session,
        body.team_id,
        body.provider_id,
        body.model_id,
        policy,
    )
    stage_latency["policy_ms"] = (time.perf_counter() - started) * 1000.0

    question = body.question
    history = _recent_chat_history(session, chat.id)
    generation = session.scalar(
        select(IndexGenerationRecord)
        .where(
            IndexGenerationRecord.team_id == body.team_id,
            IndexGenerationRecord.status == "active",
        )
        .order_by(IndexGenerationRecord.activated_at.desc())
    )
    if generation is None:
        raise ApiError(
            503,
            "INDEX_NOT_READY",
            "The team index generation is not active.",
        )
    engine_mode = EngineMode(request.app.state.settings.engine_mode)
    explicit_document_grants = _granted_document_ids(
        session, body.team_id, user.id
    )
    facet_catalog = readable_document_facets(
        session,
        body.team_id,
        user,
        tuple(knowledge_base_ids),
    )
    user_message = Message(
        id=new_ulid(),
        chat_id=chat.id,
        role="user",
        content=question,
        status="completed",
    )
    session.add(user_message)

    failure_trace_id = str(uuid.uuid4())
    def persist_failure_trace(
        error_code: str,
        *,
        result: Optional[SearchResult] = None,
        rewrite: Optional[Any] = None,
        policy: Optional[ModelPolicyDecision] = None,
        gateway_instance: Optional[LlmGateway] = None,
        classification: Optional[DataClassification] = None,
        degraded: bool = True,
    ) -> None:
        effective_trace_id = (
            result.trace_id
            if result is not None and result.trace_id
            else failure_trace_id
        )
        failed_user_message = Message(
            id=new_ulid(),
            chat_id=chat.id,
            role="user",
            content=question,
            status="completed",
        )
        failed_assistant_message = Message(
            id=new_ulid(),
            chat_id=chat.id,
            role="assistant",
            content="",
            status="failed",
            trace_id=effective_trace_id,
            citation_ids="[]",
        )
        session.add_all([failed_user_message, failed_assistant_message])
        latency = dict(result.stage_latency) if result is not None else {}
        latency.update(stage_latency)
        if gateway_instance is not None:
            latency.update(
                {
                    "gateway_{0}_ms".format(audit.purpose): float(audit.latency_ms)
                    for audit in gateway_instance.audits
                }
            )
        failure_product, failure_versions = _applied_filter_values(
            rewrite,
            body.filters.product,
            body.filters.version_values,
        )
        session.add(
            TraceRecord(
                team_id=body.team_id,
                chat_id=chat.id,
                message_id=failed_assistant_message.id,
                trace_id=effective_trace_id,
                engine_mode=engine_mode.value,
                original_query=question,
                rewritten_query=(
                    rewrite.rewritten_query if rewrite is not None else None
                ),
                rewrite=_rewrite_json(rewrite),
                filters=json.dumps(
                    {
                        "team_id": body.team_id,
                        "knowledge_base_ids": knowledge_base_ids,
                        "viewer_user_id": user.id,
                        "product": failure_product,
                        "version_values": list(failure_versions),
                        "explicit_document_grant_count": len(explicit_document_grants),
                    }
                ),
                bm25_candidates=json.dumps(
                    _candidate_rows(result.bm25_candidates if result is not None else ()),
                    ensure_ascii=False,
                ),
                dense_candidates=json.dumps(
                    _candidate_rows(result.dense_candidates if result is not None else ()),
                    ensure_ascii=False,
                ),
                rrf_candidates=json.dumps(
                    _candidate_rows(result.rrf_candidates if result is not None else ()),
                    ensure_ascii=False,
                ),
                rerank_candidates=json.dumps(
                    _candidate_rows(result.rerank_candidates if result is not None else ()),
                    ensure_ascii=False,
                ),
                final_context=json.dumps(
                    [
                        {
                            "chunk_id": chunk.chunk_id,
                            "document_version_id": chunk.document_version_id,
                            "rank": chunk.fused_rank,
                            "score": chunk.rerank_score,
                        }
                        for chunk in (result.chunks if result is not None else ())
                    ],
                    ensure_ascii=False,
                ),
                stage_latency_ms=json.dumps(latency),
                degraded=bool(
                    degraded
                    or (result is not None and result.degraded)
                    or (
                        gateway_instance is not None
                        and any(audit.degraded for audit in gateway_instance.audits)
                    )
                ),
                error_code=error_code,
                model=json.dumps(
                    {
                        "status": "failed",
                        "provider_id": resolved_provider.provider_id,
                        "model_id": resolved_provider.model_id,
                        "route": resolved_provider.provider_type,
                        "external": True,
                        "policy": policy.reason_code if policy is not None else None,
                        "policy_version": (
                            policy.policy_version if policy is not None else None
                        ),
                        "classification": (
                            classification.value
                            if classification is not None
                            else DataClassification.INTERNAL.value
                        ),
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost_micros": 0,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        chat.version += 1
        session.commit()

    if body.stream:
        assistant_message = Message(
            id=new_ulid(),
            chat_id=chat.id,
            role="assistant",
            content="",
            status="generating",
            trace_id=None,
            citation_ids="[]",
        )
        session.add(assistant_message)
        chat.version += 1
        session.commit()
        return _stream_answer_response(
            request,
            team_id=body.team_id,
            user_id=user.id,
            chat_id=chat.id,
            question=question,
            history=history,
            knowledge_base_ids=knowledge_base_ids,
            decision=policy,
            resolved_provider=resolved_provider,
            product=body.filters.product,
            version_values=body.filters.version_values,
            generation_id=generation.id,
            engine_mode=engine_mode,
            explicit_document_grants=explicit_document_grants,
            message_id=assistant_message.id,
            policy_latency_ms=stage_latency["policy_ms"],
            facet_catalog=facet_catalog,
        )

    gateway = None
    rewrite = None
    result = None
    classification = DataClassification.INTERNAL

    try:
        gateway = _build_gateway(request, policy, resolved_provider)

        started = time.perf_counter()
        rewrite = await asyncio.to_thread(
            gateway.rewrite,
            question=question,
            history=history,
            product=body.filters.product,
            version_values=body.filters.version_values,
            allowed_products=tuple(facet_catalog["products"]),
            allowed_versions=tuple(facet_catalog["versions"]),
            allow_chat_history=policy.allow_chat_history,
            classification=DataClassification.INTERNAL,
        )
        stage_latency["rewrite_ms"] = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        vectors = await asyncio.to_thread(
            gateway.embed,
            [rewrite.rewritten_query],
            classification=DataClassification.INTERNAL,
        )
        stage_latency["embedding_ms"] = (time.perf_counter() - started) * 1000.0
        if not vectors:
            raise RuntimeError("embedding provider returned no vectors")

        started = time.perf_counter()
        applied_product = rewrite.applied_filters.get("product")
        applied_versions = tuple(
            rewrite.applied_filters.get("version_values") or ()
        )
        try:
            retriever = build_retriever(
                request.app.state.settings,
                generation.id,
                engine_mode,
            )
            result = await retriever.search(
                SearchRequest(
                    query=question,
                    rewritten_query=rewrite.rewritten_query,
                    query_vector=vectors[0],
                    filters=RetrievalFilters(
                        team_id=body.team_id,
                        knowledge_base_ids=tuple(knowledge_base_ids),
                        viewer_user_id=user.id,
                        product=applied_product,
                        version_values=applied_versions,
                        explicit_document_grants=explicit_document_grants,
                    ),
                    final_top_n=10,
                )
            )
        finally:
            stage_latency["retrieval_ms"] = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        rerank_input = list(result.rrf_candidates or result.chunks)
        classification = _classification_for_chunks(session, rerank_input)
        reranked = await asyncio.to_thread(
            gateway.rerank,
            rewrite.rewritten_query,
            rerank_input,
            top_n=10,
            classification=classification,
        )
        stage_latency["rerank_ms"] = (time.perf_counter() - started) * 1000.0
        context_chunks = reranked[:8]
        context_chunks = _hydrate_source_locators(session, context_chunks)
        started = time.perf_counter()
        answer = await asyncio.to_thread(
            gateway.generate,
            question=rewrite.rewritten_query,
            chunks=context_chunks,
            classification=classification,
            max_chunks=8,
        )
        stage_latency["generation_ms"] = (time.perf_counter() - started) * 1000.0
        chunk_by_id = {chunk.chunk_id: chunk for chunk in context_chunks}
        citation_chunks = [
            chunk_by_id[chunk_id]
            for chunk_id in answer.citation_chunk_ids
            if chunk_id in chunk_by_id
        ]
        if answer.status == "completed" and not citation_chunks:
            if context_chunks:
                answer = replace(
                    answer,
                    status="refused",
                    citation_chunk_ids=(),
                    refusal_reason="INSUFFICIENT_EVIDENCE",
                    degraded=True,
                )
            else:
                answer = replace(
                    answer,
                    text="知识库中没有足够依据。",
                    status="refused",
                    citation_chunk_ids=(),
                    refusal_reason="INSUFFICIENT_EVIDENCE",
                )
        citations = _citation_rows(citation_chunks, context_chunks)
        gateway_latency = {
            "gateway_{0}_ms".format(audit.purpose): float(audit.latency_ms)
            for audit in gateway.audits
        }
        degraded = (
            result.degraded
            or answer.degraded
            or any(audit.degraded for audit in gateway.audits)
        )
        result = replace(
            result,
            chunks=citation_chunks,
            rerank_candidates=tuple(reranked),
            stage_latency={
                **result.stage_latency,
                **gateway_latency,
            },
            degraded=degraded,
        )
    except PolicyDeniedError as error:
        session.rollback()
        persist_failure_trace(
            "POLICY_DENIED",
            result=result,
            rewrite=rewrite,
            policy=policy,
            gateway_instance=gateway,
            classification=classification,
        )
        raise ApiError(403, "POLICY_DENIED", str(error)) from error
    except ModelUnavailableError as error:
        session.rollback()
        persist_failure_trace(
            "MODEL_UNAVAILABLE",
            result=result,
            rewrite=rewrite,
            policy=policy,
            gateway_instance=gateway,
            classification=classification,
        )
        raise ApiError(503, "MODEL_UNAVAILABLE", str(error)) from error
    except ProviderAdapterError as error:
        session.rollback()
        persist_failure_trace(
            error.code,
            result=result,
            rewrite=rewrite,
            policy=policy,
            gateway_instance=gateway,
            classification=classification,
        )
        raise ApiError(error.status_code, error.code, str(error)) from error
    except ApiError as error:
        session.rollback()
        persist_failure_trace(
            error.code,
            result=result,
            rewrite=rewrite,
            policy=policy,
            gateway_instance=gateway,
            classification=classification,
        )
        raise
    except Exception as error:
        session.rollback()
        persist_failure_trace(
            "RETRIEVAL_UNAVAILABLE",
            result=result,
            rewrite=rewrite,
            policy=policy,
            gateway_instance=gateway,
            classification=classification,
        )
        raise ApiError(
            503,
            "RETRIEVAL_UNAVAILABLE",
            "The retrieval stack is not available.",
        ) from error

    status = answer.status
    refusal_reason = answer.refusal_reason

    assistant_message = Message(
        id=new_ulid(),
        chat_id=chat.id,
        role="assistant",
        content=answer.text,
        status=status,
        trace_id=result.trace_id,
        citation_ids=json.dumps(citations, ensure_ascii=False),
        refusal_reason=refusal_reason,
    )
    session.add(assistant_message)
    trace_product, trace_versions = _applied_filter_values(
        rewrite,
        body.filters.product,
        body.filters.version_values,
    )
    session.add(
        TraceRecord(
            team_id=body.team_id,
            chat_id=chat.id,
            message_id=assistant_message.id,
            trace_id=result.trace_id,
            engine_mode=engine_mode.value,
            original_query=question,
            rewritten_query=rewrite.rewritten_query,
            rewrite=_rewrite_json(rewrite),
            filters=json.dumps(
                {
                    "team_id": body.team_id,
                    "knowledge_base_ids": knowledge_base_ids,
                    "viewer_user_id": user.id,
                    "product": trace_product,
                    "version_values": list(trace_versions),
                    "explicit_document_grant_count": len(explicit_document_grants),
                }
            ),
            bm25_candidates=json.dumps(
                _candidate_rows(result.bm25_candidates),
                ensure_ascii=False,
            ),
            dense_candidates=json.dumps(
                _candidate_rows(result.dense_candidates),
                ensure_ascii=False,
            ),
            rrf_candidates=json.dumps(
                _candidate_rows(result.rrf_candidates),
                ensure_ascii=False,
            ),
            rerank_candidates=json.dumps(
                _candidate_rows(result.rerank_candidates),
                ensure_ascii=False,
            ),
            final_context=json.dumps(
                [
                    {
                        "chunk_id": chunk.chunk_id,
                        "document_version_id": chunk.document_version_id,
                        "rank": chunk.fused_rank,
                        "score": chunk.rerank_score,
                    }
                    for chunk in result.chunks
                ],
                ensure_ascii=False,
            ),
            stage_latency_ms=json.dumps(result.stage_latency),
            degraded=result.degraded,
            model=json.dumps(
                {
                    "provider_id": resolved_provider.provider_id,
                    "model_id": answer.model_id,
                    "route": answer.route,
                    "external": any(
                        audit.external and audit.purpose == "answer"
                        for audit in gateway.audits
                    ),
                    "policy": policy.reason_code,
                    "policy_version": policy.policy_version,
                    "classification": classification.value,
                    "degraded": answer.degraded,
                    "input_tokens": answer.input_tokens,
                    "output_tokens": answer.output_tokens,
                    "cost_micros": answer.cost_micros,
                    "reranker": "bge-reranker-v2-m3",
                }
            ),
        )
    )
    _persist_model_calls(
        session,
        body.team_id,
        request.state.request_id,
        gateway.audits,
    )
    chat.version += 1
    session.commit()

    payload = {
        "message_id": assistant_message.id,
        "chat_id": chat.id,
        "content": answer.text,
        "citations": citations,
        "trace_id": result.trace_id,
        "status": status,
        "refusal_reason": refusal_reason,
        "degraded": result.degraded,
        "rewrite": {
            "original": rewrite.original_query,
            "rewritten": rewrite.rewritten_query,
        },
        "model": {
            "model_id": answer.model_id,
            "route": answer.route,
            "policy": policy.reason_code,
            "policy_version": policy.policy_version,
            "classification": classification.value,
        },
    }
    return envelope(payload, request.state.request_id)


@router.post("/chats/update")
def update_chat(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    chat_id = body.get("chat_id", "")
    requested_title = body.get("title")
    if not isinstance(requested_title, str) or not requested_title.strip():
        raise ApiError(400, "INVALID_ARGUMENT", "Title is required.")
    title = requested_title.strip()
    _membership_or_error(session, team_id, user.id)
    chat = _chat_owner_or_error(session, team_id, chat_id, user.id)
    expected = _if_match_version(request)
    if chat.version != expected:
        raise ApiError(409, "VERSION_CONFLICT", "Resource version has changed.")
    chat.title = title[:200]
    chat.version += 1
    session.commit()
    return envelope(_chat_view(chat), request.state.request_id)


@router.get("/messages/detail")
def get_message(
    request: Request,
    team_id: str,
    message_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    message = _message_or_error(session, team_id, message_id, user.id)
    return envelope(_message_view(message), request.state.request_id)


@router.get("/messages/citations")
def message_citations(
    request: Request,
    team_id: str,
    message_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    message = _message_or_error(session, team_id, message_id, user.id)
    citations = _normalize_citations(json.loads(message.citation_ids or "[]"))
    return envelope(citations, request.state.request_id)


@router.post("/messages/cancel", status_code=202)
def cancel_message(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    message_id = body.get("message_id", "")
    _membership_or_error(session, team_id, user.id)
    message = _message_or_error(session, team_id, message_id, user.id)
    if message.status != "generating":
        raise ApiError(409, "RESOURCE_STATE_CONFLICT", "Message is already finished.")
    message.status = "cancelled"
    session.commit()
    return envelope({"message_id": message.id, "status": message.status}, request.state.request_id)


@router.post("/messages/feedback", status_code=201)
def submit_feedback(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    message_id = body.get("message_id", "")
    feedback_type = body.get("feedback_type", "")
    if feedback_type not in {
        "useful",
        "not_useful",
        "citation_error",
        "knowledge_gap",
    }:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid feedback type.")
    _membership_or_error(session, team_id, user.id)
    _message_or_error(session, team_id, message_id, user.id)
    feedback = Feedback(
        team_id=team_id,
        message_id=message_id,
        user_id=user.id,
        feedback_type=feedback_type,
        comment=body.get("comment"),
    )
    session.add(feedback)
    session.commit()
    return envelope(
        {"id": feedback.id, "message_id": message_id, "feedback_type": feedback_type},
        request.state.request_id,
    )
