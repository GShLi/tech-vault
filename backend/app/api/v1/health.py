from fastapi import APIRouter, Request

from backend.app.api.envelope import envelope


router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request):
    return envelope({"status": "ok"}, request.state.request_id)


@router.get("/ready")
def ready(request: Request):
    return envelope({"status": "ready"}, request.state.request_id)


@router.get("/version")
def version(request: Request):
    return envelope({"version": "0.1.0"}, request.state.request_id)
