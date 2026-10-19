import asyncio

from sqlalchemy import select

import backend.app.rag.indexing.generation as generation_module
from backend.app.core.config import Settings
from backend.app.db.models import (
    ChunkOverride,
    ChunkRecord,
    Document,
    IndexGenerationRecord,
    KnowledgeBase,
    Team,
    User,
)
from backend.app.db.session import build_engine, build_session_factory, create_schema
from backend.app.rag.domain.models import ValidationResult
from backend.app.workers.tasks import reindex_generation_record


class _Writer:
    def __init__(self, *, validation=None, fail_activation=False):
        self.validation = validation
        self.fail_activation = fail_activation
        self.staged = []
        self.validated = []
        self.activated = []

    async def stage(self, generation_id, chunks):
        self.staged.append((generation_id, list(chunks)))

    async def validate(self, generation_id):
        self.validated.append(generation_id)
        if self.validation is not None:
            return self.validation
        chunks = self.staged[-1][1]
        return ValidationResult(True, (), len(chunks))

    async def activate(self, generation_id):
        if self.fail_activation:
            raise RuntimeError("activation unavailable")
        self.activated.append(generation_id)


def _settings(engine_mode="dual_engine"):
    return Settings(
        environment="test",
        jwt_secret="test-secret-at-least-32-bytes-long",
        enable_indexing=True,
        engine_mode=engine_mode,
    )


def _seed_generation(
    monkeypatch,
    *,
    validation=None,
    fail_activation=False,
    chunks_in_staging=False,
):
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    factory = build_session_factory(engine)
    writer = _Writer(validation=validation, fail_activation=fail_activation)
    modes = []

    def build_writers(_settings, mode):
        modes.append(mode)
        return [writer]

    monkeypatch.setattr(generation_module, "build_index_writers", build_writers)
    monkeypatch.setattr(
        generation_module.EmbeddingClient,
        "embed",
        lambda self, texts: [[0.1, 0.2] for _ in texts],
    )

    with factory() as session:
        user = User(
            email="generation@example.com",
            display_name="Generation",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        team = Team(name="Generation Team", created_by=user.id)
        session.add(team)
        session.flush()
        kb = KnowledgeBase(team_id=team.id, name="Generation KB", created_by=user.id)
        session.add(kb)
        session.flush()
        document = Document(
            knowledge_base_id=kb.id,
            owner_user_id=user.id,
            file_name="guide.md",
            doc_status="active",
        )
        session.add(document)
        session.flush()
        old = IndexGenerationRecord(
            team_id=team.id,
            status="active",
            chunk_count=2,
        )
        staging = IndexGenerationRecord(
            team_id=team.id,
            status="staging",
            chunk_count=0,
        )
        session.add_all([old, staging])
        session.flush()
        for index in (1, 2):
            session.add(
                ChunkRecord(
                    document_id=document.id,
                    team_id=team.id,
                    knowledge_base_id=kb.id,
                    owner_user_id=user.id,
                    content="Enabled content {0}".format(index),
                    heading_path='["Guide"]',
                    source_locator="{}",
                    version_values="[]",
                    logical_chunk_key="guide.md#section-{0}".format(index),
                    content_hash="hash-{0}".format(index),
                    source_path="guide.md",
                    index_generation=staging.id if chunks_in_staging else old.id,
                    status="enabled",
                    chunk_status="enabled",
                    doc_status="active",
                )
            )
        session.commit()
        return factory, team.id, old.id, staging.id, writer, modes


def test_reindex_generation_stages_validates_and_activates_enabled_chunks(monkeypatch):
    factory, team_id, old_id, staging_id, writer, modes = _seed_generation(monkeypatch)

    with factory() as session:
        result = reindex_generation_record(session, staging_id, _settings())

        assert result["status"] == "active"
        assert result["checked_chunks"] == 2
        assert session.get(IndexGenerationRecord, old_id).status == "validated"
        assert session.get(IndexGenerationRecord, staging_id).status == "active"
        chunks = session.scalars(
            select(ChunkRecord).where(ChunkRecord.team_id == team_id)
        ).all()
        assert {chunk.index_generation for chunk in chunks} == {staging_id}
    assert writer.validated == [staging_id]
    assert writer.activated == [staging_id]
    assert modes == [generation_module.EngineMode.DUAL_ENGINE]


def test_reindex_generation_failure_keeps_previous_active_generation(monkeypatch):
    factory, _team_id, old_id, staging_id, writer, _modes = _seed_generation(
        monkeypatch,
        validation=ValidationResult(False, ("index count mismatch",), 1),
    )

    with factory() as session:
        result = reindex_generation_record(session, staging_id, _settings())

        staging = session.get(IndexGenerationRecord, staging_id)
        assert result["status"] == "failed"
        assert staging.status == "failed"
        assert "index count mismatch" in staging.validation_errors
        assert session.get(IndexGenerationRecord, old_id).status == "active"
    assert writer.activated == []


def test_reindex_activation_failure_keeps_previous_active_generation(monkeypatch):
    factory, _team_id, old_id, staging_id, writer, _modes = _seed_generation(
        monkeypatch,
        fail_activation=True,
    )

    with factory() as session:
        result = reindex_generation_record(session, staging_id, _settings())

        staging = session.get(IndexGenerationRecord, staging_id)
        assert result["status"] == "failed"
        assert staging.status == "failed"
        assert "activation failed" in staging.validation_errors
        assert session.get(IndexGenerationRecord, old_id).status == "active"
    assert writer.activated == []


def test_reindex_generation_applies_active_manual_override(monkeypatch):
    factory, team_id, _old_id, staging_id, writer, _modes = _seed_generation(monkeypatch)

    with factory() as session:
        chunk = session.scalar(
            select(ChunkRecord).where(ChunkRecord.team_id == team_id)
        )
        chunk.auto_content = chunk.content
        session.add(
            ChunkOverride(
                team_id=team_id,
                document_id=chunk.document_id,
                source_path=chunk.source_path,
                logical_chunk_key=chunk.logical_chunk_key,
                content="Manual content used by every rebuild.",
                manual_status="enabled",
                status="active",
                source_chunk_id=chunk.id,
                applied_chunk_id=chunk.id,
                created_by=chunk.owner_user_id,
                updated_by=chunk.owner_user_id,
            )
        )
        session.commit()

        result = reindex_generation_record(session, staging_id, _settings())

        assert result["status"] == "active"
        staged_chunks = writer.staged[-1][1]
        manual = next(
            item for item in staged_chunks if item.logical_chunk_key == chunk.logical_chunk_key
        )
        assert manual.content == "Manual content used by every rebuild."


def test_generation_validation_compares_postgres_and_writer_counts(monkeypatch):
    factory, _team_id, _old_id, staging_id, writer, _modes = _seed_generation(
        monkeypatch,
        validation=ValidationResult(True, (), 1),
        chunks_in_staging=True,
    )

    with factory() as session:
        generation = session.get(IndexGenerationRecord, staging_id)
        result = asyncio.run(
            generation_module.validate_existing_generation(
                session,
                generation,
                _settings(),
            )
        )

        assert result["passed"] is False
        assert result["checked_chunks"] == 2
        assert any("index count mismatch" in error for error in result["errors"])
        assert "index count mismatch" in generation.validation_errors
    assert writer.staged == [(staging_id, [])]
    assert writer.validated == [staging_id]
