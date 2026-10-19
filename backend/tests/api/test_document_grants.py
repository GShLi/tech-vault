from backend.app.api.v1.documents import _granted_document_ids
from backend.app.db.models import Document, DocumentGrant, KnowledgeBase, Team, User
from backend.app.db.session import build_engine, build_session_factory, create_schema


def test_granted_document_ids_are_scoped_by_team_and_user():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    create_schema(engine)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        owner = User(email="owner@example.com", display_name="Owner", password_hash="x")
        viewer = User(email="viewer@example.com", display_name="Viewer", password_hash="x")
        session.add_all([owner, viewer])
        session.flush()
        team = Team(name="Team A", created_by=owner.id)
        other_team = Team(name="Team B", created_by=owner.id)
        session.add_all([team, other_team])
        session.flush()
        kb = KnowledgeBase(team_id=team.id, name="KB A", created_by=owner.id)
        other_kb = KnowledgeBase(team_id=other_team.id, name="KB B", created_by=owner.id)
        session.add_all([kb, other_kb])
        session.flush()
        document = Document(
            knowledge_base_id=kb.id,
            owner_user_id=owner.id,
            file_name="private-a.md",
            visibility="private",
        )
        other_document = Document(
            knowledge_base_id=other_kb.id,
            owner_user_id=owner.id,
            file_name="private-b.md",
            visibility="private",
        )
        session.add_all([document, other_document])
        session.flush()
        session.add_all(
            [
                DocumentGrant(
                    document_id=document.id,
                    user_id=viewer.id,
                    granted_by=owner.id,
                ),
                DocumentGrant(
                    document_id=other_document.id,
                    user_id=viewer.id,
                    granted_by=owner.id,
                ),
            ]
        )
        session.commit()

        grants = _granted_document_ids(session, team.id, viewer.id)

    assert grants == (document.id,)
