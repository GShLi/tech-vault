from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api.errors import (
    ApiError,
    api_error_handler,
    http_error_handler,
    validation_error_handler,
)
from backend.app.api.middleware import RequestIdMiddleware
from backend.app.api.v1.router import api_router
from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory, create_schema


def create_app(
    settings: Optional[Settings] = None,
    session_factory=None,
) -> FastAPI:
    effective_settings = settings or Settings.from_env()
    app = FastAPI(title="TechVault API", version="0.1.0")
    app.state.settings = effective_settings

    if session_factory is None:
        engine = build_engine(effective_settings.database_url)
        create_schema(engine)
        session_factory = build_session_factory(engine)
    app.state.session_factory = session_factory

    app.add_middleware(RequestIdMiddleware)
    app.include_router(api_router, prefix="/api/v1")
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    return app


app = create_app()
