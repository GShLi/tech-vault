from uuid import uuid4

from sqlalchemy import select

from backend.app.db.models import Chat, Feedback, Message, TraceRecord, User


def _create_team(client, headers, name="Chats"):
    return client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    ).json()["data"]


def test_chat_title_validation_rejects_null_on_update(api_client, admin_headers):
    team = _create_team(api_client, admin_headers, name="Chat title validation")
    created = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "title": None, "knowledge_base_ids": []},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["title"] == "新对话"

    invalid = api_client.post(
        "/api/v1/chats/update",
        json={"team_id": team["id"], "chat_id": created.json()["data"]["id"], "title": None},
        headers={**admin_headers, "If-Match": "1"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_ARGUMENT"


def test_chat_crud_and_message_cleanup(api_client, api_app, admin_headers):
    team = _create_team(api_client, admin_headers)
    created = api_client.post(
        "/api/v1/chats/create",
        json={
            "team_id": team["id"],
            "title": "Architecture questions",
            "knowledge_base_ids": [],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    chat = created.json()["data"]

    listed = api_client.get(
        "/api/v1/chats",
        params={"team_id": team["id"]},
        headers=admin_headers,
    )
    assert [item["id"] for item in listed.json()["data"]] == [chat["id"]]

    with api_app.state.session_factory() as session:
        session.add(
            Message(chat_id=chat["id"], role="user", content="hello")
        )
        session.commit()

    messages = api_client.get(
        "/api/v1/chats/messages",
        params={"team_id": team["id"], "chat_id": chat["id"]},
        headers=admin_headers,
    )
    assert messages.status_code == 200
    assert messages.json()["data"][0]["content"] == "hello"

    deleted = api_client.post(
        "/api/v1/chats/delete",
        json={"team_id": team["id"], "chat_id": chat["id"]},
        headers=admin_headers,
    )
    assert deleted.status_code == 200

    with api_app.state.session_factory() as session:
        assert session.get(Chat, chat["id"]) is None
        assert session.scalars(
            select(Message).where(Message.chat_id == chat["id"])
        ).all() == []


def test_delete_chat_removes_feedback_and_messages_but_retains_detached_trace(
    api_client, api_app, admin_headers
):
    team = _create_team(api_client, admin_headers, name="Chat Delete Audit")
    created = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "title": "Audited chat", "knowledge_base_ids": []},
        headers=admin_headers,
    )
    assert created.status_code == 201
    chat = created.json()["data"]
    trace_id = str(uuid4())

    with api_app.state.session_factory() as session:
        user = session.scalar(select(User).where(User.email == "admin@techvault.local"))
        assert user is not None
        message = Message(
            chat_id=chat["id"],
            role="assistant",
            content="Audited answer",
            status="completed",
            trace_id=trace_id,
        )
        session.add(message)
        session.flush()
        session.add_all(
            [
                Feedback(
                    team_id=team["id"],
                    message_id=message.id,
                    user_id=user.id,
                    feedback_type="useful",
                ),
                TraceRecord(
                    team_id=team["id"],
                    chat_id=chat["id"],
                    message_id=message.id,
                    trace_id=trace_id,
                    original_query="Audited question",
                ),
            ]
        )
        session.commit()
        message_id = message.id

    deleted = api_client.post(
        "/api/v1/chats/delete",
        json={"team_id": team["id"], "chat_id": chat["id"]},
        headers=admin_headers,
    )

    assert deleted.status_code == 200, deleted.text
    with api_app.state.session_factory() as session:
        assert session.get(Chat, chat["id"]) is None
        assert session.get(Message, message_id) is None
        assert session.scalar(
            select(Feedback).where(Feedback.message_id == message_id)
        ) is None
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.trace_id == trace_id)
        )
        assert trace is not None
        assert trace.original_query == "Audited question"
        assert trace.chat_id is None
        assert trace.message_id is None


def test_delete_chat_detaches_audit_trace_even_without_messages(
    api_client, api_app, admin_headers
):
    team = _create_team(api_client, admin_headers, name="Trace Only Delete")
    created = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "title": "Trace only", "knowledge_base_ids": []},
        headers=admin_headers,
    )
    assert created.status_code == 201
    chat = created.json()["data"]
    trace_id = str(uuid4())

    with api_app.state.session_factory() as session:
        session.add(
            TraceRecord(
                team_id=team["id"],
                chat_id=chat["id"],
                trace_id=trace_id,
                original_query="Trace without a message",
            )
        )
        session.commit()

    deleted = api_client.post(
        "/api/v1/chats/delete",
        json={"team_id": team["id"], "chat_id": chat["id"]},
        headers=admin_headers,
    )

    assert deleted.status_code == 200, deleted.text
    with api_app.state.session_factory() as session:
        trace = session.scalar(
            select(TraceRecord).where(TraceRecord.trace_id == trace_id)
        )
        assert trace is not None
        assert trace.chat_id is None
