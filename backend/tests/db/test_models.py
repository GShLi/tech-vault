from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db.base import Base
from backend.app.db.models import KnowledgeBase, Team, TeamMember, User


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


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
