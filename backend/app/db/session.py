from pathlib import Path

from sqlalchemy import MetaData, create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateIndex, CreateTable

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
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _bridge_document_object_uri(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("documents"):
        return
    columns = {column["name"] for column in inspector.get_columns("documents")}
    if "object_uri" in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE documents ADD COLUMN object_uri VARCHAR(2000)")
        )


def _bridge_document_lifecycle(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("documents"):
        return
    columns = {column["name"] for column in inspector.get_columns("documents")}
    timestamp_type = (
        "TIMESTAMP WITH TIME ZONE"
        if engine.dialect.name == "postgresql"
        else "DATETIME"
    )
    statements = []
    if "deleted_at" not in columns:
        statements.append(
            "ALTER TABLE documents ADD COLUMN deleted_at " + timestamp_type
        )
    if "purged_at" not in columns:
        statements.append(
            "ALTER TABLE documents ADD COLUMN purged_at " + timestamp_type
        )

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text(
                "UPDATE documents SET deleted_at = updated_at "
                "WHERE doc_status IN ('deleted', 'deleting') "
                "AND deleted_at IS NULL"
            )
        )


def _bridge_chunk_overrides(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("chunks"):
        return
    columns = {column["name"] for column in inspector.get_columns("chunks")}
    with engine.begin() as connection:
        if "auto_content" not in columns:
            connection.execute(
                text("ALTER TABLE chunks ADD COLUMN auto_content TEXT NOT NULL DEFAULT ''")
            )
        connection.execute(
            text(
                "UPDATE chunks SET auto_content = content "
                "WHERE auto_content IS NULL OR auto_content = ''"
            )
        )


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


def _bridge_credential_encryption(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("credentials"):
        return
    columns = {column["name"] for column in inspector.get_columns("credentials")}
    if "secret_encrypted" in columns:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE credentials ADD COLUMN "
                "secret_encrypted TEXT NOT NULL DEFAULT ''"
            )
        )


