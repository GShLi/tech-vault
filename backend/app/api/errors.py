from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


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
                "details": error.details,
                "request_id": _request_id(request),
            }
        },
    )


async def http_error_handler(
    request: Request, error: StarletteHTTPException
) -> JSONResponse:
    code = "NOT_FOUND" if error.status_code == 404 else "INVALID_ARGUMENT"
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": code,
                "message": str(error.detail),
                "details": {},
                "request_id": _request_id(request),
            }
        },
    )


async def validation_error_handler(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "Request validation failed.",
                "details": {"errors": jsonable_encoder(error.errors())},
                "request_id": _request_id(request),
            }
        },
    )
