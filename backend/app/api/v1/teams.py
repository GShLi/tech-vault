from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor
from backend.app.api.v1.schemas import TeamCreateRequest, TeamUpdateRequest
from backend.app.db.models import Team, TeamMember, User


router = APIRouter(tags=["teams"])


def _membership_or_error(
    session: Session,
    team_id: str,
    user_id: str,
) -> TeamMember:
    membership = session.get(TeamMember, (team_id, user_id))
    if membership is None or membership.status != "active":
        raise ApiError(
            403,
            "PERMISSION_DENIED",
            "You do not have permission to access this team.",
        )
    return membership


def _leader_or_error(session: Session, team_id: str, user_id: str) -> TeamMember:
    membership = _membership_or_error(session, team_id, user_id)
    if membership.role != "leader":
        raise ApiError(403, "PERMISSION_DENIED", "Team leader permission is required.")
    return membership


def _if_match_version(request: Request) -> int:
    raw = request.headers.get("If-Match")
    if raw is None:
        raise ApiError(400, "INVALID_ARGUMENT", "If-Match is required.")
    try:
        return int(raw.strip().strip('"'))
    except ValueError as error:
        raise ApiError(400, "INVALID_ARGUMENT", "If-Match must be an integer.") from error


def _team_view(team: Team, role: str):
    return {
        "id": team.id,
        "name": team.name,
        "description": team.description,
        "role": role,
        "version": team.version,
        "created_at": team.created_at.isoformat(),
        "updated_at": team.updated_at.isoformat(),
    }


@router.get("/teams")
def list_teams(
    request: Request,
    limit: int = 20,
    cursor: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    page_limit = max(1, min(limit, 100))
    query = (
        select(Team, TeamMember.role)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user.id, TeamMember.status == "active")
    )
    if cursor is not None:
        after_created, after_id = decode_cursor(cursor)
        query = query.where(
            or_(
                Team.created_at < after_created,
                and_(Team.created_at == after_created, Team.id < after_id),
            )
        )

    rows = session.execute(
        query.order_by(Team.created_at.desc(), Team.id.desc()).limit(page_limit + 1)
    ).all()
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    next_cursor = (
        encode_cursor(page_rows[-1][0].created_at, page_rows[-1][0].id)
        if has_more and page_rows
        else None
    )
    return page_envelope(
        [_team_view(team, role) for team, role in page_rows],
        request.state.request_id,
        next_cursor,
    )


@router.post("/teams/create", status_code=201)
def create_team(
    body: TeamCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team = Team(
        name=body.name.strip(),
        description=body.description,
        created_by=user.id,
    )
    session.add(team)
    session.flush()
    session.add(
        TeamMember(
            team_id=team.id,
            user_id=user.id,
            role="leader",
            status="active",
        )
    )
    session.commit()
    return envelope(_team_view(team, "leader"), request.state.request_id)


@router.get("/teams/detail")
def get_team(
    request: Request,
    team_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    membership = _membership_or_error(session, team_id, user.id)
    team = session.get(Team, team_id)
    if team is None:
        raise ApiError(403, "PERMISSION_DENIED", "Team is not available.")
    return envelope(_team_view(team, membership.role), request.state.request_id)


@router.post("/teams/update")
def update_team(
    body: TeamUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    membership = _leader_or_error(session, body.team_id, user.id)
    expected_version = _if_match_version(request)
    result = session.execute(
        update(Team)
        .where(Team.id == body.team_id, Team.version == expected_version)
        .values(
            name=body.name,
            description=body.description,
            version=Team.version + 1,
        )
    )
    if result.rowcount == 0:
        session.rollback()
        raise ApiError(409, "VERSION_CONFLICT", "Resource version has changed.")
    session.commit()

    team = session.get(Team, body.team_id)
    if team is None:
        raise ApiError(403, "PERMISSION_DENIED", "Team is not available.")
    session.refresh(team)
    return envelope(_team_view(team, membership.role), request.state.request_id)
