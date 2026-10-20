import json
from uuid import uuid4

from backend.app.db.models import (
    Chat,
    ChunkRecord,
    Document,
    KnowledgeBaseMember,
    TraceRecord,
)
from backend.tests.api.conftest import create_user_as_admin, login_headers


def _create_team(api_client, headers, name):
    return api_client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    ).json()["data"]


def _create_kb(api_client, headers, team_id, name):
    return api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team_id, "name": name},
        headers=headers,
    ).json()["data"]


def _trace_row(team_id, chat_id, trace_id, chunk_id):
    candidate = json.dumps(
        [{"chunk_id": chunk_id, "rank": 1, "score": 0.91}],
        ensure_ascii=False,
    )
    return TraceRecord(
        team_id=team_id,
        chat_id=chat_id,
        trace_id=trace_id,
        engine_mode="dual_engine",
        original_query="如何配置虚拟线程？",
        bm25_candidates=candidate,
        dense_candidates=candidate,
        rrf_candidates=candidate,
        rerank_candidates=candidate,
        final_context=candidate,
    )


def test_trace_detail_hydrates_authorized_chunk_content(
    api_client, api_app, admin_headers
):
    team = _create_team(api_client, admin_headers, "Trace Chunk Owner Team")
    owner = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "trace-chunk-owner@example.com",
        role="member",
        display_name="Trace Chunk Owner",
    )
    owner_headers = login_headers(api_client, "trace-chunk-owner@example.com")
    kb = _create_kb(api_client, admin_headers, team["id"], "Trace Chunk KB")
    chat = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "knowledge_base_ids": [kb["id"]]},
        headers=owner_headers,
    ).json()["data"]
    trace_id = str(uuid4())

    with api_app.state.session_factory() as session:
        session.add(
            KnowledgeBaseMember(
                kb_id=kb["id"],
                user_id=owner["user"]["id"],
                status="active",
                added_by=owner["user"]["id"],
            )
        )
        document = Document(
            knowledge_base_id=kb["id"],
            owner_user_id=owner["user"]["id"],
            file_name="virtual-threads.md",
            visibility="team_shared",
        )
        session.add(document)
        session.flush()
        session.add(
            ChunkRecord(
                id="trace-chunk-authorized",
                document_id=document.id,
                team_id=team["id"],
                knowledge_base_id=kb["id"],
                owner_user_id=owner["user"]["id"],
                content="设置 spring.threads.virtual.enabled=true 可启用虚拟线程。",
                heading_path=json.dumps(["Spring Boot", "线程配置"], ensure_ascii=False),
                source_locator=json.dumps(
                    {"page_no": 12, "heading_path": ["Spring Boot", "线程配置"]},
                    ensure_ascii=False,
                ),
                version_values=json.dumps(["3.2"]),
            )
        )
        session.add(
            _trace_row(
                team["id"],
                chat["id"],
                trace_id,
                "trace-chunk-authorized",
            )
        )
        session.commit()

    detail = api_client.get(
        "/api/v1/traces/detail",
        params={"team_id": team["id"], "trace_id": trace_id},
        headers=owner_headers,
    )
    assert detail.status_code == 200, detail.text
    chunk = detail.json()["data"]["chunk_details"]["trace-chunk-authorized"]
    assert chunk["content"] == "设置 spring.threads.virtual.enabled=true 可启用虚拟线程。"
    assert chunk["document_name"] == "virtual-threads.md"
    assert chunk["knowledge_base_name"] == "Trace Chunk KB"
    assert chunk["heading_path"] == ["Spring Boot", "线程配置"]
    assert chunk["source_locator"]["page_no"] == 12
    assert chunk["version_values"] == ["3.2"]

    listed = api_client.get(
        "/api/v1/traces",
        params={"team_id": team["id"]},
        headers=owner_headers,
    )
    assert listed.status_code == 200
    assert "chunk_details" not in listed.json()["data"][0]


def test_trace_detail_hides_other_users_private_chunk_content(
    api_client, api_app, admin_headers
):
    team = _create_team(api_client, admin_headers, "Trace Chunk Privacy Team")
    owner = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "trace-private-owner@example.com",
        role="member",
        display_name="Trace Private Owner",
    )
    leader = create_user_as_admin(
        api_client,
        admin_headers,
        team["id"],
        "trace-private-leader@example.com",
        role="leader",
        display_name="Trace Private Leader",
    )
    owner_headers = login_headers(api_client, "trace-private-owner@example.com")
    leader_headers = login_headers(api_client, "trace-private-leader@example.com")
    kb = _create_kb(api_client, admin_headers, team["id"], "Trace Private KB")
    chat = api_client.post(
        "/api/v1/chats/create",
        json={"team_id": team["id"], "knowledge_base_ids": [kb["id"]]},
        headers=owner_headers,
    ).json()["data"]
    trace_id = str(uuid4())

    with api_app.state.session_factory() as session:
        for user in (owner, leader):
            session.add(
                KnowledgeBaseMember(
                    kb_id=kb["id"],
                    user_id=user["user"]["id"],
                    status="active",
                    added_by=user["user"]["id"],
                )
            )
        document = Document(
            knowledge_base_id=kb["id"],
            owner_user_id=owner["user"]["id"],
            file_name="private-notes.md",
            visibility="private",
        )
        session.add(document)
        session.flush()
        session.add(
            ChunkRecord(
                id="trace-chunk-private",
                document_id=document.id,
                team_id=team["id"],
                knowledge_base_id=kb["id"],
                owner_user_id=owner["user"]["id"],
                content="仅文档所有者可见的私有内容。",
            )
        )
        session.add(
            _trace_row(
                team["id"],
                chat["id"],
                trace_id,
                "trace-chunk-private",
            )
        )
        session.commit()

    owner_detail = api_client.get(
        "/api/v1/traces/detail",
        params={"team_id": team["id"], "trace_id": trace_id},
        headers=owner_headers,
    )
    assert owner_detail.status_code == 200
    assert (
        owner_detail.json()["data"]["chunk_details"]["trace-chunk-private"]["content"]
        == "仅文档所有者可见的私有内容。"
    )

    leader_detail = api_client.get(
        "/api/v1/traces/detail",
        params={"team_id": team["id"], "trace_id": trace_id},
        headers=leader_headers,
    )
    assert leader_detail.status_code == 200
    restricted = leader_detail.json()["data"]["chunk_details"]["trace-chunk-private"]
    assert restricted == {"id": "trace-chunk-private", "restricted": True}
    assert "仅文档所有者可见的私有内容" not in leader_detail.text