def _bridge_model_provider_api_key(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("model_providers"):
        return
    columns = {
        column["name"] for column in inspector.get_columns("model_providers")
    }
    timestamp_type = (
        "TIMESTAMP WITH TIME ZONE"
        if engine.dialect.name == "postgresql"
        else "DATETIME"
    )
    statements = []
    if "api_key_masked" not in columns:
        statements.append(
            "ALTER TABLE model_providers ADD COLUMN "
            "api_key_masked VARCHAR(40) NOT NULL DEFAULT ''"
        )
    if "api_key_encrypted" not in columns:
        statements.append(
            "ALTER TABLE model_providers ADD COLUMN "
            "api_key_encrypted TEXT NOT NULL DEFAULT ''"
        )
    if "api_key_updated_at" not in columns:
        statements.append(
            "ALTER TABLE model_providers ADD COLUMN "
            "api_key_updated_at " + timestamp_type
        )
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _bridge_evaluation_run_provider(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("evaluation_runs"):
        return
    columns = {
        column["name"] for column in inspector.get_columns("evaluation_runs")
    }
    statements = []
    if "provider_id" not in columns:
        statements.append(
            "ALTER TABLE evaluation_runs ADD COLUMN "
            "provider_id VARCHAR(26) NOT NULL DEFAULT ''"
        )
    if "model_id" not in columns:
        statements.append(
            "ALTER TABLE evaluation_runs ADD COLUMN "
            "model_id VARCHAR(120) NOT NULL DEFAULT ''"
        )
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _bridge_audit_log_nullability(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("audit_logs"):
        return
    columns = {
        column["name"]: column for column in inspector.get_columns("audit_logs")
    }
    team_column = columns.get("team_id")
    actor_column = columns.get("actor_id")
    needs_relaxation = (
        team_column is None
        or actor_column is None
        or team_column.get("nullable") is False
        or actor_column.get("nullable") is False
    )
    if not needs_relaxation:
        return

    if engine.dialect.name == "sqlite":
        _rebuild_sqlite_table(engine, "audit_logs")
        return
    if engine.dialect.name != "postgresql":
        return

    statements = []
    if actor_column is None:
        statements.append("ALTER TABLE audit_logs ADD COLUMN actor_id VARCHAR(26)")
    elif actor_column.get("nullable") is False:
        statements.append(
            "ALTER TABLE audit_logs ALTER COLUMN actor_id DROP NOT NULL"
        )
    if team_column is not None and team_column.get("nullable") is False:
        statements.append(
            "ALTER TABLE audit_logs ALTER COLUMN team_id DROP NOT NULL"
        )
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))


_IDENTIFIER_LENGTHS = {
    "chunks": {"id": 68},
    "chunk_history": {"chunk_id": 68},
    "messages": {"trace_id": 36},
    "retrieval_traces": {"trace_id": 36},
}


def _identifier_columns_to_widen(engine: Engine) -> dict:
    inspector = inspect(engine)
    pending = {}
    for table_name, columns in _IDENTIFIER_LENGTHS.items():
        if not inspector.has_table(table_name):
            continue
        current = {
            column["name"]: column["type"]
            for column in inspector.get_columns(table_name)
        }
        for column_name, minimum_length in columns.items():
            length = getattr(current.get(column_name), "length", None)
            if length is not None and length < minimum_length:
                pending.setdefault(table_name, {})[column_name] = minimum_length
    return pending


def _rebuild_sqlite_table(engine: Engine, table_name: str) -> None:
    table = Base.metadata.tables[table_name]
    temporary_name = "__techvault_migration_" + table_name
    temporary_metadata = MetaData()
    for existing_table in Base.metadata.sorted_tables:
        existing_table.to_metadata(
            temporary_metadata,
            name=temporary_name if existing_table is table else existing_table.name,
        )
    temporary_table = temporary_metadata.tables[temporary_name]
    preparer = engine.dialect.identifier_preparer

    with engine.connect() as connection:
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            for index in inspect(connection).get_indexes(table_name):
                if index.get("name"):
                    connection.exec_driver_sql(
                        "DROP INDEX IF EXISTS "
                        + preparer.quote(index["name"])
                    )

            connection.execute(CreateTable(temporary_table))
            old_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(" + preparer.quote(table_name) + ")"
                )
            }
            copied_columns = [
                column.name for column in table.columns if column.name in old_columns
            ]
            if copied_columns:
                quoted_columns = ", ".join(
                    preparer.quote(column_name) for column_name in copied_columns
                )
                connection.exec_driver_sql(
                    "INSERT INTO {temporary} ({columns}) SELECT {columns} FROM {source}".format(
                        temporary=preparer.quote(temporary_name),
                        columns=quoted_columns,
                        source=preparer.quote(table_name),
                    )
                )
            connection.exec_driver_sql(
                "DROP TABLE " + preparer.quote(table_name)
            )
            connection.exec_driver_sql(
                "ALTER TABLE {temporary} RENAME TO {source}".format(
                    temporary=preparer.quote(temporary_name),
                    source=preparer.quote(table_name),
                )
            )
            for index in table.indexes:
                connection.execute(CreateIndex(index))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def _widen_postgresql_identifiers(engine: Engine, pending: dict) -> None:
    inspector = inspect(engine)
    chunk_history_foreign_keys = []
    if "chunks" in pending or "chunk_history" in pending:
        chunk_history_foreign_keys = [
            foreign_key
            for foreign_key in inspector.get_foreign_keys("chunk_history")
            if foreign_key.get("referred_table") == "chunks"
        ]

    preparer = engine.dialect.identifier_preparer
    with engine.begin() as connection:
        for foreign_key in chunk_history_foreign_keys:
            if foreign_key.get("name"):
                connection.execute(
                    text(
                        "ALTER TABLE {table} DROP CONSTRAINT {constraint}".format(
                            table=preparer.quote("chunk_history"),
                            constraint=preparer.quote(foreign_key["name"]),
                        )
                    )
                )
        for table_name, columns in pending.items():
            for column_name, length in columns.items():
                connection.execute(
                    text(
                        "ALTER TABLE {table} ALTER COLUMN {column} "
                        "TYPE VARCHAR({length})".format(
                            table=preparer.quote(table_name),
                            column=preparer.quote(column_name),
                            length=length,
                        )
                    )
                )
        for foreign_key in chunk_history_foreign_keys:
            if foreign_key.get("name"):
                constrained = foreign_key.get("constrained_columns") or []
                referred = foreign_key.get("referred_columns") or []
                connection.execute(
                    text(
                        "ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                        "FOREIGN KEY ({columns}) REFERENCES chunks ({referred})".format(
                            table=preparer.quote("chunk_history"),
                            constraint=preparer.quote(foreign_key["name"]),
                            columns=", ".join(preparer.quote(item) for item in constrained),
                            referred=", ".join(preparer.quote(item) for item in referred),
                        )
                    )
                )


def _bridge_identifier_lengths(engine: Engine) -> None:
    pending = _identifier_columns_to_widen(engine)
    if not pending:
        return
    if engine.dialect.name == "sqlite":
        for table_name in _IDENTIFIER_LENGTHS:
            if table_name in pending:
                _rebuild_sqlite_table(engine, table_name)
        return
    if engine.dialect.name == "postgresql":
        _widen_postgresql_identifiers(engine, pending)


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _bridge_teams_description(engine)
    _bridge_users_admin_flags(engine)
    _bridge_document_object_uri(engine)
    _bridge_document_lifecycle(engine)
    _bridge_chunks_scope(engine)
    _bridge_chunk_overrides(engine)
    _bridge_kb_policy(engine)
    _bridge_index_generation_validation(engine)
    _bridge_invitation_expiry(engine)
    _bridge_credential_encryption(engine)
    _bridge_model_provider_api_key(engine)
    _bridge_evaluation_run_provider(engine)
    _bridge_audit_log_nullability(engine)
    _bridge_trace_rewrite(engine)
    _bridge_identifier_lengths(engine)


def _bridge_trace_rewrite(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("retrieval_traces"):
        return
    columns = {
        column["name"]
        for column in inspector.get_columns("retrieval_traces")
    }
    if "rewrite" in columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE retrieval_traces "
                "ADD COLUMN rewrite TEXT NOT NULL DEFAULT '{}'"
            )
        )
