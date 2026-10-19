from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
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


def _bridge_teams_description(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("teams"):
        return
    columns = {column["name"] for column in inspector.get_columns("teams")}
    if "description" in columns:
        return

    # PoC schema bridge; replace with Alembic migrations before production use.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE teams ADD COLUMN description TEXT"))


def _bridge_users_admin_flags(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("users"):
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    statements = []
    if "is_super_admin" not in columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN is_super_admin BOOLEAN NOT NULL DEFAULT FALSE"
        )
    if "is_builtin" not in columns:
        statements.append(
            "ALTER TABLE users ADD COLUMN is_builtin BOOLEAN NOT NULL DEFAULT FALSE"
        )
    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _bridge_chunks_scope(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("chunks"):
        return
    columns = {column["name"] for column in inspector.get_columns("chunks")}
    definitions = {
        "team_id": "VARCHAR(26) NOT NULL DEFAULT ''",
        "knowledge_base_id": "VARCHAR(26) NOT NULL DEFAULT ''",
        "owner_user_id": "VARCHAR(26) NOT NULL DEFAULT ''",
        "visibility": "VARCHAR(16) NOT NULL DEFAULT 'team_shared'",
        "data_classification": "VARCHAR(16) NOT NULL DEFAULT 'internal'",
        "doc_status": "VARCHAR(16) NOT NULL DEFAULT 'active'",
        "chunk_status": "VARCHAR(16) NOT NULL DEFAULT 'enabled'",
        "version_values": "TEXT NOT NULL DEFAULT '[]'",
        "logical_chunk_key": "TEXT NOT NULL DEFAULT ''",
        "content_hash": "VARCHAR(128) NOT NULL DEFAULT ''",
        "source_path": "VARCHAR(500) NOT NULL DEFAULT ''",
        "index_generation": "VARCHAR(26) NOT NULL DEFAULT ''",
    }
    statements = [
        "ALTER TABLE chunks ADD COLUMN {0} {1}".format(name, definition)
        for name, definition in definitions.items()
        if name not in columns
    ]
    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _bridge_kb_policy(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("knowledge_bases"):
        return
    columns = {column["name"] for column in inspector.get_columns("knowledge_bases")}
    if "model_policy_mode" in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE knowledge_bases ADD COLUMN "
                "model_policy_mode VARCHAR(24) NOT NULL DEFAULT 'local_only'"
            )
        )


def _bridge_index_generation_validation(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("index_generations"):
        return
    columns = {
        column["name"] for column in inspector.get_columns("index_generations")
    }
    statements = []
    if "validation_errors" not in columns:
        statements.append(
            "ALTER TABLE index_generations ADD COLUMN "
            "validation_errors TEXT NOT NULL DEFAULT '[]'"
        )
    if "validated_at" not in columns:
        statements.append(
            "ALTER TABLE index_generations ADD COLUMN validated_at DATETIME"
        )
    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _bridge_invitation_expiry(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("invitations"):
        return
    columns = {column["name"] for column in inspector.get_columns("invitations")}
    statements = []
    if "expires_at" not in columns:
        statements.append(
            "ALTER TABLE invitations ADD COLUMN expires_at DATETIME NOT NULL "
            "DEFAULT '1970-01-01 00:00:00'"
        )
    if "updated_at" not in columns:
        statements.append(
            "ALTER TABLE invitations ADD COLUMN updated_at DATETIME NOT NULL "
            "DEFAULT '1970-01-01 00:00:00'"
        )
    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _bridge_teams_description(engine)
    _bridge_users_admin_flags(engine)
    _bridge_chunks_scope(engine)
    _bridge_kb_policy(engine)
    _bridge_index_generation_validation(engine)
    _bridge_invitation_expiry(engine)
