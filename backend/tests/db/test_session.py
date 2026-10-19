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

    create_schema(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("teams")}
    assert "description" in columns
