import hashlib
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, update

from backend.app.db.models import (
    Chat,
    ChunkHistory,
    ChunkRecord,
    Credential,
    Document,
    DocumentGrant,
    DocumentVersion,
    EvaluationCase,
    EvaluationDataset,
    EvaluationRun,
    IngestionRun,
    KnowledgeBaseMember,
    Message,
    ModelCall,
    ModelProvider,
    SourceConnection,
    TeamMember,
    User,
)
from backend.tests.api.conftest import (
    ADMIN_EMAIL,
    admin_headers_for,
    create_user_as_admin,
    login_headers,
)


def _chunk_id(label: str) -> str:
    return "chk_" + hashlib.sha256(label.encode("utf-8")).hexdigest()


@pytest.fixture()
def pagination_context(api_client, api_app):
    headers = admin_headers_for(api_client)
    team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Pagination Team"},
        headers=headers,
    ).json()["data"]
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Pagination KB"},
        headers=headers,
    ).json()["data"]
    users = [
        create_user_as_admin(
            api_client,
            headers,
            team["id"],
            "page-member-{0}@example.com".format(index),
            display_name="Page Member {0}".format(index),
        )["user"]
        for index in (1, 2)
    ]

    timestamp = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    expected = {}
    with api_app.state.session_factory() as session:
        admin = session.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert admin is not None

        session.execute(
            update(TeamMember)
            .where(TeamMember.team_id == team["id"])
            .values(joined_at=timestamp)
        )

        sources = [
            SourceConnection(
                team_id=team["id"],
                kb_id=kb["id"],
                source_type="github",
                repo_url="https://github.com/acme/repo-{0}.git".format(index),
                branch="main",
                path_filters="[]",
                status="active",
                created_by=admin.id,
                created_at=timestamp,
            )
            for index in range(3)
        ]
        credentials = [
            Credential(
                team_id=team["id"],
                name="credential-{0}".format(index),
                secret_masked="****{0}".format(index),
                secret_encrypted="encrypted",
                created_by=admin.id,
                created_at=timestamp,
            )
            for index in range(3)
        ]
        document = Document(
            knowledge_base_id=kb["id"],
            owner_user_id=admin.id,
            file_name="pagination.md",
            source_type="upload",
            visibility="team_shared",
            data_classification="internal",
            doc_status="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add_all(sources + credentials + [document])
        session.flush()

        versions = [
            DocumentVersion(
                document_id=document.id,
                content_fingerprint="fingerprint-{0}".format(index),
                file_size_bytes=10 + index,
                status="active",
                chunk_count=1,
                created_at=timestamp,
            )
            for index in range(3)
        ]
        session.add_all(versions)
        session.flush()
        document.current_version_id = versions[-1].id

        tasks = [
            IngestionRun(
                document_version_id=version.id,
                status="completed",
                current_stage="completed",
                stage_progress_pct=100,
                created_at=timestamp,
                updated_at=timestamp,
            )
            for version in versions
        ]
        chunks = [
            ChunkRecord(
                id=_chunk_id("chunk-{0}".format(index)),
                document_id=document.id,
                team_id=team["id"],
                knowledge_base_id=kb["id"],
                owner_user_id=admin.id,
                content="chunk {0}".format(index),
                heading_path="[]",
                source_locator="{}",
                status="enabled",
                chunk_status="enabled",
                created_at=timestamp,
                updated_at=timestamp,
            )
            for index in range(3)
        ]
        chunk_history = [
            ChunkHistory(
                chunk_id=chunks[0].id,
                action="updated-{0}".format(index),
                actor_id=admin.id,
                created_at=timestamp,
            )
            for index in range(3)
        ]
        grants = [
            DocumentGrant(
                document_id=document.id,
                user_id=user_id,
                granted_by=admin.id,
                created_at=timestamp,
            )
            for user_id in [admin.id] + [user["id"] for user in users]
        ]
        session.add_all(tasks + chunks)
        session.flush()
        session.add_all(chunk_history + grants)

        dataset = EvaluationDataset(
            team_id=team["id"],
            name="Pagination Set",
            status="active",
            case_count=3,
            created_by=admin.id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(dataset)
        session.flush()
        cases = [
            EvaluationCase(
                dataset_id=dataset.id,
                query_id="query-{0}".format(index),
                query_type="concept",
                query="question {0}".format(index),
                created_at=timestamp,
            )
            for index in range(3)
        ]
        runs = [
            EvaluationRun(
                dataset_id=dataset.id,
                engine_mode="dual_engine",
                status="succeeded",
                created_by=admin.id,
                created_at=timestamp,
                updated_at=timestamp,
            )
            for index in range(3)
        ]
        session.add_all(cases + runs)

        chat = Chat(
            team_id=team["id"],
            user_id=admin.id,
            title="Pagination chat",
            knowledge_base_ids="[]",
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(chat)
        session.flush()
        messages = [
            Message(
                chat_id=chat.id,
                role="user" if index % 2 == 0 else "assistant",
                content="message {0}".format(index),
                status="completed",
                created_at=timestamp,
            )
            for index in range(3)
        ]
        session.add_all(messages)

        providers = [
            ModelProvider(
                team_id=team["id"] if index else None,
                name="provider-{0}".format(index),
                provider_type="openai_compatible",
                base_url="http://provider-{0}".format(index),
                model_ids=json.dumps(
                    ["model-{0}-a".format(index), "model-{0}-b".format(index)]
                    if index == 0
                    else ["model-{0}".format(index)]
                ),
                status="active",
                created_by=admin.id,
                created_at=timestamp,
            )
            for index in range(3)
        ]
        model_calls = [
            ModelCall(
                team_id=team["id"],
                model_id="model-{0}".format(index),
                purpose="answer",
                classification="internal",
                external=False,
                request_id="request-{0}".format(index),
                created_at=timestamp,
            )
            for index in range(3)
        ]
        session.add_all(providers + model_calls)

        session.add_all(
            [
                KnowledgeBaseMember(
                    kb_id=kb["id"],
                    user_id=user["id"],
                    status="active",
                    added_by=admin.id,
                    created_at=timestamp,
                )
                for user in users
            ]
        )
        session.execute(
            update(KnowledgeBaseMember)
            .where(KnowledgeBaseMember.kb_id == kb["id"])
            .values(created_at=timestamp)
        )
        session.commit()

        expected["members"] = sorted(
            [admin.id] + [user["id"] for user in users], reverse=True
        )
        expected["sources"] = sorted([row.id for row in sources], reverse=True)
        expected["credentials"] = sorted([row.id for row in credentials], reverse=True)
        expected["versions"] = sorted([row.id for row in versions], reverse=True)
        expected["tasks"] = sorted([row.id for row in tasks], reverse=True)
        expected["doc_chunks"] = sorted([row.id for row in chunks])
        expected["chunk_history"] = sorted(
            [row.id for row in chunk_history], reverse=True
        )
        expected["kb_members"] = sorted(
            [admin.id] + [user["id"] for user in users], reverse=True
        )
        expected["grants"] = [
            row.user_id
            for row in sorted(grants, key=lambda grant: grant.id, reverse=True)
        ]
        expected["datasets"] = [dataset.id]
        expected["cases"] = sorted([row.id for row in cases])
        expected["runs"] = sorted([row.id for row in runs], reverse=True)
        expected["messages"] = sorted([row.id for row in messages])
        expected["model_calls"] = sorted([row.id for row in model_calls], reverse=True)
        expected["providers"] = sorted([row.id for row in providers], reverse=True)
        expected["admin_providers"] = expected["providers"]
        ordered_providers = sorted(providers, key=lambda row: row.id, reverse=True)
        expected["admin_models"] = [
            model_id
            for provider in ordered_providers
            for model_id in json.loads(provider.model_ids)
        ]
        expected["document_id"] = document.id
        expected["chunk_id"] = chunks[0].id
        expected["dataset_id"] = dataset.id
        expected["chat_id"] = chat.id

    cases = [
        ("members", "/api/v1/members", {"team_id": team["id"]}, "user_id"),
        (
            "messages",
            "/api/v1/chats/messages",
            {"team_id": team["id"], "chat_id": expected["chat_id"]},
            "id",
        ),
        ("sources", "/api/v1/sources", {"team_id": team["id"]}, "id"),
        ("credentials", "/api/v1/credentials", {"team_id": team["id"]}, "id"),
        (
            "versions",
            "/api/v1/docs/versions",
            {"team_id": team["id"], "document_id": expected["document_id"]},
            "id",
        ),
        (
            "tasks",
            "/api/v1/docs/tasks",
            {"team_id": team["id"], "document_id": expected["document_id"]},
            "id",
        ),
        (
            "doc_chunks",
            "/api/v1/docs/chunks",
            {"team_id": team["id"], "document_id": expected["document_id"]},
            "id",
        ),
        (
            "chunk_history",
            "/api/v1/chunks/history",
            {"team_id": team["id"], "chunk_id": expected["chunk_id"]},
            "id",
        ),
        (
            "kb_members",
            "/api/v1/kbs/members",
            {"team_id": team["id"], "kb_id": kb["id"]},
            "user_id",
        ),
        (
            "grants",
            "/api/v1/docs/grants",
            {"team_id": team["id"], "document_id": expected["document_id"]},
            "user_id",
        ),
        ("datasets", "/api/v1/evals/datasets", {"team_id": team["id"]}, "id"),
        (
            "cases",
            "/api/v1/evals/datasets/cases",
            {"team_id": team["id"], "dataset_id": expected["dataset_id"]},
            "id",
        ),
        (
            "runs",
            "/api/v1/evals/runs",
            {"team_id": team["id"], "dataset_id": expected["dataset_id"]},
            "id",
        ),
        ("model_calls", "/api/v1/model-calls", {"team_id": team["id"]}, "id"),
        ("providers", "/api/v1/providers", {"team_id": team["id"]}, "id"),
        ("admin_providers", "/api/v1/admin/providers", {}, "id"),
        ("admin_models", "/api/v1/admin/models", {}, "model_id"),
    ]
    return {
        "headers": headers,
        "team": team,
        "kb": kb,
        "document_id": expected["document_id"],
        "dataset_id": expected["dataset_id"],
        "chat_id": expected["chat_id"],
        "member_headers": login_headers(
            api_client,
            email=users[0]["email"],
            password="password-123",
        ),
        "cases": [
            {
                "name": name,
                "path": path,
                "params": params,
                "item_key": item_key,
                "expected": expected[name],
            }
            for name, path, params, item_key in cases
        ],
    }


def test_p0_list_endpoints_walk_cursor_pages_without_truncation(
    api_client, pagination_context
):
    failures = []
    for case in pagination_context["cases"]:
        cursor = None
        values = []
        page_count = 0
        while True:
            params = {**case["params"], "limit": 1}
            if cursor is not None:
                params["cursor"] = cursor
            response = api_client.get(
                case["path"], params=params, headers=pagination_context["headers"]
            )
            if response.status_code != 200:
                failures.append(
                    "{0}: expected 200, got {1}: {2}".format(
                        case["name"], response.status_code, response.text
                    )
                )
                break
            body = response.json()
            meta = body.get("meta", {})
            if "next_cursor" not in meta or "has_more" not in meta:
                failures.append("{0}: missing page metadata: {1}".format(case["name"], meta))
                break
            values.extend(item[case["item_key"]] for item in body["data"])
            page_count += 1
            if not meta["has_more"]:
                if meta["next_cursor"] is not None:
                    failures.append(
                        "{0}: terminal page returned next_cursor".format(case["name"])
                    )
                break
            if meta["next_cursor"] is None:
                failures.append(
                    "{0}: has_more=true without next_cursor".format(case["name"])
                )
                break
            cursor = meta["next_cursor"]
            if page_count > len(case["expected"]) + 1:
                failures.append("{0}: pagination did not terminate".format(case["name"]))
                break
        if values != case["expected"]:
            failures.append(
                "{0}: expected {1}, got {2}".format(
                    case["name"], case["expected"], values
                )
            )
    assert failures == []


def test_p0_list_endpoints_reject_invalid_cursor(api_client, pagination_context):
    failures = []
    for case in pagination_context["cases"]:
        response = api_client.get(
            case["path"],
            params={**case["params"], "limit": 1, "cursor": "not-a-cursor"},
            headers=pagination_context["headers"],
        )
        if response.status_code != 400:
            failures.append(
                "{0}: expected 400, got {1}: {2}".format(
                    case["name"], response.status_code, response.text
                )
            )
        elif response.json().get("error", {}).get("code") != "INVALID_ARGUMENT":
            failures.append(
                "{0}: unexpected error code {1}".format(
                    case["name"], response.json().get("error", {}).get("code")
                )
            )
    assert failures == []


def test_p0_list_endpoints_enforce_scope_before_pagination(
    api_client, pagination_context
):
    outsider_team = api_client.post(
        "/api/v1/teams/create",
        json={"name": "Pagination Outsider Team"},
        headers=pagination_context["headers"],
    ).json()["data"]
    outsider = create_user_as_admin(
        api_client,
        pagination_context["headers"],
        outsider_team["id"],
        "pagination-outsider@example.com",
    )["user"]
    outsider_headers = login_headers(
        api_client,
        email=outsider["email"],
        password="password-123",
    )
    team_id = pagination_context["team"]["id"]
    checks = [
        ("members", "/api/v1/members", {"team_id": team_id}, outsider_headers, 403),
        (
            "messages",
            "/api/v1/chats/messages",
            {"team_id": team_id, "chat_id": pagination_context["chat_id"]},
            outsider_headers,
            403,
        ),
        ("sources", "/api/v1/sources", {"team_id": team_id}, outsider_headers, 403),
        (
            "credentials",
            "/api/v1/credentials",
            {"team_id": team_id},
            outsider_headers,
            403,
        ),
        (
            "versions",
            "/api/v1/docs/versions",
            {"team_id": team_id, "document_id": pagination_context["document_id"]},
            outsider_headers,
            403,
        ),
        (
            "tasks",
            "/api/v1/docs/tasks",
            {"team_id": team_id, "document_id": pagination_context["document_id"]},
            outsider_headers,
            403,
        ),
        (
            "doc_chunks",
            "/api/v1/docs/chunks",
            {"team_id": team_id, "document_id": pagination_context["document_id"]},
            outsider_headers,
            403,
        ),
        (
            "chunk_history",
            "/api/v1/chunks/history",
            {
                "team_id": team_id,
                "chunk_id": next(
                    case["expected"][0]
                    for case in pagination_context["cases"]
                    if case["name"] == "doc_chunks"
                ),
            },
            outsider_headers,
            403,
        ),
        (
            "kb_members",
            "/api/v1/kbs/members",
            {"team_id": team_id, "kb_id": pagination_context["kb"]["id"]},
            outsider_headers,
            404,
        ),
        (
            "grants",
            "/api/v1/docs/grants",
            {"team_id": team_id, "document_id": pagination_context["document_id"]},
            outsider_headers,
            403,
        ),
        (
            "datasets",
            "/api/v1/evals/datasets",
            {"team_id": team_id},
            outsider_headers,
            403,
        ),
        (
            "cases",
            "/api/v1/evals/datasets/cases",
            {"team_id": team_id, "dataset_id": pagination_context["dataset_id"]},
            outsider_headers,
            403,
        ),
        (
            "runs",
            "/api/v1/evals/runs",
            {"team_id": team_id, "dataset_id": pagination_context["dataset_id"]},
            outsider_headers,
            403,
        ),
        (
            "model_calls",
            "/api/v1/model-calls",
            {"team_id": team_id},
            outsider_headers,
            403,
        ),
        (
            "providers",
            "/api/v1/providers",
            {"team_id": team_id},
            outsider_headers,
            403,
        ),
        ("admin_providers", "/api/v1/admin/providers", {}, pagination_context["member_headers"], 403),
        ("admin_models", "/api/v1/admin/models", {}, pagination_context["member_headers"], 403),
    ]
    failures = []
    for name, path, params, headers, expected_status in checks:
        response = api_client.get(path, params=params, headers=headers)
        if response.status_code != expected_status:
            failures.append(
                "{0}: expected {1}, got {2}: {3}".format(
                    name, expected_status, response.status_code, response.text
                )
            )
        elif response.json().get("error", {}).get("code") != "PERMISSION_DENIED" and expected_status == 403:
            failures.append(
                "{0}: expected PERMISSION_DENIED, got {1}".format(
                    name, response.json().get("error", {}).get("code")
                )
            )
    same_team_message = api_client.get(
        "/api/v1/chats/messages",
        params={"team_id": team_id, "chat_id": pagination_context["chat_id"]},
        headers=pagination_context["member_headers"],
    )
    if same_team_message.status_code != 403:
        failures.append(
            "same-team non-owner message access: expected 403, got {0}".format(
                same_team_message.status_code
            )
        )
    assert failures == []
