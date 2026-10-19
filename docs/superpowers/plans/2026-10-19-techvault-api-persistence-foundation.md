# TechVault P0 API and Persistence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a runnable FastAPI service with a standardized response envelope, request IDs, authentication, team and knowledge-base APIs, and SQLAlchemy persistence covered by contract tests.

**Architecture:** A FastAPI app factory owns settings and a SQLAlchemy session factory. Thin routers delegate to small auth and team-scope helpers. Tests use an in-memory SQLite database and FastAPI's TestClient, so the first API slice runs without external infrastructure.

**Tech Stack:** Python 3.9-compatible runtime, FastAPI, Pydantic v2, SQLAlchemy 2.0, PyJWT, stdlib `hashlib.scrypt`, pytest, httpx.

**Spec:** `TechVault 典阁 — 团队私有技术知识库 RAG 系统.md`

## Global Constraints

- All business endpoints live under `/api/v1`.
- API paths contain no `{team_id}` or `{document_id}` path parameters.
- Read endpoints use GET with limited query parameters; mutations use POST with JSON bodies.
- Roles are exactly `admin | leader | member | viewer`.
- `admin` and `leader` do not automatically read another member's private document.
- No `tenant_id` or tenant concept exists now or later.
- Team scope and knowledge-base scope are checked server-side on every request.
- JSON fields use `snake_case`; IDs are ULID strings; timestamps are UTC.
- Success responses use `{data, meta}`; errors use `{error: {code, message, details, request_id}}`.
- Editable team and knowledge-base resources use `If-Match` and an integer `version`.
- Never return password hashes, JWT secrets, provider keys, or internal paths.
- Default external model policy remains `local_only`; this plan does not add external model calls.

### Task 1: Runtime Primitives

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/core/ids.py`
- Create: `backend/app/core/passwords.py`
- Create: `backend/app/core/tokens.py`
- Test: `backend/tests/core/test_ids.py`
- Test: `backend/tests/core/test_passwords.py`
- Test: `backend/tests/core/test_tokens.py`

**Interfaces:**
- Produces: `Settings`, `Settings.from_env()`.
- Produces: `new_ulid(now_ms=None) -> str`, `is_valid_ulid(value) -> bool`.
- Produces: `hash_password(password) -> str`, `verify_password(password, encoded) -> bool`.
- Produces: `TokenError`, `create_access_token(user_id, settings, now=None) -> str`, `decode_access_token(token, settings) -> str`.

- [x] **Step 1: Add API dependencies**

Change the `api` extra in `pyproject.toml` to:

```toml
api = [
  "fastapi>=0.115",
  "pydantic>=2.7",
  "sqlalchemy>=2.0",
  "uvicorn[standard]>=0.30",
  "PyJWT>=2.9",
  "httpx>=0.27",
]
```

Install with:

```bash
python -m pip install -e ".[test,api]"
```

- [x] **Step 2: Write failing primitive tests**

Create `backend/tests/core/test_ids.py`:

```python
from backend.app.core.ids import is_valid_ulid, new_ulid


def test_new_ulid_is_canonical_and_time_sortable():
    earlier = new_ulid(now_ms=1000)
    later = new_ulid(now_ms=2000)

    assert len(earlier) == 26
    assert is_valid_ulid(earlier)
    assert earlier < later


def test_is_valid_ulid_rejects_bad_values():
    assert not is_valid_ulid("")
    assert not is_valid_ulid("0" * 25)
    assert not is_valid_ulid("I" * 26)
```

Create `backend/tests/core/test_passwords.py`:

```python
from backend.app.core.passwords import hash_password, verify_password


def test_password_hash_round_trips_without_storing_plaintext():
    encoded = hash_password("correct horse battery staple")

    assert "correct horse battery staple" not in encoded
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_malformed_password_hash_is_rejected():
    assert not verify_password("anything", "not-a-valid-hash")
```

Create `backend/tests/core/test_tokens.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.core.config import Settings
from backend.app.core.tokens import TokenError, create_access_token, decode_access_token


def test_access_token_round_trips_subject():
    settings = Settings(jwt_secret="test-secret", access_token_ttl_seconds=60)
    token = create_access_token("user-1", settings)

    assert decode_access_token(token, settings) == "user-1"


def test_expired_access_token_is_rejected():
    settings = Settings(jwt_secret="test-secret", access_token_ttl_seconds=60)
    issued_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = create_access_token("user-1", settings, now=issued_at)

    with pytest.raises(TokenError):
        decode_access_token(token, settings)


def test_wrong_secret_is_rejected():
    issued = Settings(jwt_secret="first-secret")
    verifier = Settings(jwt_secret="second-secret")
    token = create_access_token("user-1", issued)

    with pytest.raises(TokenError):
        decode_access_token(token, verifier)
