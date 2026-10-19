from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import AuditLog, ChunkRecord, Document, KnowledgeBase, TeamMember, User

router = APIRouter(tags=["members"])


@router.get("/members")
def list_members(request: Request, team_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    rows = session.execute(
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team_id)
        .order_by(TeamMember.joined_at.desc())
    ).all()
    return page_envelope(
        [{"team_id": m.team_id, "user_id": m.user_id, "role": m.role, "status": m.status,
          "email": u.email, "display_name": u.display_name, "joined_at": m.joined_at.isoformat()} for m, u in rows],
        request.state.request_id,
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
    role = body.get("role")
    if role is not None and role not in {"leader", "member", "viewer"}:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid team role.")
    for field in ("role", "status"):
        value = body.get(field)
        if value is not None:
            setattr(member, field, value)
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
    member.status = "removed"
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
