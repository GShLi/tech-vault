import json
from uuid import uuid4

from backend.app.db.models import TraceRecord


def test_trace_detail_returns_rewrite_metadata(
    api_client, api_app, admin_headers
):
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Rewrite Trace Team"},
        headers=admin_headers,
    ).json()["data"]
    chat = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "knowledge_base_ids": []},
        headers=admin_headers,
    ).json()["data"]
    trace_id = str(uuid4())
    rewrite = {
        "original_query": "它怎么开启？",
        "rewritten_query": "Spring Boot 3.2 如何开启虚拟线程？",
        "changed": True,
        "route": "openai_chat_completions",
        "model_id": "model-test",
        "structured_mode": "json_schema",
        "extracted_filters": {
            "product": "spring-boot",
            "version_values": ["3.2"],
        },
        "applied_filters": {
            "product": "spring-boot",
            "version_values": ["3.2"],
        },
        "dropped_filters": [],
    }

    with api_app.state.session_factory() as session:
        session.add(
            TraceRecord(
                team_id=team["id"],
                chat_id=chat["id"],
                trace_id=trace_id,
                original_query="它怎么开启？",
                rewritten_query="Spring Boot 3.2 如何开启虚拟线程？",
                rewrite=json.dumps(rewrite, ensure_ascii=False),
            )
        )
        session.commit()

    response = api_client.get(
        "/api/v1/traces/detail",
        params={"team_id": team["id"], "trace_id": trace_id},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["data"]["rewrite"] == rewrite
