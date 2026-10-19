from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
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
        return int(raw.strip())
    except ValueError as error:
        raise ApiError(400, "INVALID_ARGUMENT", "If-Match must be an integer.") from error


def _team_view(team: Team):
    return {
        "id": team.id,
        "name": team.name,
        "version": team.version,
        "created_at": team.created_at.isoformat(),
    }


@router.get("/teams")
def list_teams(
    request: Request,
    limit: int = 20,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    teams = session.scalars(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user.id, TeamMember.status == "active")
        .order_by(Team.created_at.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return page_envelope(
        [_team_view(team) for team in teams],
        request.state.request_id,
    )


@router.post("/teams/create", status_code=201)
def create_team(
    body: TeamCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    team = Team(name=body.name.strip(), created_by=user.id)
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
    return envelope(_team_view(team), request.state.request_id)


@router.get("/teams/detail")
def get_team(
    request: Request,
    team_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    team = session.get(Team, team_id)
    if team is None:
        raise ApiError(403, "PERMISSION_DENIED", "Team is not available.")
    return envelope(_team_view(team), request.state.request_id)


@router.post("/teams/update")
def update_team(
    body: TeamUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, body.team_id, user.id)
    expected_version = _if_match_version(request)
    result = session.execute(
        update(Team)
        .where(Team.id == body.team_id, Team.version == expected_version)
        .values(name=body.name, version=Team.version + 1)
    )
    if result.rowcount == 0:
        session.rollback()
        raise ApiError(409, "VERSION_CONFLICT", "Resource version has changed.")
    session.commit()

    team = session.get(Team, body.team_id)
    if team is None:
        raise ApiError(403, "PERMISSION_DENIED", "Team is not available.")
    session.refresh(team)
    return envelope(_team_view(team), request.state.request_id)
