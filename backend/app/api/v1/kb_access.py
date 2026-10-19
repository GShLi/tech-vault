from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError
from backend.app.db.models import KnowledgeBase, KnowledgeBaseMember


def knowledge_base_member_ids(session: Session, team_id: str, user_id: str):
    return select(KnowledgeBaseMember.kb_id).join(
        KnowledgeBase,
        KnowledgeBase.id == KnowledgeBaseMember.kb_id,
    ).where(
        KnowledgeBase.team_id == team_id,
        KnowledgeBase.status == "active",
        KnowledgeBaseMember.user_id == user_id,
        KnowledgeBaseMember.status == "active",
    )


def knowledge_base_or_error(
    session: Session,
    team_id: str,
    kb_id: str,
    user_id: str,
) -> KnowledgeBase:
    knowledge_base = session.get(KnowledgeBase, kb_id)
    if (
        knowledge_base is None
        or knowledge_base.team_id != team_id
        or knowledge_base.status != "active"
    ):
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    membership = session.get(KnowledgeBaseMember, (kb_id, user_id))
    if membership is None or membership.status != "active":
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    return knowledge_base
