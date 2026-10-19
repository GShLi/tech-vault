from sqlalchemy import select

from backend.app.db.models import Chat, Message


def _create_team(client, headers, name="Chats"):
    return client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    ).json()["data"]


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
