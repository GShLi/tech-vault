from fastapi import APIRouter

from backend.app.api.v1.audit import router as audit_router
from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.chats import router as chats_router
from backend.app.api.v1.chunks import router as chunks_router
from backend.app.api.v1.documents import router as documents_router
from backend.app.api.v1.evaluations import router as evals_router
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.invitations import router as invitations_router
from backend.app.api.v1.members import router as members_router
from backend.app.api.v1.kbs import router as kbs_router
from backend.app.api.v1.model_policy import router as policy_router
from backend.app.api.v1.teams import router as teams_router
from backend.app.api.v1.traces import router as traces_router
from backend.app.api.v1.upload_batches import router as upload_batches_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(teams_router)
api_router.include_router(kbs_router)
api_router.include_router(members_router)
api_router.include_router(invitations_router)
api_router.include_router(documents_router)
api_router.include_router(upload_batches_router)
api_router.include_router(chunks_router)
api_router.include_router(chats_router)
api_router.include_router(evals_router)
api_router.include_router(policy_router)
api_router.include_router(audit_router)
api_router.include_router(traces_router)