```

- [x] **Step 3: Run the tests and verify failure**

Run:

```bash
pytest backend/tests/core/test_ids.py backend/tests/core/test_passwords.py backend/tests/core/test_tokens.py -q
```

Expected: import failures because the modules do not exist.

- [x] **Step 4: Implement configuration**

Replace `backend/app/core/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


_DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./data/techvault.db"
_DEFAULT_JWT_SECRET = "dev-only-change-me"
_DEFAULT_JWT_ALGORITHM = "HS256"
_DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 900
_DEFAULT_ENVIRONMENT = "development"


@dataclass(frozen=True)
class Settings:
    database_url: str = _DEFAULT_DATABASE_URL
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = _DEFAULT_JWT_ALGORITHM
    access_token_ttl_seconds: int = _DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    environment: str = _DEFAULT_ENVIRONMENT

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("TECHVAULT_DATABASE_URL", _DEFAULT_DATABASE_URL),
            jwt_secret=os.getenv("TECHVAULT_JWT_SECRET", _DEFAULT_JWT_SECRET),
            jwt_algorithm=os.getenv(
                "TECHVAULT_JWT_ALGORITHM", _DEFAULT_JWT_ALGORITHM
            ),
            access_token_ttl_seconds=int(
                os.getenv(
                    "TECHVAULT_ACCESS_TOKEN_TTL_SECONDS",
                    str(_DEFAULT_ACCESS_TOKEN_TTL_SECONDS),
                )
            ),
            environment=os.getenv("TECHVAULT_ENVIRONMENT", _DEFAULT_ENVIRONMENT),
        )
```

- [x] **Step 5: Implement ULID generation**

Create `backend/app/core/ids.py`:

```python
import os
import time
from typing import Optional


_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid(now_ms: Optional[int] = None) -> str:
    timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if timestamp < 0 or timestamp >= (1 << 48):
        raise ValueError("timestamp is outside the ULID range")
    randomness = int.from_bytes(os.urandom(10), "big")
    return _encode(timestamp, 10) + _encode(randomness, 16)


def is_valid_ulid(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 26
        and all(character in _ALPHABET for character in value)
    )
```

- [x] **Step 6: Implement password hashing**

Create `backend/app/core/passwords.py`:

```python
import base64
import hashlib
import hmac
import os


_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DKLEN,
    )
    return "scrypt${0}${1}${2}${3}${4}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_value, digest_value = encoded.split(
            "$"
        )
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_value),
            r=int(r_value),
            p=int(p_value),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError):
        return False
```

- [x] **Step 7: Implement access tokens**

Create `backend/app/core/tokens.py`:

```python
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from backend.app.core.config import Settings


class TokenError(Exception):
    pass


