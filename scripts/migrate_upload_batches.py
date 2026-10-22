"""Apply the development schema cutover for batch uploads (PostgreSQL only).

Run with the same TECHVAULT_* environment as the API, with API/workers stopped.
Removed GitHub connection/credential tables and obsolete vector cache are discarded.
Document, knowledge-base, model-provider and account records are preserved.
"""
from sqlalchemy import inspect, text

from backend.app.core.config import Settings
from backend.app.db.models import EmbeddingCache
from backend.app.db.session import build_engine, create_schema


def main():
    engine = build_engine(Settings.from_env().database_url)
    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("Use a fresh development database for non-PostgreSQL environments.")
        inspector = inspect(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS source_connections"))
            connection.execute(text("DROP TABLE IF EXISTS credentials"))
            if inspector.has_table("embedding_cache"):
                columns = {column["name"] for column in inspector.get_columns("embedding_cache")}
                if not {"team_id", "created_at"}.issubset(columns):
                    EmbeddingCache.__table__.drop(connection)
            if inspector.has_table("knowledge_bases"):
                connection.execute(text("ALTER TABLE knowledge_bases ALTER COLUMN model_policy_mode SET DEFAULT 'external_allowed'"))
            # The first development build created these FKs without delete actions.
            quote = engine.dialect.identifier_preparer.quote
            for table, column, parent, action in (
                ("upload_batch_files", "run_id", "ingestion_runs", "SET NULL"),
                ("upload_batch_files", "document_id", "documents", "SET NULL"),
                ("prepared_ingestions", "run_id", "ingestion_runs", "CASCADE"),
            ):
                if not inspector.has_table(table):
                    continue
                for fk in inspector.get_foreign_keys(table):
                    if fk["constrained_columns"] == [column] and fk.get("options", {}).get("ondelete") != action:
                        connection.execute(text(f"ALTER TABLE {quote(table)} DROP CONSTRAINT {quote(fk['name'])}"))
                        connection.execute(text(f"ALTER TABLE {quote(table)} ADD FOREIGN KEY ({quote(column)}) REFERENCES {quote(parent)} (id) ON DELETE {action}"))
        create_schema(engine)
        print("Batch upload schema ready; removed GitHub tables and obsolete cache.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
