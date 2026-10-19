import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError, StatementError

from backend.app.db.models import KnowledgeBase, Team, TeamMember, User
from backend.app.db.session import build_engine, build_session_factory, create_schema


def _session_factory():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    return build_session_factory(engine)


def _session():
    return _session_factory()()


def test_models_store_team_membership_and_knowledge_base():
    with _session() as session:
        user = User(
            email="leader@example.com",
            display_name="Leader",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        team = Team(name="Platform", created_by=user.id)
        session.add(team)
        session.flush()
        session.add(
            TeamMember(
                team_id=team.id,
                user_id=user.id,
                role="leader",
                status="active",
            )
        )
        session.add(
            KnowledgeBase(
                team_id=team.id,
                name="Java",
                created_by=user.id,
            )
        )
        session.commit()

        assert session.get(User, user.id).email == "leader@example.com"
        assert session.get(Team, team.id).name == "Platform"
        assert session.get(TeamMember, (team.id, user.id)).role == "leader"
        assert session.query(KnowledgeBase).one().name == "Java"


def test_user_email_is_unique():
    with _session() as session:
        session.add(
            User(email="same@example.com", display_name="A", password_hash="hash")
        )
        session.commit()
        session.add(
            User(email="same@example.com", display_name="B", password_hash="hash")
        )

        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate email should have failed")


def test_persisted_timestamps_are_returned_as_aware_utc_datetimes():
    factory = _session_factory()
    local_time = datetime(
        2026,
        1,
        2,
        12,
        30,
        tzinfo=timezone(timedelta(hours=8)),
    )
    expected_utc = datetime(2026, 1, 2, 4, 30, tzinfo=timezone.utc)

    with factory() as session:
        user = User(
            email="utc@example.com",
            display_name="UTC",
            password_hash="hash",
            created_at=local_time,
            updated_at=local_time,
        )
        session.add(user)
        session.flush()
        team = Team(
            name="UTC Team",
            created_by=user.id,
            created_at=local_time,
            updated_at=local_time,
        )
        session.add(team)
        session.flush()
        session.add(
            TeamMember(
                team_id=team.id,
                user_id=user.id,
                role="leader",
                joined_at=local_time,
            )
        )
        session.add(
            KnowledgeBase(
                team_id=team.id,
                name="UTC KB",
                created_by=user.id,
                created_at=local_time,
                updated_at=local_time,
            )
        )
        session.commit()
        user_id = user.id
        team_id = team.id

    with factory() as session:
        user = session.get(User, user_id)
        team = session.get(Team, team_id)
        member = session.get(TeamMember, (team_id, user_id))
        knowledge_base = session.query(KnowledgeBase).one()
        timestamps = (
            user.created_at,
            user.updated_at,
            team.created_at,
            team.updated_at,
            member.joined_at,
            knowledge_base.created_at,
            knowledge_base.updated_at,
        )

        for timestamp in timestamps:
            assert timestamp.tzinfo is not None
            assert timestamp.utcoffset() == timedelta(0)
            assert timestamp == expected_utc


def test_naive_datetime_is_rejected_on_bind():
    with _session() as session:
        session.add(
            User(
                email="naive@example.com",
                display_name="Naive",
                password_hash="hash",
                created_at=datetime(2026, 1, 2, 12, 30),
            )
        )

        with pytest.raises(StatementError, match="timezone-aware") as error:
            session.commit()

        assert isinstance(error.value.orig, ValueError)


def test_orphan_team_member_is_rejected():
    with _session() as session:
        session.add(
            TeamMember(
                team_id="missing-team",
                user_id="missing-user",
                role="member",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_orphan_knowledge_base_is_rejected():
    with _session() as session:
        session.add(
            KnowledgeBase(
                team_id="missing-team",
                name="Orphan",
                created_by="missing-user",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_knowledge_base_name_is_unique_within_team():
    with _session() as session:
        user = User(
            email="kb@example.com",
            display_name="KB",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        team = Team(name="Platform", created_by=user.id)
        session.add(team)
        session.flush()
        session.add(
            KnowledgeBase(team_id=team.id, name="Java", created_by=user.id)
        )
        session.commit()
        session.add(
            KnowledgeBase(team_id=team.id, name="Java", created_by=user.id)
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_team_and_knowledge_base_versions_default_and_change():
    factory = _session_factory()

    with factory() as session:
        user = User(
            email="version@example.com",
            display_name="Version",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        team = Team(name="Platform", created_by=user.id)
        session.add(team)
        session.flush()
        knowledge_base = KnowledgeBase(
            team_id=team.id,
            name="Java",
            created_by=user.id,
        )
        session.add(knowledge_base)
        session.commit()
        assert team.version == 1
        assert knowledge_base.version == 1
        team_id = team.id
        knowledge_base_id = knowledge_base.id

    with factory() as session:
        team = session.get(Team, team_id)
        knowledge_base = session.get(KnowledgeBase, knowledge_base_id)
        team.version = 2
        knowledge_base.version = 2
        session.commit()

    with factory() as session:
        assert session.get(Team, team_id).version == 2
        assert session.get(KnowledgeBase, knowledge_base_id).version == 2


def test_updated_at_changes_when_row_is_updated():
    factory = _session_factory()

    with factory() as session:
        user = User(
            email="updated@example.com",
            display_name="Updated",
            password_hash="hash",
        )
        session.add(user)
        session.flush()
        team = Team(name="Original", created_by=user.id)
        session.add(team)
        session.commit()
        team_id = team.id

    with factory() as session:
        team = session.get(Team, team_id)
        previous_updated_at = team.updated_at
        time.sleep(0.01)
        team.name = "Renamed"
        session.commit()

    with factory() as session:
        assert session.get(Team, team_id).updated_at > previous_updated_at
