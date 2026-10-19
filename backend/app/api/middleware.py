import logging
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.core.ids import new_ulid


logger = logging.getLogger(__name__)
_CLIENT_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        client_request_id = request.headers.get("X-Request-Id")
        if client_request_id and _CLIENT_REQUEST_ID.fullmatch(client_request_id):
            request_id = client_request_id
        else:
            request_id = "req_" + new_ulid()
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled API exception for request %s", request_id)
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Internal server error.",
                        "details": {},
                        "request_id": request_id,
                    }
                },
            )
        response.headers["X-Request-Id"] = request_id
        return response
