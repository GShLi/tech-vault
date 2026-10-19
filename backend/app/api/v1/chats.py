import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.v1.schemas import AskRequest, ChatView, MessageView
from backend.app.api.v1.teams import _membership_or_error, _if_match_version
from backend.app.core.ids import new_ulid
from backend.app.db.models import Chat, Message, User
from backend.app.rag.domain.models import RetrievalFilters, SearchRequest
from backend.app.rag.embedding.service import EmbeddingClient
from backend.app.rag.retrieval.config import EngineMode
from backend.app.rag.retrieval.factory import build_retriever


router = APIRouter(tags=["chats"])


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
    return MessageView(
        id=msg.id,
        chat_id=msg.chat_id,
        role=msg.role,
        content=msg.content,
        status=msg.status,
        trace_id=msg.trace_id,
        citation_ids=json.loads(msg.citation_ids) if msg.citation_ids else [],
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
    chat = Chat(
        team_id=team_id,
        user_id=user.id,
        title=body.get("title", "新对话").strip()[:200],
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
    session.execute(delete(Message).where(Message.chat_id == chat_id))
    session.delete(chat)
    session.commit()
    return envelope({"deleted": chat_id}, request.state.request_id)


@router.get("/chats/messages")
def list_messages(
    request: Request,
    team_id: str,
    chat_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    _chat_owner_or_error(session, team_id, chat_id, user.id)
    messages = session.scalars(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.asc())
    ).all()
    return envelope([_message_view(m) for m in messages], request.state.request_id)


def _compose_answer(chunks) -> str:
    lines = ["根据知识库检索结果："]
    for index, chunk in enumerate(chunks, start=1):
        lines.append("[{0}] {1}".format(index, chunk.content.strip()))
    return "\n\n".join(lines)


@router.post("/chats/ask")
async def ask(
    body: AskRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, body.team_id, user.id)
    chat = _chat_owner_or_error(session, body.team_id, body.chat_id, user.id)
    knowledge_base_ids = body.knowledge_base_ids or json.loads(
        chat.knowledge_base_ids or "[]"
    )
    if not knowledge_base_ids:
        raise ApiError(400, "INVALID_ARGUMENT", "Select at least one knowledge base.")

    question = body.question.strip()
    user_message = Message(
        id=new_ulid(),
        chat_id=chat.id,
        role="user",
        content=question,
        status="completed",
    )
    session.add(user_message)

    try:
        embedder = EmbeddingClient(request.app.state.settings.embedding_url)
        vector = embedder.embed([question])[0]
        retriever = build_retriever(
            request.app.state.settings,
            "current",
            EngineMode.DUAL_ENGINE,
        )
        result = await retriever.search(
            SearchRequest(
                query=question,
                rewritten_query=None,
                query_vector=vector,
                filters=RetrievalFilters(
                    team_id=body.team_id,
                    knowledge_base_ids=tuple(knowledge_base_ids),
                    viewer_user_id=user.id,
                ),
                final_top_n=5,
            )
        )
    except Exception as error:
        session.rollback()
        raise ApiError(
            503,
            "RETRIEVAL_UNAVAILABLE",
            "The retrieval stack is not available.",
        ) from error

    if result.chunks:
        answer = _compose_answer(result.chunks)
        citations = [
            {
                "citation_id": "c{0}".format(index),
                "chunk_id": chunk.chunk_id,
                "document_version_id": chunk.document_version_id,
                "excerpt": chunk.content[:500],
                "source_locator": chunk.source_locator,
            }
            for index, chunk in enumerate(result.chunks, start=1)
        ]
        status = "completed"
        refusal_reason = None
    else:
        answer = "知识库中没有足够依据。"
        citations = []
        status = "refused"
        refusal_reason = "INSUFFICIENT_EVIDENCE"

    assistant_message = Message(
        id=new_ulid(),
        chat_id=chat.id,
        role="assistant",
        content=answer,
        status=status,
        trace_id=result.trace_id,
        citation_ids=json.dumps(citations, ensure_ascii=False),
        refusal_reason=refusal_reason,
    )
    session.add(assistant_message)
    chat.version += 1
    session.commit()

    payload = {
        "message_id": assistant_message.id,
        "chat_id": chat.id,
        "content": answer,
        "citations": citations,
        "trace_id": result.trace_id,
        "status": status,
        "refusal_reason": refusal_reason,
        "degraded": result.degraded,
    }
    if not body.stream:
        return envelope(payload, request.state.request_id)

    events = [
        (
            "meta",
            {
                "trace_id": result.trace_id,
                "message_id": assistant_message.id,
                "engine_mode": "dual_engine",
                "degraded": result.degraded,
            },
        ),
        (
            "answer",
            {
                "content": answer,
                "citations": citations,
                "status": status,
            },
        ),
        (
            "done",
            {
                "message_id": assistant_message.id,
                "status": status,
            },
        ),
    ]

    async def stream_events():
        for event, data in events:
            yield "event: {0}\ndata: {1}\n\n".format(
                event,
                json.dumps(data, ensure_ascii=False),
            )

    return StreamingResponse(stream_events(), media_type="text/event-stream")
