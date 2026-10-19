import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.main import create_app

ADMIN_EMAIL = "admin@techvault.local"
ADMIN_PASSWORD = "ChangeMe-123!"


@pytest.fixture()
def api_app():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    factory = build_session_factory(engine)
    return create_app(
        settings=Settings(
            environment="test",
            jwt_secret="test-secret-at-least-32-bytes-long",
            allow_registration=True,
            allow_legacy_team_creation=True,
        ),
        session_factory=factory,
    )


@pytest.fixture()
def api_client(api_app):
    with TestClient(api_app) as client:
        yield client


@pytest.fixture()
def strict_api_app():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    factory = build_session_factory(engine)
    return create_app(
        settings=Settings(
            environment="test",
            jwt_secret="test-secret-at-least-32-bytes-long",
            allow_registration=False,
            allow_legacy_team_creation=False,
        ),
        session_factory=factory,
    )


@pytest.fixture()
def strict_api_client(strict_api_app):
    with TestClient(strict_api_app) as client:
        yield client


@pytest.fixture()
def admin_headers(api_client):
    login = api_client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    token = login.json()["data"]["access_token"]
    return {"Authorization": "Bearer " + token}
