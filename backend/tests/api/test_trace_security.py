import json
from uuid import uuid4

from backend.app.db.models import Chat, TeamMember, TraceRecord
from backend.tests.api.conftest import create_user_as_admin, login_headers


def test_trace_requires_owner_leader_or_admin_and_never_returns_content(
    api_client, api_app, admin_headers
):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Trace Team"},
        headers=admin_headers,
    ).json()["data"]
    create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "trace-owner@example.com",
        role="member",
        display_name="Trace Owner",
    )
    create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "trace-outsider@example.com",
        role="member",
        display_name="Trace Outsider",
    )
    owner_headers = login_headers(api_client, "trace-owner@example.com")
    outsider_headers = login_headers(api_client, "trace-outsider@example.com")
    chat = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "knowledge_base_ids": []},
        headers=owner_headers,
    ).json()["data"]
    trace_id = str(uuid4())

    with api_app.state.session_factory() as session:
        session.add(
            TraceRecord(
                team_id=team["id"],
                chat_id=chat["id"],
                trace_id=trace_id,
                engine_mode="dual_engine",
                original_query="private query",
                filters=json.dumps({"viewer_user_id": chat["user_id"]}),
                final_context=json.dumps(
                    [
                        {
                            "chunk_id": "chk_private",
                            "document_id": "doc_private",
                            "document_version_id": "ver_private",
                            "source_locator": {"page_no": 2},
                            "content": "TOP SECRET PRIVATE BODY",
                        }
                    ],
                    ensure_ascii=False,
                ),
            )
        )
        session.commit()

    with api_app.state.session_factory() as session:
        stored = session.query(TraceRecord).filter_by(trace_id=trace_id).one()
        assert "TOP SECRET" not in stored.final_context
        assert json.loads(stored.final_context)[0]["chunk_id"] == "chk_private"

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
    outsider_export = api_client.get(
        "/api/v1/traces/export",
        params={"team_id": team["id"], "trace_id": trace_id},
        headers=outsider_headers,
    )
    assert outsider_list.json()["data"] == []
    assert outsider_detail.status_code == 403
    assert outsider_export.status_code == 403

    for headers in (owner_headers, admin_headers):
        detail = api_client.get(
            "/api/v1/traces/detail",
            params={"team_id": team["id"], "trace_id": trace_id},
            headers=headers,
        )
        assert detail.status_code == 200, detail.text
        assert "TOP SECRET" not in detail.text
        final_context = detail.json()["data"]["final_context"]
        assert final_context == [
            {
                "chunk_id": "chk_private",
                "document_id": "doc_private",
                "document_version_id": "ver_private",
                "source_locator": {"page_no": 2},
            }
        ]

    owner_list = api_client.get(
        "/api/v1/traces",
        params={"team_id": team["id"]},
        headers=owner_headers,
    )
    assert [row["trace_id"] for row in owner_list.json()["data"]] == [trace_id]


def test_super_admin_can_read_team_trace_without_team_membership(
    api_client, api_app, admin_headers
):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Trace Admin Team"},
        headers=admin_headers,
    ).json()["data"]
    admin_id = api_client.get("/api/v1/auth/me", headers=admin_headers).json()["data"][
        "user"
    ]["id"]
    trace_id = str(uuid4())

    with api_app.state.session_factory() as session:
        membership = session.get(TeamMember, (team["id"], admin_id))
        assert membership is not None
        session.delete(membership)
        session.add(
            TraceRecord(
                team_id=team["id"],
                trace_id=trace_id,
                engine_mode="dual_engine",
                original_query="admin-visible query",
            )
        )
        session.commit()

    listing = api_client.get(
        "/api/v1/traces",
        params={"team_id": team["id"]},
        headers=admin_headers,
    )
    assert listing.status_code == 200, listing.text
    assert [row["trace_id"] for row in listing.json()["data"]] == [trace_id]

    detail = api_client.get(
        "/api/v1/traces/detail",
        params={"team_id": team["id"], "trace_id": trace_id},
        headers=admin_headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["trace_id"] == trace_id
