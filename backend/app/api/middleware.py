from starlette.middleware.base import BaseHTTPMiddleware

from backend.app.core.ids import new_ulid


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-Id") or "req_" + new_ulid()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
