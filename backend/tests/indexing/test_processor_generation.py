from pathlib import Path

from sqlalchemy import select

import backend.app.rag.ingestion.processor as processor_module
from backend.app.core.config import Settings
from backend.app.db.models import (
    ChunkRecord,
    Document,
    DocumentVersion,
    IndexGenerationRecord,
    IngestionRun,
    KnowledgeBase,
    Team,
    TeamMember,
    User,
)
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.rag.domain.models import ValidationResult
from backend.app.rag.ingestion.processor import process_document
from backend.app.rag.retrieval.config import EngineMode


class _Writer:
    def __init__(self):
        self.generations = []
        self.staged_statuses = []
        self.deleted_chunk_batches = []
        self.document_statuses = []

    async def stage(self, generation_id, chunks):
        self.generations.append(generation_id)
        self.staged_statuses.append(
            [chunk.doc_status.value for chunk in chunks]
        )

    async def delete_chunks(self, generation_id, chunk_ids):
        self.deleted_chunk_batches.append((generation_id, tuple(chunk_ids)))

    async def set_document_status(self, generation_id, document_id, status):
        self.document_statuses.append((generation_id, document_id, status))

    async def validate(self, generation_id):
        return ValidationResult(True, (), 1)

    async def activate(self, generation_id):
        return None


def test_ingestion_creates_and_reuses_team_active_generation(tmp_path, monkeypatch):
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    session_factory = build_session_factory(engine)
    writer = _Writer()
    writer_modes = []

    def build_writers(_settings, mode):
        writer_modes.append(mode)
        return [writer]

    monkeypatch.setattr(processor_module, "build_index_writers", build_writers)
    monkeypatch.setattr(
        processor_module.EmbeddingClient,
        "embed",
        lambda self, texts: [[0.1, 0.2] for _ in texts],
    )
    settings = Settings(
        environment="test",
        jwt_secret="test-secret-at-least-32-bytes-long",
        enable_indexing=True,
        engine_mode="elastic_single",
    )

    with session_factory() as session:
        user = User(
            email="owner@example.com",
            display_name="Owner",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        team = Team(name="Index Team", created_by=user.id)
        session.add(team)
        session.flush()
        session.add(
            TeamMember(team_id=team.id, user_id=user.id, role="leader", status="active")
        )
        kb = KnowledgeBase(team_id=team.id, name="Index KB", created_by=user.id)
        session.add(kb)
        session.flush()

        documents = []
        for index in (1, 2):
            path = tmp_path / ("doc{0}.md".format(index))
            path.write_text("# Section\nContent {0}\n".format(index), encoding="utf-8")
            document = Document(
                knowledge_base_id=kb.id,
                owner_user_id=user.id,
                file_name=path.name,
                source_uri=str(path),
            )
            session.add(document)
            session.flush()
            version = DocumentVersion(
                document_id=document.id,
                content_fingerprint="fp-{0}".format(index),
                file_size_bytes=path.stat().st_size,
            )
            session.add(version)
            session.flush()
            document.current_version_id = version.id
            run = IngestionRun(document_version_id=version.id, status="queued")
            session.add(run)
            session.commit()
            documents.append((document, run))

        for document, run in documents:
            process_document(document, run, session, settings)

        rebuilt_document, _ = documents[0]
        rebuilt_document.doc_status = "building"
        rebuilt_run = IngestionRun(
            document_version_id=rebuilt_document.current_version_id,
            status="queued",
        )
        session.add(rebuilt_run)
        session.commit()
        process_document(rebuilt_document, rebuilt_run, session, settings)

        generations = session.scalars(select(IndexGenerationRecord)).all()
        assert len(generations) == 1
        assert generations[0].status == "active"
        assert generations[0].chunk_count == len(
            session.scalars(select(ChunkRecord)).all()
        )
        assert set(writer.generations) == {generations[0].id}
        assert all(
            chunk.index_generation == generations[0].id
            for chunk in session.scalars(select(ChunkRecord)).all()
        )
        assert writer_modes == [
            EngineMode.ELASTIC_SINGLE,
            EngineMode.ELASTIC_SINGLE,
            EngineMode.ELASTIC_SINGLE,
        ]
        assert writer.staged_statuses
        assert all(
            set(statuses) <= {"building"}
            for statuses in writer.staged_statuses
        )
        assert writer.document_statuses
        assert all(status == "active" for _, _, status in writer.document_statuses)
