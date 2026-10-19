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
