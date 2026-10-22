from sqlalchemy import inspect, text

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


def test_create_schema_adds_description_to_legacy_teams_table():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE teams (id VARCHAR(26) PRIMARY KEY)"))

    create_schema(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("teams")}
    assert "description" in columns




def test_create_schema_adds_provider_fields_to_legacy_evaluation_runs_table():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE evaluation_runs ("
                "id VARCHAR(26) PRIMARY KEY, "
                "dataset_id VARCHAR(26) NOT NULL, "
                "engine_mode VARCHAR(20) NOT NULL, "
                "status VARCHAR(16) NOT NULL, "
                "baseline_run_id VARCHAR(26), "
                "created_by VARCHAR(26) NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL"
                ")"
            )
        )

    create_schema(engine)
    create_schema(engine)
    columns = {
        column["name"] for column in inspect(engine).get_columns("evaluation_runs")
    }

    assert {"provider_id", "model_id"}.issubset(columns)


def test_identifier_columns_use_runtime_lengths():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    inspector = inspect(engine)

    def length(table_name, column_name):
        columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        return columns[column_name]["type"].length

    assert length("chunks", "id") == 68
    assert length("chunk_history", "chunk_id") == 68
    assert length("messages", "trace_id") == 36
    assert length("retrieval_traces", "trace_id") >= 36


def test_create_schema_widens_legacy_identifier_columns():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE chunks (id VARCHAR(26) PRIMARY KEY, "
                 "document_id VARCHAR(26) NOT NULL, content TEXT NOT NULL)")
        )
        connection.execute(
            text("CREATE TABLE chunk_history (id VARCHAR(26) PRIMARY KEY, "
                 "chunk_id VARCHAR(26) NOT NULL)")
        )
        connection.execute(
            text("CREATE TABLE messages (id VARCHAR(26) PRIMARY KEY, trace_id VARCHAR(26))")
        )
        connection.execute(
            text("CREATE TABLE retrieval_traces (id VARCHAR(26) PRIMARY KEY, "
                 "trace_id VARCHAR(64))")
        )

    create_schema(engine)
    create_schema(engine)
    inspector = inspect(engine)

    def length(table_name, column_name):
        columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        return columns[column_name]["type"].length

    assert length("chunks", "id") == 68
    assert length("chunk_history", "chunk_id") == 68
    assert length("messages", "trace_id") == 36
    assert length("retrieval_traces", "trace_id") >= 36


def test_create_schema_adds_chunk_auto_content_and_override_table():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE chunks ("
                "id VARCHAR(68) PRIMARY KEY, "
                "document_id VARCHAR(26) NOT NULL, "
                "content TEXT NOT NULL"
                ")"
            )
        )
        connection.execute(
            text(
                "INSERT INTO chunks (id, document_id, content) "
                "VALUES ('chk_legacy', 'doc_legacy', 'Automatic legacy content')"
            )
        )

    create_schema(engine)
    inspector = inspect(engine)

    columns = {column["name"] for column in inspector.get_columns("chunks")}
    assert "auto_content" in columns
    assert inspector.has_table("chunk_overrides")
    override_columns = {
        column["name"] for column in inspector.get_columns("chunk_overrides")
    }
    assert {
        "logical_chunk_key",
        "content",
        "manual_status",
        "status",
        "pending_reason",
        "applied_chunk_id",
    }.issubset(override_columns)

    with engine.connect() as connection:
        auto_content = connection.execute(
            text("SELECT auto_content FROM chunks WHERE id = 'chk_legacy'")
        ).scalar_one()
    assert auto_content == "Automatic legacy content"


def test_create_schema_adds_rewrite_to_legacy_retrieval_traces():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE retrieval_traces ("
                "id VARCHAR(26) PRIMARY KEY, "
                "team_id VARCHAR(26) NOT NULL, "
                "trace_id VARCHAR(36) NOT NULL, "
                "original_query TEXT NOT NULL"
                ")"
            )
        )

    create_schema(engine)
    create_schema(engine)
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("retrieval_traces")
    }
    assert "rewrite" in columns
