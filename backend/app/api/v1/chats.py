import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.v1.schemas import ChatView, MessageView
from backend.app.api.v1.teams import _membership_or_error, _if_match_version
from backend.app.core.ids import new_ulid
from backend.app.db.models import Chat, Message, User


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


def _chat_owner_or_error(session: Session, chat_id: str, user_id: str) -> Chat:
    chat = session.get(Chat, chat_id)
    if chat is None or chat.user_id != user_id:
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
    chat = _chat_owner_or_error(session, chat_id, user.id)
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
    _chat_owner_or_error(session, chat_id, user.id)
    session.execute(select(Message).where(Message.chat_id == chat_id)).all()
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
    _chat_owner_or_error(session, chat_id, user.id)
    messages = session.scalars(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.asc())
    ).all()
    return envelope([_message_view(m) for m in messages], request.state.request_id)
