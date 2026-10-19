import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.teams import _leader_or_error, _membership_or_error
from backend.app.db.models import (
    EvaluationCase,
    EvaluationDataset,
    EvaluationResult,
    EvaluationRun,
    User,
)

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


def _dataset_or_error(session: Session, team_id: str, dataset_id: str) -> EvaluationDataset:
    dataset = session.get(EvaluationDataset, dataset_id)
    if dataset is None or dataset.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Dataset was not found.")
    return dataset


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
    session.commit()
    return envelope({"id": dataset.id, "name": dataset.name, "version": dataset.version}, request.state.request_id)


@router.post("/evals/datasets/archive")
def archive_dataset(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    dataset = _dataset_or_error(session, team_id, body.get("dataset_id", ""))
    dataset.status = "archived"
    dataset.version += 1
    session.commit()
    return envelope({"id": dataset.id, "status": dataset.status}, request.state.request_id)


@router.get("/evals/datasets/cases")
def list_cases(request: Request, team_id: str, dataset_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    _dataset_or_error(session, team_id, dataset_id)
    cases = session.scalars(select(EvaluationCase).where(EvaluationCase.dataset_id == dataset_id).order_by(EvaluationCase.created_at.asc()).limit(500)).all()
    return envelope([_case_view(case) for case in cases], request.state.request_id)


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
    dataset.case_count += 1
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
    session.commit()
    return envelope({"imported": len(created)}, request.state.request_id)


@router.get("/evals/runs/events")
def run_events(request: Request, team_id: str, run_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise ApiError(404, "NOT_FOUND", "Run was not found.")
    payload = {"run_id": run.id, "status": run.status}
    async def events():
        yield "event: progress\ndata: {0}\n\n".format(json.dumps(payload))
        yield "event: completed\ndata: {0}\n\n".format(json.dumps(payload))
    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/evals/runs/cancel", status_code=202)
def cancel_run(body: dict, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    team_id = body.get("team_id", "")
    _leader_or_error(session, team_id, user.id)
    run = session.get(EvaluationRun, body.get("run_id", ""))
    if run is None:
        raise ApiError(404, "NOT_FOUND", "Run was not found.")
    run.status = "cancelled"
    session.commit()
    return envelope({"id": run.id, "status": run.status}, request.state.request_id)


@router.get("/evals/runs/report")
def run_report(request: Request, team_id: str, run_id: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _membership_or_error(session, team_id, user.id)
    run = session.get(EvaluationRun, run_id)
    if run is None:
        raise ApiError(404, "NOT_FOUND", "Run was not found.")
    result = session.scalar(select(EvaluationResult).where(EvaluationResult.run_id == run_id))
    return envelope(
        {
            "run_id": run.id,
            "status": run.status,
            "metrics": json.loads(result.metrics or "{}") if result else {},
            "report": json.loads(result.report or "{}") if result else {},
        },
        request.state.request_id,
    )
