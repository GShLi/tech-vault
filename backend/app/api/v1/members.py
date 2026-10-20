from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import paginate_rows
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import AuditLog, ChunkRecord, Document, KnowledgeBase, TeamMember, User
from backend.app.modules.audit.service import write_audit

router = APIRouter(tags=["members"])


def _active_leader_count(
    session: Session, team_id: str, *, exclude_user_id: Optional[str] = None
) -> int:
    query = (
        select(func.count())
        .select_from(TeamMember)
        .join(User, User.id == TeamMember.user_id)
        .where(
            TeamMember.team_id == team_id,
            TeamMember.role == "leader",
            TeamMember.status == "active",
            User.is_active.is_(True),
        )
    )
    if exclude_user_id is not None:
        query = query.where(TeamMember.user_id != exclude_user_id)
    return int(session.scalar(query) or 0)


def ensure_user_can_be_disabled(session: Session, user_id: str) -> None:
    memberships = session.scalars(
        select(TeamMember).where(
            TeamMember.user_id == user_id,
            TeamMember.role == "leader",
            TeamMember.status == "active",
        )
    ).all()
    for membership in memberships:
        if _active_leader_count(
            session,
            membership.team_id,
            exclude_user_id=user_id,
        ) == 0:
            raise ApiError(
                409,
                "RESOURCE_STATE_CONFLICT",
                "A team must retain at least one active leader.",
            )


def ensure_not_last_active_leader(
    session: Session,
    member: TeamMember,
    *,
    next_role: Optional[str] = None,
    next_status: Optional[str] = None,
) -> None:
    if member.role != "leader" or member.status != "active":
        return
    resulting_role = member.role if next_role is None else next_role
    resulting_status = member.status if next_status is None else next_status
    if resulting_role == "leader" and resulting_status == "active":
        return
    if _active_leader_count(
        session, member.team_id, exclude_user_id=member.user_id
    ) == 0:
        raise ApiError(
            409,
            "RESOURCE_STATE_CONFLICT",
            "A team must retain at least one active leader.",
        )


@router.get("/members")
def list_members(
    request: Request,
    team_id: str,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    query = (
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team_id)
    )
    return paginate_rows(
        session,
        query,
        timestamp_column=TeamMember.joined_at,
        id_column=TeamMember.user_id,
        cursor=cursor,
        limit=limit,
        request_id=request.state.request_id,
        view=lambda row: {
            "team_id": row[0].team_id,
            "user_id": row[0].user_id,
            "role": row[0].role,
            "status": row[0].status,
            "email": row[1].email,
            "display_name": row[1].display_name,
            "joined_at": row[0].joined_at.isoformat(),
        },
    )


@router.post("/members/update")
def update_member(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _leader_or_error(session, body.get("team_id", ""), user.id)
    target_user_id = body.get("user_id", "")
    target = session.get(User, target_user_id)
    if target is not None and target.is_builtin:
        raise ApiError(
            403,
            "PROTECTED_ACCOUNT",
            "The built-in administrator cannot be modified.",
        )
    member = session.get(TeamMember, (body.get("team_id", ""), target_user_id))
    if member is None:
        raise ApiError(404, "NOT_FOUND", "Member not found.")
    before = {"role": member.role, "status": member.status}
    role = body.get("role")
    if role is not None and role not in {"leader", "member", "viewer"}:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid team role.")
    status = body.get("status")
    if status is not None and status not in {"active", "disabled"}:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid member status.")
    ensure_not_last_active_leader(
        session,
        member,
        next_role=role,
        next_status=status,
    )
    for field in ("role", "status"):
        value = body.get(field)
        if value is not None:
            setattr(member, field, value)
    write_audit(
        session,
        action="team.member.updated",
        actor_id=user.id,
        team_id=member.team_id,
        resource_type="team_member",
        resource_id=member.user_id,
        details={
            "before": before,
            "after": {"role": member.role, "status": member.status},
        },
    )
    session.commit()
    return envelope({"team_id": member.team_id, "user_id": member.user_id, "role": member.role, "status": member.status}, request.state.request_id)


@router.post("/members/remove")
def remove_member(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _leader_or_error(session, body.get("team_id", ""), user.id)
    target_user_id = body.get("user_id", "")
    target = session.get(User, target_user_id)
    if target is not None and target.is_builtin:
        raise ApiError(
            403,
            "PROTECTED_ACCOUNT",
            "The built-in administrator cannot be removed.",
        )
    member = session.get(TeamMember, (body.get("team_id", ""), target_user_id))
    if member is None:
        raise ApiError(404, "NOT_FOUND", "Member not found.")
    ensure_not_last_active_leader(session, member, next_status="removed")
    before = {"role": member.role, "status": member.status}
    member.status = "removed"
    write_audit(
        session,
        action="team.member.removed",
        actor_id=user.id,
        team_id=member.team_id,
        resource_type="team_member",
        resource_id=member.user_id,
        details={"before": before},
    )
    session.commit()
    return envelope({"removed": member.user_id}, request.state.request_id)


@router.post("/members/transfer-documents", status_code=202)
def transfer_documents(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    source_user_id = body.get("from_user_id", "")
    target_user_id = body.get("to_user_id", "")
    if not source_user_id or not target_user_id or source_user_id == target_user_id:
        raise ApiError(400, "INVALID_ARGUMENT", "Distinct source and target users are required.")

    source = session.get(TeamMember, (team_id, source_user_id))
    if source is None or source.status not in {"active", "removed"}:
        raise ApiError(404, "NOT_FOUND", "Source team member was not found.")
    target = session.get(TeamMember, (team_id, target_user_id))
    if target is None or target.status != "active":
        raise ApiError(404, "NOT_FOUND", "Target active team member was not found.")

    kb_ids = session.scalars(
        select(KnowledgeBase.id).where(KnowledgeBase.team_id == team_id)
    ).all()
    document_ids = session.scalars(
        select(Document.id).where(
            Document.knowledge_base_id.in_(kb_ids),
            Document.owner_user_id == source_user_id,
            Document.visibility == "private",
        )
    ).all()
    if document_ids:
        session.execute(
            update(Document)
            .where(Document.id.in_(document_ids))
            .values(owner_user_id=target_user_id)
        )
        chunk_result = session.execute(
            update(ChunkRecord)
            .where(
                ChunkRecord.team_id == team_id,
                ChunkRecord.document_id.in_(document_ids),
            )
            .values(owner_user_id=target_user_id)
        )
        transferred_chunks = chunk_result.rowcount
    else:
        transferred_chunks = 0

    session.add(
        AuditLog(
            team_id=team_id,
            actor_id=user.id,
            action="member.transfer_documents",
            resource_type="member",
            resource_id=target_user_id,
            details=(
                '{"from_user_id":"%s","to_user_id":"%s",'
                '"transferred_documents":%d,"transferred_chunks":%d}'
            )
            % (
                source_user_id,
                target_user_id,
                len(document_ids),
                transferred_chunks,
            ),
        )
    )
    session.commit()
    return envelope(
        {
            "from_user_id": source_user_id,
            "to_user_id": target_user_id,
            "transferred_documents": len(document_ids),
            "transferred_chunks": transferred_chunks,
        },
        request.state.request_id,
    )
