from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import EvaluationDataset, EvaluationRun, User

router = APIRouter(tags=["evals"])


@router.get("/evals/datasets")
def list_datasets(request: Request, team_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    datasets = session.scalars(select(EvaluationDataset).where(EvaluationDataset.team_id == team_id, EvaluationDataset.status == "active").order_by(EvaluationDataset.created_at.desc()).limit(100)).all()
    return page_envelope([{ "id": d.id, "name": d.name, "description": d.description, "case_count": d.case_count, "version": d.version, "created_at": d.created_at.isoformat() } for d in datasets], request.state.request_id)


@router.post("/evals/datasets/create", status_code=201)
def create_dataset(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    ds = EvaluationDataset(team_id=team_id, name=body.get("name", "").strip(), description=body.get("description"), created_by=user.id)
    session.add(ds)
    session.commit()
    return envelope({ "id": ds.id, "name": ds.name, "case_count": 0, "version": 1, "created_at": ds.created_at.isoformat() }, request.state.request_id)


@router.get("/evals/runs")
def list_runs(request: Request, team_id: str, dataset_id: str = "", user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    query = select(EvaluationRun).join(EvaluationDataset).where(EvaluationDataset.team_id == team_id)
    if dataset_id: query = query.where(EvaluationRun.dataset_id == dataset_id)
    runs = session.scalars(query.order_by(EvaluationRun.created_at.desc()).limit(100)).all()
    return page_envelope([{ "id": r.id, "dataset_id": r.dataset_id, "engine_mode": r.engine_mode, "status": r.status, "baseline_run_id": r.baseline_run_id, "created_at": r.created_at.isoformat() } for r in runs], request.state.request_id)


@router.post("/evals/runs/start", status_code=202)
def start_run(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    run = EvaluationRun(dataset_id=body.get("dataset_id", ""), engine_mode=body.get("engine_mode", "dual_engine"), baseline_run_id=body.get("baseline_run_id"), created_by=user.id, status="running")
    session.add(run)
    session.commit()
    return envelope({ "id": run.id, "status": run.status }, request.state.request_id)


@router.get("/evals/runs/detail")
def get_run(request: Request, team_id: str, run_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    run = session.get(EvaluationRun, run_id)
    if run is None: raise ApiError(404, "NOT_FOUND", "Run not found.")
    return envelope({ "id": run.id, "dataset_id": run.dataset_id, "engine_mode": run.engine_mode, "status": run.status, "baseline_run_id": run.baseline_run_id, "created_at": run.created_at.isoformat() }, request.state.request_id)
