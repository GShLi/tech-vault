from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


_HTTP_ERROR_CODES = {
    401: "UNAUTHENTICATED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "RESOURCE_STATE_CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_FAILED",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.code,
                "message": error.message,
                "details": jsonable_encoder(error.details),
                "request_id": _request_id(request),
            }
        },
    )


def _http_error_code(status_code: int) -> str:
    if status_code in _HTTP_ERROR_CODES:
        return _HTTP_ERROR_CODES[status_code]
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return "INVALID_ARGUMENT"


def _http_error_message(detail: Any) -> str:
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return str(detail)


async def http_error_handler(
    request: Request, error: StarletteHTTPException
) -> JSONResponse:
    details = jsonable_encoder(error.detail) if isinstance(error.detail, dict) else {}
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": _http_error_code(error.status_code),
                "message": _http_error_message(error.detail),
                "details": details,
                "request_id": _request_id(request),
            }
        },
    )


async def validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            key: validation_error[key]
            for key in ("loc", "msg")
            if key in validation_error
        }
        for validation_error in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "Request validation failed.",
                "details": {"errors": jsonable_encoder(errors)},
                "request_id": _request_id(request),
            }
        },
    )
