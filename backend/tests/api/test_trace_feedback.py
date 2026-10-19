import json
from uuid import uuid4

from backend.app.db.models import Feedback, Message, TraceRecord
from backend.tests.api.conftest import create_user_as_admin, login_headers


def test_trace_list_and_detail_include_feedback_without_weakening_access(
    api_client, api_app, admin_headers
):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Trace Feedback Team"},
        headers=admin_headers,
    ).json()["data"]
    owner = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "feedback-owner@example.com",
        role="member",
        display_name="Feedback Owner",
    )
    leader = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "feedback-leader@example.com",
        role="leader",
        display_name="Feedback Leader",
    )
    create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "feedback-outsider@example.com",
        role="member",
        display_name="Feedback Outsider",
    )
    owner_headers = login_headers(api_client, "feedback-owner@example.com")
    leader_headers = login_headers(api_client, "feedback-leader@example.com")
    outsider_headers = login_headers(api_client, "feedback-outsider@example.com")
    chat = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "knowledge_base_ids": []},
        headers=owner_headers,
    ).json()["data"]
    trace_id = str(uuid4())

    with api_app.state.session_factory() as session:
        message = Message(
            chat_id=chat["id"],
            role="assistant",
            content="Answer with feedback",
            status="completed",
        )
        session.add(message)
        session.flush()
        feedback = Feedback(
            team_id=team["id"],
            message_id=message.id,
            user_id=owner["user"]["id"],
            feedback_type="useful",
            comment="Resolved the issue.",
        )
        session.add(feedback)
        session.add(
            TraceRecord(
                team_id=team["id"],
                chat_id=chat["id"],
                message_id=message.id,
                trace_id=trace_id,
                engine_mode="dual_engine",
                original_query="How do I resolve this?",
                filters=json.dumps({"viewer_user_id": owner["user"]["id"]}),
            )
        )
        session.commit()
        feedback_id = feedback.id

    for headers in (owner_headers, leader_headers, admin_headers):
        detail = api_client.get(
            "/api/v1/traces/detail",
            params={"team_id": team["id"], "trace_id": trace_id},
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        feedback_rows = detail.json()["data"]["feedback"]
        assert len(feedback_rows) == 1
        assert feedback_rows[0]["id"] == feedback_id
        assert feedback_rows[0]["feedback_type"] == "useful"
        assert feedback_rows[0]["comment"] == "Resolved the issue."
        assert feedback_rows[0]["created_at"]
        assert set(feedback_rows[0]) == {
            "id",
            "feedback_type",
            "comment",
            "created_at",
        }

    owner_list = api_client.get(
        "/api/v1/traces",
        params={"team_id": team["id"]},
        headers=owner_headers,
    )
    assert owner_list.status_code == 200, owner_list.text
    assert owner_list.json()["data"][0]["feedback"][0]["feedback_type"] == "useful"

    outsider_list = api_client.get(
        "/api/v1/traces",
        params={"team_id": team["id"]},
        headers=outsider_headers,
    )
    outsider_detail = api_client.get(
        "/api/v1/traces/detail",
        params={"team_id": team["id"], "trace_id": trace_id},
        headers=outsider_headers,
    )
    assert outsider_list.headers["content-type"].startswith("application/json")
    assert outsider_list.json()["data"] == []
    assert outsider_detail.status_code == 403
    assert outsider_detail.json()["error"]["code"] == "PERMISSION_DENIED"
