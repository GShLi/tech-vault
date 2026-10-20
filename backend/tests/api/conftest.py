import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.main import create_app

ADMIN_EMAIL = "admin@techvault.local"
ADMIN_PASSWORD = "ChangeMe-123!"


def login_headers(
    client,
    email: str = ADMIN_EMAIL,
    password: str = "password-123",
):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["data"]["access_token"]}


def admin_headers_for(client):
    return login_headers(client, ADMIN_EMAIL, ADMIN_PASSWORD)


def create_team_as_admin(client, headers, name="Test Team"):
    response = client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def create_user_as_admin(
    client,
    headers,
    team_id,
    email,
    role="member",
    password="password-123",
    display_name="Test User",
):
    response = client.post(
        "/api/v1/admin/users/create",
        json={
            "email": email,
            "display_name": display_name,
            "password": password,
            "team_id": team_id,
            "role": role,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.fixture()
def api_app():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    factory = build_session_factory(engine)
    return create_app(
        settings=Settings(
            environment="development",
            jwt_secret="test-secret-at-least-32-bytes-long",
            task_execution_mode="inline",
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
            task_execution_mode="inline",
        ),
        session_factory=factory,
    )


@pytest.fixture()
def strict_api_client(strict_api_app):
    with TestClient(strict_api_app) as client:
        yield client


@pytest.fixture()
def admin_headers(api_client):
    return admin_headers_for(api_client)
