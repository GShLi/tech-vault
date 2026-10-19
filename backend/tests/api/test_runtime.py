import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api.errors import ApiError
from backend.app.core.config import Settings
from backend.app.main import create_app


VALID_REQUEST_ID = re.compile(r"req_[0-9A-HJKMNP-TV-Z]{26}")


def test_import_does_not_create_default_database(tmp_path):
    database_path = tmp_path / "import-side-effect.db"
    env = os.environ.copy()
    env["TECHVAULT_DATABASE_URL"] = f"sqlite+pysqlite:///{database_path}"

    subprocess.run(
        [sys.executable, "-c", "import backend.app.main"],
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert not database_path.exists()


def test_internal_engine_is_stored_and_disposed_on_shutdown(tmp_path, monkeypatch):
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'dispose.db'}",
        environment="development",
        jwt_secret="test-secret",
    )
    app = create_app(settings=settings)
    engine = app.state.engine
    disposed = []
    monkeypatch.setattr(engine, "dispose", lambda: disposed.append(True))

    with TestClient(app):
        assert disposed == []

    assert disposed == [True]


def test_generated_request_id_is_returned_in_header_and_envelope(api_client):
    response = api_client.get("/api/v1/health")

    request_id = response.headers["X-Request-Id"]
    assert VALID_REQUEST_ID.fullmatch(request_id)
    assert response.json()["meta"]["request_id"] == request_id


@pytest.mark.parametrize(
    "request_id",
    ["", "contains spaces", "contains/slash", "a" * 129],
)
def test_invalid_client_request_id_is_replaced(api_client, request_id):
    response = api_client.get(
        "/api/v1/health",
        headers={"X-Request-Id": request_id},
    )

    generated = response.headers["X-Request-Id"]
    assert generated != request_id
    assert VALID_REQUEST_ID.fullmatch(generated)
    assert response.json()["meta"]["request_id"] == generated


def test_validation_error_uses_error_envelope(api_app):
    @api_app.get("/api/v1/test-validation")
    def validation_route(limit: int):
        return {"limit": limit}

    with TestClient(api_app) as client:
        response = client.get("/api/v1/test-validation")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_FAILED"
    assert error["message"] == "Request validation failed."
    assert error["details"]["errors"][0]["loc"] == ["query", "limit"]
    assert error["request_id"] == response.headers["X-Request-Id"]


def test_http_exception_422_uses_validation_failed_code(api_app):
    @api_app.get("/api/v1/test-http-validation")
    def http_validation_route():
        raise HTTPException(status_code=422, detail="Validation failed.")

    with TestClient(api_app) as client:
        response = client.get("/api/v1/test-http-validation")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_api_error_encodes_details(api_app):
    @api_app.get("/api/v1/test-api-error")
    def api_error_route():
        raise ApiError(
            409,
            "RESOURCE_STATE_CONFLICT",
            "Resource cannot transition.",
            {"at": datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)},
        )

    with TestClient(api_app) as client:
        response = client.get("/api/v1/test-api-error")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "RESOURCE_STATE_CONFLICT",
            "message": "Resource cannot transition.",
            "details": {"at": "2026-10-19T12:00:00+00:00"},
            "request_id": response.headers["X-Request-Id"],
        }
    }


def test_unhandled_exception_uses_500_envelope(api_app):
    @api_app.get("/api/v1/test-unhandled")
    def unhandled_route():
        raise RuntimeError("boom")

    with TestClient(api_app) as client:
        response = client.get(
            "/api/v1/test-unhandled",
            headers={"X-Request-Id": "req-test-500"},
        )

    assert response.status_code == 500
    assert response.headers["X-Request-Id"] == "req-test-500"
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Internal server error.",
            "details": {},
            "request_id": "req-test-500",
        }
    }


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, "INVALID_ARGUMENT"),
        (401, "UNAUTHENTICATED"),
        (403, "PERMISSION_DENIED"),
        (404, "NOT_FOUND"),
        (409, "RESOURCE_STATE_CONFLICT"),
        (413, "PAYLOAD_TOO_LARGE"),
        (418, "INVALID_ARGUMENT"),
        (429, "RATE_LIMITED"),
        (500, "INTERNAL_ERROR"),
        (503, "SERVICE_UNAVAILABLE"),
    ],
)
def test_http_exception_codes_follow_contract(api_app, status_code, expected_code):
    @api_app.get("/api/v1/test-http-error")
    def http_error_route():
        raise HTTPException(status_code=status_code, detail="Request failed.")

    with TestClient(api_app) as client:
        response = client.get("/api/v1/test-http-error")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == expected_code
    assert response.json()["error"]["request_id"] == response.headers[
        "X-Request-Id"
    ]


def test_http_exception_preserves_dict_details(api_app):
    @api_app.get("/api/v1/test-forbidden")
    def forbidden_route():
        raise HTTPException(
            status_code=403,
            detail={"message": "Access denied.", "resource": "team"},
        )

    with TestClient(api_app) as client:
        response = client.get("/api/v1/test-forbidden")

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "PERMISSION_DENIED",
        "message": "Access denied.",
        "details": {"message": "Access denied.", "resource": "team"},
        "request_id": response.headers["X-Request-Id"],
    }
