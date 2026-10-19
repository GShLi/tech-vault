from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db import models as _models  # noqa: F401
from backend.app.db.base import Base


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def build_engine(database_url: str) -> Engine:
    if database_url in {"sqlite://", "sqlite+pysqlite:///:memory:"}:
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    else:
        if database_url.startswith("sqlite"):
            path = database_url.split("///", 1)[-1]
            if path:
                Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False}
            if database_url.startswith("sqlite")
            else {},
            future=True,
        )

    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)

    return engine


def build_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