def create_access_token(
    user_id: str,
    settings: Settings,
    now: Optional[datetime] = None,
) -> str:
    issued_at = now or datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(
            (issued_at + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()
        ),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as error:
        raise TokenError("invalid or expired token") from error

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise TokenError("token subject is missing")
    return subject
```

- [x] **Step 8: Run focused and full tests**

Run:

```bash
pytest backend/tests/core/test_ids.py backend/tests/core/test_passwords.py backend/tests/core/test_tokens.py -q
pytest -q
```

Expected: focused tests pass; full suite passes.

- [x] **Step 9: Commit**

```bash
git add pyproject.toml backend/app/core backend/tests/core
git commit -m "feat: add API runtime primitives"
```

### Task 2: SQLAlchemy Persistence Foundation

**Files:**
- Create: `backend/app/db/base.py`
- Modify: `backend/app/db/models.py`
- Create: `backend/app/db/session.py`
- Test: `backend/tests/db/test_models.py`
- Test: `backend/tests/db/test_session.py`

**Interfaces:**
- Produces: `Base`, `User`, `Team`, `TeamMember`, `KnowledgeBase`.
- Produces: `build_engine(database_url) -> Engine`, `build_session_factory(engine)`, `create_schema(engine) -> None`.
- Consumes: `new_ulid`, `utc_now`.

- [x] **Step 1: Write failing persistence tests**

Create `backend/tests/db/test_models.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.db.models import KnowledgeBase, Team, TeamMember, User


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_models_store_team_membership_and_knowledge_base():
    with _session() as session:
        user = User(
            email="leader@example.com",
            display_name="Leader",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        team = Team(name="Platform", created_by=user.id)
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
        session.add(
            KnowledgeBase(
                team_id=team.id,
                name="Java",
                created_by=user.id,
            )
        )
        session.commit()

        assert session.get(User, user.id).email == "leader@example.com"
        assert session.get(Team, team.id).name == "Platform"
        assert session.get(TeamMember, (team.id, user.id)).role == "leader"
        assert session.query(KnowledgeBase).one().name == "Java"


def test_user_email_is_unique():
    with _session() as session:
        session.add(
            User(email="same@example.com", display_name="A", password_hash="hash")
        )
        session.commit()
        session.add(
            User(email="same@example.com", display_name="B", password_hash="hash")
        )

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate email should have failed")
```

Create `backend/tests/db/test_session.py`:

```python
from sqlalchemy import text

from backend.app.db.models import User
from backend.app.db.session import build_engine, build_session_factory, create_schema


def test_in_memory_session_factory_survives_across_sessions():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    factory = build_session_factory(engine)

    with factory() as session:
        session.add(
            User(email="a@example.com", display_name="A", password_hash="hash")
        )
        session.commit()

    with factory() as session:
        assert session.query(User).count() == 1
        assert session.execute(text("select 1")).scalar_one() == 1
```

- [x] **Step 2: Run the tests and verify failure**

Run:

```bash
pytest backend/tests/db -q
```

Expected: import failures because the persistence modules do not exist.

- [x] **Step 3: Implement the declarative base and models**

Create `backend/app/db/base.py`:

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

Replace `backend/app/db/models.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.ids import new_ulid
from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    name: Mapped[str] = mapped_column(String(120))
    created_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("teams.id"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("team_id", "name", name="uq_knowledge_base_team_name"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)
    team_id: Mapped[str] = mapped_column(String(26), ForeignKey("teams.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[str] = mapped_column(String(26), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
```

- [x] **Step 4: Implement engine and session helpers**

Create `backend/app/db/session.py`:

```python
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import models as _models  # noqa: F401
from backend.app.db.base import Base


def build_engine(database_url: str) -> Engine:
    if database_url in {"sqlite://", "sqlite+pysqlite:///:memory:"}:
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )

    if database_url.startswith("sqlite"):
        path = database_url.split("///", 1)[-1]
        if path:
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    return create_engine(
        database_url,
        connect_args={"check_same_thread": False}
        if database_url.startswith("sqlite")
        else {},
        future=True,
    )


def build_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
```

- [x] **Step 5: Run focused and full tests**

Run:

```bash
pytest backend/tests/db -q
pytest -q
```

Expected: persistence tests pass and the full suite remains green.

- [x] **Step 6: Commit**

```bash
git add backend/app/db backend/tests/db
git commit -m "feat: add SQLAlchemy persistence foundation"
```

### Task 3: API Runtime and Health Endpoints

**Files:**
- Create: `backend/app/api/errors.py`
- Create: `backend/app/api/envelope.py`
- Create: `backend/app/api/middleware.py`
- Create: `backend/app/api/v1/health.py`
- Modify: `backend/app/api/v1/router.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/api/__init__.py`
- Test: `backend/tests/api/conftest.py`
- Test: `backend/tests/api/test_health.py`

**Interfaces:**
- Produces: `create_app(settings=None, session_factory=None) -> FastAPI`.
- Produces: `ApiError`, `envelope(data, request_id)`, `page_envelope(items, request_id, next_cursor=None)`.
- Produces: `GET /api/v1/health`, `GET /api/v1/ready`, `GET /api/v1/version`.

- [x] **Step 1: Write failing API foundation tests**

Create `backend/tests/api/conftest.py`:

```python
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.main import create_app


@pytest.fixture()
def api_client():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    factory = build_session_factory(engine)
    app = create_app(
        settings=Settings(jwt_secret="test-secret"),
        session_factory=factory,
    )
    with TestClient(app) as client:
        yield client
```

Create `backend/tests/api/test_health.py`:

```python
def test_health_endpoint_uses_envelope_and_request_id(api_client):
    response = api_client.get(
        "/api/v1/health",
        headers={"X-Request-Id": "req-test-1"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-test-1"
    assert response.json() == {
        "data": {"status": "ok"},
        "meta": {"request_id": "req-test-1"},
    }


def test_unknown_route_uses_error_envelope(api_client):
    response = api_client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"] == response.headers["X-Request-Id"]


def test_ready_and_version_are_public(api_client):
    ready = api_client.get("/api/v1/ready")
    version = api_client.get("/api/v1/version")

    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready"
    assert version.status_code == 200
    assert version.json()["data"]["version"]
```

- [x] **Step 2: Run the tests and verify failure**

Run:

```bash
pytest backend/tests/api/test_health.py -q
```

Expected: import failure because the API app does not exist.

- [x] **Step 3: Implement the response envelope and errors**

Create `backend/app/api/envelope.py`:

```python
from typing import Any, Dict, List, Optional


def envelope(data: Any, request_id: str) -> Dict[str, Any]:
    return {"data": data, "meta": {"request_id": request_id}}


def page_envelope(
    items: List[Any],
    request_id: str,
    next_cursor: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "data": items,
        "meta": {
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
            "request_id": request_id,
        },
    }
```

Create `backend/app/api/errors.py`:

```python
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
```

- [x] **Step 4: Implement request IDs and health routes**

Create `backend/app/api/middleware.py`:

```python
from starlette.middleware.base import BaseHTTPMiddleware

from backend.app.core.ids import new_ulid


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-Id") or "req_" + new_ulid()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
```

Create `backend/app/api/v1/health.py`:

```python
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
```

Replace `backend/app/api/v1/router.py`:

```python
from fastapi import APIRouter

from backend.app.api.v1.health import router as health_router


api_router = APIRouter()
api_router.include_router(health_router)
```

Create `backend/app/main.py`:

```python
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
```

- [x] **Step 5: Run focused and full tests**

Run:

```bash
pytest backend/tests/api/test_health.py -q
pytest -q
```

Expected: health tests pass and the full suite remains green.

- [x] **Step 6: Commit**

```bash
git add backend/app/api backend/app/main.py backend/tests/api
git commit -m "feat: add FastAPI runtime and health endpoints"
```

### Task 4: Authentication API

**Files:**
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/v1/schemas.py`
- Create: `backend/app/api/v1/auth.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/api/test_auth.py`

**Interfaces:**
- Consumes: `Settings`, `User`, `TeamMember`, `hash_password`, `verify_password`, `create_access_token`, `decode_access_token`.
- Produces: `get_session`, `get_current_user`.
- Produces: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`.

- [x] **Step 1: Write failing auth tests**

Create `backend/tests/api/test_auth.py`:

```python
def _register(client, email="member@example.com", password="password-123"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "Member"},
    )


def test_register_login_and_me(api_client):
    registered = _register(api_client)
    assert registered.status_code == 201
    assert registered.json()["data"]["email"] == "member@example.com"
    assert "password_hash" not in registered.json()["data"]

    logged_in = api_client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "password-123"},
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["data"]["access_token"]

    me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )
    assert me.status_code == 200
    assert me.json()["data"]["display_name"] == "Member"


def test_duplicate_email_and_wrong_password_use_error_envelopes(api_client):
    assert _register(api_client).status_code == 201
    duplicate = _register(api_client)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_RESOURCE"

    wrong = api_client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "wrong-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_requires_a_valid_token(api_client):
    missing = api_client.get("/api/v1/auth/me")
    invalid = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
```

- [x] **Step 2: Run the tests and verify failure**

Run:

```bash
pytest backend/tests/api/test_auth.py -q
```

Expected: 404 responses because the auth routes do not exist.

- [x] **Step 3: Implement request schemas**

Create `backend/app/api/v1/schemas.py`:

```python
from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    is_active: bool
    created_at: datetime


class MembershipView(BaseModel):
    team_id: str
    team_name: str
    role: str
    status: str


class MeView(BaseModel):
    user: UserView
    memberships: List[MembershipView]
```

- [x] **Step 4: Implement session and bearer dependencies**

Create `backend/app/api/deps.py`:

```python
from typing import Iterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.api.errors import ApiError
from backend.app.core.tokens import TokenError, decode_access_token
from backend.app.db.models import User


bearer = HTTPBearer(auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    if credentials is None:
        raise ApiError(401, "UNAUTHENTICATED", "Authentication is required.")
    try:
        user_id = decode_access_token(
            credentials.credentials,
            request.app.state.settings,
        )
    except TokenError as error:
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token.") from error

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise ApiError(401, "UNAUTHENTICATED", "User is not active.")
    return user
```

- [x] **Step 5: Implement auth routes**

Create `backend/app/api/v1/auth.py`:

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.schemas import (
    LoginRequest,
    MembershipView,
    MeView,
    RegisterRequest,
    UserView,
)
from backend.app.core.passwords import hash_password, verify_password
from backend.app.core.tokens import create_access_token
from backend.app.db.models import Team, TeamMember, User


router = APIRouter(tags=["auth"])


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or " " in normalized:
        raise ApiError(400, "INVALID_ARGUMENT", "A valid email is required.")
    return normalized


@router.post("/auth/register", status_code=201)
def register(
    body: RegisterRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    email = _normalize_email(body.email)
    if session.scalar(select(User).where(User.email == email)) is not None:
        raise ApiError(409, "DUPLICATE_RESOURCE", "Email is already registered.")

    user = User(
        email=email,
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ApiError(409, "DUPLICATE_RESOURCE", "Email is already registered.") from error

    return envelope(UserView.model_validate(user).model_dump(), request.state.request_id)


@router.post("/auth/login")
def login(
    body: LoginRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    email = _normalize_email(body.email)
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(
        body.password, user.password_hash
    ):
        raise ApiError(401, "UNAUTHENTICATED", "Invalid email or password.")

    token = create_access_token(user.id, request.app.state.settings)
    return envelope(
        {"access_token": token, "token_type": "bearer"},
        request.state.request_id,
    )


@router.get("/auth/me")
def me(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    rows = session.execute(
        select(TeamMember, Team)
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.user_id == user.id)
        .order_by(Team.created_at.desc())
    ).all()
    memberships = [
        MembershipView(
            team_id=team.id,
            team_name=team.name,
            role=membership.role,
            status=membership.status,
        )
        for membership, team in rows
    ]
    return envelope(
        MeView(
            user=UserView.model_validate(user),
            memberships=memberships,
        ).model_dump(),
        request.state.request_id,
    )
```

- [x] **Step 6: Wire the auth router**

Update `backend/app/api/v1/router.py`:

```python
from fastapi import APIRouter

from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.health import router as health_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
```

- [x] **Step 7: Run focused and full tests**

Run:

```bash
pytest backend/tests/api/test_auth.py -q
pytest -q
```

Expected: auth tests pass and the full suite remains green.

- [x] **Step 8: Commit**

```bash
git add backend/app/api backend/tests/api/test_auth.py
git commit -m "feat: add authentication API"
```

### Task 5: Teams and Knowledge Bases API

> **Implementation ruling:** The shipped implementation uses an atomic conditional `UPDATE ... WHERE version = expected` for team update, KB update, and KB archive. Zero-row updates return 409 `VERSION_CONFLICT` or 409 `RESOURCE_STATE_CONFLICT`. Archived KBs are immutable in this slice. Team and KB names are stripped and rejected when blank. The code blocks below show the original design; these rulings take precedence.

**Files:**
- Create: `backend/app/api/v1/teams.py`
- Create: `backend/app/api/v1/kbs.py`
- Modify: `backend/app/api/v1/schemas.py`
- Modify: `backend/app/api/v1/router.py`
- Test: `backend/tests/api/test_teams.py`
- Test: `backend/tests/api/test_kbs.py`

**Interfaces:**
- Consumes: `get_current_user`, `get_session`, `Team`, `TeamMember`, `KnowledgeBase`.
- Produces: team and KB list/create/detail/update/archive endpoints.
- Produces: `_membership_or_error`, `_leader_or_error`, `_if_match_version`.

- [x] **Step 1: Write failing team and KB tests**

Create `backend/tests/api/test_teams.py`:

```python
def _register_and_login(client, email="leader@example.com"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password-123", "display_name": "Leader"},
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password-123"},
    )
    token = login.json()["data"]["access_token"]
    return {"Authorization": "Bearer " + token}


def test_team_create_list_and_detail(api_client):
    headers = _register_and_login(api_client)
    created = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Platform"},
        headers=headers,
    )
    assert created.status_code == 201
    team = created.json()["data"]
    assert team["name"] == "Platform"
    assert team["version"] == 1

    listed = api_client.get("/api/v1/teams", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [team["id"]]

    detail = api_client.get(
        "/api/v1/teams/detail",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == team["id"]


def test_team_update_requires_leader_and_if_match(api_client):
    headers = _register_and_login(api_client)
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Platform"},
        headers=headers,
    ).json()["data"]

    missing_match = api_client.post(
        "/api/v1/teams/update",
        json={"team_id": team["id"], "name": "Renamed"},
        headers=headers,
    )
    assert missing_match.status_code == 400

    updated = api_client.post(
        "/api/v1/teams/update",
        json={"team_id": team["id"], "name": "Renamed"},
        headers={**headers, "If-Match": "1"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Renamed"
    assert updated.json()["data"]["version"] == 2

    conflict = api_client.post(
        "/api/v1/teams/update",
        json={"team_id": team["id"], "name": "Again"},
        headers={**headers, "If-Match": "1"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "VERSION_CONFLICT"
```

Create `backend/tests/api/test_kbs.py`:

```python
from backend.tests.api.test_teams import _register_and_login


def _create_team(client, headers):
    return client.post(
        "/api/v1/teams/create",
        json={"name": "Platform"},
        headers=headers,
    ).json()["data"]


def test_leader_can_create_list_and_archive_kb(api_client):
    headers = _register_and_login(api_client, email="kb-leader@example.com")
    team = _create_team(api_client, headers)

    created = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Java", "description": "JDK notes"},
        headers=headers,
    )
    assert created.status_code == 201
    kb = created.json()["data"]
    assert kb["name"] == "Java"

    listed = api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert [item["id"] for item in listed.json()["data"]] == [kb["id"]]

    archived = api_client.post(
        "/api/v1/kbs/archive",
        json={"team_id": team["id"], "kb_id": kb["id"]},
        headers={**headers, "If-Match": "1"},
    )
    assert archived.status_code == 202
    assert archived.json()["data"]["status"] == "archived"

    listed_after = api_client.get(
        "/api/v1/kbs",
        params={"team_id": team["id"]},
        headers=headers,
    )
    assert listed_after.json()["data"] == []


def test_non_leader_cannot_create_kb(api_client):
    leader_headers = _register_and_login(api_client, email="owner@example.com")
    team = _create_team(api_client, leader_headers)
    member_headers = _register_and_login(api_client, email="member@example.com")

    response = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Forbidden"},
        headers=member_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


def test_kb_update_requires_leader_and_if_match(api_client):
    leader_headers = _register_and_login(api_client, email="kb-update-leader@example.com")
    team = _create_team(api_client, leader_headers)
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Java"},
        headers=leader_headers,
    ).json()["data"]

    missing_match = api_client.post(
        "/api/v1/kbs/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "name": "Java 21",
        },
        headers=leader_headers,
    )
    assert missing_match.status_code == 400

    updated = api_client.post(
        "/api/v1/kbs/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "name": "Java 21",
        },
        headers={**leader_headers, "If-Match": "1"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "Java 21"
    assert updated.json()["data"]["version"] == 2

    conflict = api_client.post(
        "/api/v1/kbs/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "name": "Java 17",
        },
        headers={**leader_headers, "If-Match": "1"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "VERSION_CONFLICT"

    member_headers = _register_and_login(
        api_client, email="kb-update-member@example.com"
    )
    forbidden = api_client.post(
        "/api/v1/kbs/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "name": "Forbidden",
        },
        headers=member_headers,
    )
    assert forbidden.status_code == 403
```

- [x] **Step 2: Run the tests and verify failure**

Run:

```bash
pytest backend/tests/api/test_teams.py backend/tests/api/test_kbs.py -q
```

Expected: 404 responses because the routes do not exist.

- [x] **Step 3: Add request/response schemas**

Append to `backend/app/api/v1/schemas.py`:

```python
from typing import Optional


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TeamUpdateRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    name: str = Field(min_length=1, max_length=120)


class KnowledgeBaseCreateRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)


class KnowledgeBaseUpdateRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    kb_id: str = Field(min_length=1, max_length=26)
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=2000)


class KnowledgeBaseArchiveRequest(BaseModel):
    team_id: str = Field(min_length=1, max_length=26)
    kb_id: str = Field(min_length=1, max_length=26)
```

- [x] **Step 4: Implement team routes**

Create `backend/app/api/v1/teams.py`:

```python
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
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


def _if_match_version(request: Request, current_version: int) -> None:
    raw = request.headers.get("If-Match")
    if raw is None:
        raise ApiError(400, "INVALID_ARGUMENT", "If-Match is required.")
    try:
        expected = int(raw.strip().strip('"'))
    except ValueError as error:
        raise ApiError(400, "INVALID_ARGUMENT", "If-Match must be an integer.") from error
    if expected != current_version:
        raise ApiError(409, "VERSION_CONFLICT", "Resource version has changed.")


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
    team = session.get(Team, body.team_id)
    if team is None:
        raise ApiError(403, "PERMISSION_DENIED", "Team is not available.")
    _if_match_version(request, team.version)
    team.name = body.name.strip()
    team.version += 1
    session.commit()
    return envelope(_team_view(team), request.state.request_id)
```

- [x] **Step 5: Implement knowledge-base routes**

Create `backend/app/api/v1/kbs.py`:

```python
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user, get_session
from backend.app.api.envelope import envelope, page_envelope
from backend.app.api.errors import ApiError
from backend.app.api.v1.schemas import (
    KnowledgeBaseArchiveRequest,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseUpdateRequest,
)
from backend.app.api.v1.teams import (
    _if_match_version,
    _leader_or_error,
    _membership_or_error,
)
from backend.app.db.models import KnowledgeBase, User


router = APIRouter(tags=["kbs"])


def _kb_view(kb: KnowledgeBase):
    return {
        "id": kb.id,
        "team_id": kb.team_id,
        "name": kb.name,
        "description": kb.description,
        "status": kb.status,
        "version": kb.version,
        "created_at": kb.created_at.isoformat(),
    }


@router.get("/kbs")
def list_kbs(
    request: Request,
    team_id: str,
    limit: int = 20,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    kbs = session.scalars(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.team_id == team_id,
            KnowledgeBase.status == "active",
        )
        .order_by(KnowledgeBase.created_at.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return page_envelope(
        [_kb_view(kb) for kb in kbs],
        request.state.request_id,
    )


@router.post("/kbs/create", status_code=201)
def create_kb(
    body: KnowledgeBaseCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, body.team_id, user.id)
    kb = KnowledgeBase(
        team_id=body.team_id,
        name=body.name.strip(),
        description=body.description,
        created_by=user.id,
    )
    session.add(kb)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ApiError(
            409,
            "DUPLICATE_RESOURCE",
            "A knowledge base with this name already exists.",
        ) from error
    return envelope(_kb_view(kb), request.state.request_id)


@router.get("/kbs/detail")
def get_kb(
    request: Request,
    team_id: str,
    kb_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _membership_or_error(session, team_id, user.id)
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None or kb.team_id != team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    return envelope(_kb_view(kb), request.state.request_id)


@router.post("/kbs/update")
def update_kb(
    body: KnowledgeBaseUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, body.team_id, user.id)
    kb = session.get(KnowledgeBase, body.kb_id)
    if kb is None or kb.team_id != body.team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    _if_match_version(request, kb.version)
    kb.name = body.name.strip()
    kb.description = body.description
    kb.version += 1
    session.commit()
    return envelope(_kb_view(kb), request.state.request_id)


@router.post("/kbs/archive", status_code=202)
def archive_kb(
    body: KnowledgeBaseArchiveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _leader_or_error(session, body.team_id, user.id)
    kb = session.get(KnowledgeBase, body.kb_id)
    if kb is None or kb.team_id != body.team_id:
        raise ApiError(404, "NOT_FOUND", "Knowledge base was not found.")
    _if_match_version(request, kb.version)
    kb.status = "archived"
    kb.version += 1
    session.commit()
    return envelope(_kb_view(kb), request.state.request_id)
```

- [x] **Step 6: Wire team and KB routers**

Update `backend/app/api/v1/router.py`:

```python
from fastapi import APIRouter

from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.kbs import router as kbs_router
from backend.app.api.v1.teams import router as teams_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(teams_router)
api_router.include_router(kbs_router)
```

- [x] **Step 7: Run focused and full tests**

Run:

```bash
pytest backend/tests/api/test_teams.py backend/tests/api/test_kbs.py -q
pytest -q
```

Expected: team and KB tests pass and the full suite remains green.

- [x] **Step 8: Commit**

```bash
git add backend/app/api backend/tests/api
git commit -m "feat: add team and knowledge base APIs"
```

### Task 6: Contract Verification and Developer Commands

**Files:**
- Create: `backend/tests/api/test_contract_paths.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `create_app`.
- Produces: an executable P0 API contract check and the local run command.

- [x] **Step 1: Write the failing contract test**

Create `backend/tests/api/test_contract_paths.py`:

```python
def test_implemented_p0_paths_are_exposed_without_path_parameters(api_client):
    paths = set(api_client.app.openapi()["paths"])

    required = {
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/version",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/teams",
        "/api/v1/teams/create",
        "/api/v1/teams/detail",
        "/api/v1/teams/update",
        "/api/v1/kbs",
        "/api/v1/kbs/create",
        "/api/v1/kbs/detail",
        "/api/v1/kbs/update",
        "/api/v1/kbs/archive",
    }

    assert required.issubset(paths)
    assert all("{" not in path for path in paths)
```

- [x] **Step 2: Run the test and verify failure**

Run:

```bash
pytest backend/tests/api/test_contract_paths.py -q
```

Expected: PASS when Tasks 1-5 are complete; this is the executable contract gate for the new surface.

- [x] **Step 3: Document the runnable API**

Add to `README.md` after the local test commands:

```markdown
### 启动 API

```bash
python -m pip install -e ".[test,api]"
uvicorn backend.app.main:create_app --factory --reload
```

默认地址为 `http://127.0.0.1:8000/api/v1`，交互文档为
`http://127.0.0.1:8000/docs`。当前 API 已覆盖健康检查、注册登录、
当前用户、团队和知识库；文档上传、检索问答、Celery 和前端仍待接入。

测试数据库使用独立的 SQLite 内存库；本地开发默认使用
`data/techvault.db`，可通过 `TECHVAULT_DATABASE_URL` 覆盖。
```

- [x] **Step 4: Run full verification**

Run:

```bash
pytest -q
python -m compileall -q backend
```

Expected: full suite passes and compileall exits successfully.

- [x] **Step 5: Commit**

```bash
git add backend/tests/api/test_contract_paths.py README.md
git commit -m "test: verify API contract and runnable service"
```

### Task 7: Fail-Closed Runtime Settings

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/tokens.py`
- Modify: `backend/app/api/v1/auth.py`
- Modify: `backend/tests/api/conftest.py`
- Modify: `backend/tests/api/test_runtime.py`
- Modify: `backend/tests/core/test_config.py`
- Modify: `backend/tests/core/test_tokens.py`
- Modify: `README.md`

**Interfaces:**
- `Settings()` and `Settings.from_env()` must fail closed unless the environment is explicitly `development` or a strong secret is supplied.
- `decode_access_token` must require `sub`, `iat`, and `exp`.

- [x] **Step 1: Write failing settings tests**

Add to `backend/tests/core/test_config.py`:

```python
def test_default_settings_fail_closed_without_explicit_development():
    with pytest.raises(ValueError, match="32 bytes"):
        Settings()


def test_explicit_development_allows_local_secret():
    settings = Settings(environment="development")

    assert settings.jwt_secret


def test_non_positive_token_ttl_is_rejected():
    with pytest.raises(ValueError, match="TTL"):
        Settings(environment="development", access_token_ttl_seconds=0)
```

- [x] **Step 2: Make settings fail closed**

Set `_DEFAULT_ENVIRONMENT = "production"` and add:

```python
if self.access_token_ttl_seconds <= 0:
    raise ValueError("access token TTL must be positive")
```

Keep the existing non-development secret-strength check.

- [x] **Step 3: Require token claims**

In `decode_access_token` use:

```python
payload = jwt.decode(
    token,
    settings.jwt_secret,
    algorithms=[settings.jwt_algorithm],
    options={"require": ["sub", "iat", "exp"]},
)
```

Add a token test that signs a payload without `exp` and expects `TokenError`.

- [x] **Step 4: Add timing-equalized unknown-user login**

Create a module-level dummy hash in `auth.py` and verify it when the user is missing or inactive:

```python
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-login-timing")

if user is None or not user.is_active:
    verify_password(body.password, _DUMMY_PASSWORD_HASH)
    raise ApiError(401, "UNAUTHENTICATED", "Invalid email or password.")
if not verify_password(body.password, user.password_hash):
    raise ApiError(401, "UNAUTHENTICATED", "Invalid email or password.")
```

- [x] **Step 5: Update test settings**

Use a long test secret and `environment="test"` in `backend/tests/api/conftest.py`, or `environment="development"` for tests that intentionally use the local default. Update `test_runtime.py` and `test_tokens.py` so no test constructs `Settings()` without an explicit environment.

- [x] **Step 6: Document local development**

Add to the README start command:

```bash
export TECHVAULT_ENVIRONMENT=development
uvicorn backend.app.main:create_app --factory --reload
```

State that production must set a unique `TECHVAULT_JWT_SECRET` of at least 32 bytes and must not use `development`.

- [x] **Step 7: Verify and commit**

```bash
.venv/bin/python -m pytest backend/tests/core backend/tests/api -q
.venv/bin/python -m pytest -q
git add backend README.md
git commit -m "security: fail closed on runtime settings"
```

### Task 8: Cursor Pagination and Contract Shapes

**Files:**
- Create: `backend/app/api/pagination.py`
- Modify: `backend/app/api/v1/teams.py`
- Modify: `backend/app/api/v1/kbs.py`
- Modify: `backend/app/api/v1/schemas.py`
- Modify: `backend/app/api/v1/auth.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/tests/api/test_auth.py`
- Modify: `backend/tests/api/test_teams.py`
- Modify: `backend/tests/api/test_kbs.py`

**Interfaces:**
- `encode_cursor(created_at, item_id) -> str`
- `decode_cursor(cursor) -> tuple[datetime, str]`
- Team and KB list endpoints accept `cursor`, return `next_cursor` and `has_more`.
- User responses expose `status`, not `is_active`.
- Team responses expose `description` and the caller's `role`.
- KB responses expose `updated_at`, `default_model_policy_mode="local_only"`, and `document_count=0`.

- [x] **Step 1: Write failing pagination and shape tests**

Add tests that create three teams and three KBs, list with `limit=1`, follow `next_cursor`, and collect all three. Assert an invalid cursor returns 400 `INVALID_ARGUMENT`. Assert team responses include `description` and `role`; KB responses include `updated_at`, `default_model_policy_mode`, and `document_count`; user responses include `status` and omit `is_active`.

- [x] **Step 2: Implement cursor helpers**

Create `backend/app/api/pagination.py`:

```python
import base64
import json
from datetime import datetime, timezone
from typing import Tuple

from backend.app.api.errors import ApiError


def encode_cursor(created_at: datetime, item_id: str) -> str:
    payload = json.dumps(
        {
            "created_at": created_at.astimezone(timezone.utc).isoformat(),
            "id": item_id,
        },
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> Tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        item_id = payload["id"]
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("cursor id is missing")
        return created_at, item_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid cursor.") from error
```

- [x] **Step 3: Add pagination to team and KB listings**

Use `limit + 1` rows, `has_more = len(rows) > limit`, and encode the last returned row when more rows exist. Apply the cursor predicate:

```python
or_(
    Team.created_at < after_created,
    and_(Team.created_at == after_created, Team.id < after_id),
)
```

Use `order_by(Team.created_at.desc(), Team.id.desc())`. Repeat with `KnowledgeBase`.

- [x] **Step 4: Align response shapes**

- Add nullable `description` to the `Team` model and team create/update schemas.
- Return the membership role in team views.
- Return `status` from `UserView` instead of `is_active`.
- Add `updated_at`, `default_model_policy_mode: "local_only"`, and `document_count: 0` to KB views.

- [x] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest backend/tests/api -q
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q backend
git add backend
git commit -m "feat: add cursor pagination and contract shapes"
```
