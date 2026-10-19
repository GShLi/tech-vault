import json
from collections import Counter

from sqlalchemy import select

from backend.app.api.v1 import evaluations as evaluations_module
from backend.app.db.models import AuditLog, ChunkRecord
from backend.app.modules.sources import github as github_source_module
from backend.app.modules.sources.github import GitHubSyncSummary


RAW_DOCUMENT_TEXT = "raw document body must never enter audit details"
RAW_MODEL_TEXT = "raw model response must never enter audit details"
SOURCE_SECRET = "ghp_super-secret-1234"


def _create_team(client, headers, name):
    response = client.post(
        "/api/v1/teams/create",
        json={"name": name},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _create_kb(client, headers, team_id, name):
    response = client.post(
        "/api/v1/kbs/create",
        json={
            "team_id": team_id,
            "name": name,
            "description": RAW_DOCUMENT_TEXT,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _audit_records(api_app, team_id):
    with api_app.state.session_factory() as session:
        scope = (
            AuditLog.team_id.is_(None)
            if team_id is None
            else AuditLog.team_id == team_id
        )
        return session.scalars(
            select(AuditLog)
            .where(scope)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        ).all()


def _assert_actions_once(records, expected_actions):
    counts = Counter(record.action for record in records)
    for action in expected_actions:
        assert counts[action] == 1, (action, counts)


def _walk_details(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_details(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_details(item)


def _assert_audit_details_safe(records):
    decoded = [json.loads(record.details or "{}") for record in records]
    encoded = json.dumps(decoded, ensure_ascii=False)
    for sensitive_value in (RAW_DOCUMENT_TEXT, RAW_MODEL_TEXT, SOURCE_SECRET):
        assert sensitive_value not in encoded

    forbidden_keys = {
        "api_key",
        "authorization",
        "body",
        "content",
        "password",
        "prompt",
        "query",
        "request",
        "response",
        "secret",
        "token",
    }
    for details in decoded:
        assert not forbidden_keys.intersection(_walk_details(details))


def test_knowledge_base_and_team_policy_success_paths_are_audited_once(
    api_client, api_app, admin_headers
):
    team = _create_team(api_client, admin_headers, "Audit KB Team")
    kb = _create_kb(api_client, admin_headers, team["id"], "Audited KB")
    admin_id = api_client.get("/api/v1/auth/me", headers=admin_headers).json()["data"][
        "user"
    ]["id"]

    updated = api_client.post(
        "/api/v1/kbs/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "name": "Audited KB v2",
            "description": RAW_DOCUMENT_TEXT,
        },
        headers={**admin_headers, "If-Match": "1"},
    )
    assert updated.status_code == 200, updated.text

    policy = api_client.post(
        "/api/v1/kbs/policy/update",
        json={"team_id": team["id"], "kb_id": kb["id"], "mode": "local_only"},
        headers={**admin_headers, "If-Match": "2"},
    )
    assert policy.status_code == 200, policy.text

    members = api_client.post(
        "/api/v1/kbs/members/update",
        json={"team_id": team["id"], "kb_id": kb["id"], "user_ids": [admin_id]},
        headers=admin_headers,
    )
    assert members.status_code == 200, members.text

    team_policy = api_client.post(
        "/api/v1/model-policy/update",
        json={"team_id": team["id"], "mode": "local_only"},
        headers=admin_headers,
    )
    assert team_policy.status_code == 200, team_policy.text

    provider = api_client.post(
        "/api/v1/providers/create",
        json={"team_id": team["id"], "name": "Team Provider", "model_ids": ["m1"]},
        headers=admin_headers,
    )
    assert provider.status_code == 201, provider.text

    archived = api_client.post(
        "/api/v1/kbs/archive",
        json={"team_id": team["id"], "kb_id": kb["id"]},
        headers={**admin_headers, "If-Match": "3"},
    )
    assert archived.status_code == 202, archived.text

    records = _audit_records(api_app, team["id"])
    _assert_actions_once(
        records,
        {
            "kb.create",
            "kb.update",
            "kb.archive",
            "kb.policy.update",
            "kb.members.update",
            "model_policy.team.update",
            "provider.team.create",
        },
    )
    _assert_audit_details_safe(records)


def test_admin_model_and_provider_success_paths_are_audited_once(
    api_client, api_app, admin_headers
):
    team = _create_team(api_client, admin_headers, "Audit Admin Team")

    policy = api_client.post(
        "/api/v1/admin/model-policy/update",
        json={
            "mode": "external_allowed",
            "max_data_classification": "internal",
            "allowed_provider_ids": [],
        },
        headers=admin_headers,
    )
    assert policy.status_code == 200, policy.text

    provider = api_client.post(
        "/api/v1/admin/providers/create",
        json={
            "name": "Global Provider",
            "provider_type": "openai_compatible",
            "base_url": "https://user:secret@example.invalid?api_key=hidden",
            "model_ids": ["model-a"],
        },
        headers=admin_headers,
    )
    assert provider.status_code == 201, provider.text
    provider_id = provider.json()["data"]["id"]

    provider_update = api_client.post(
        "/api/v1/admin/providers/update",
        json={"provider_id": provider_id, "status": "disabled"},
        headers=admin_headers,
    )
    assert provider_update.status_code == 200, provider_update.text

    model_update = api_client.post(
        "/api/v1/admin/models/update",
        json={"provider_id": provider_id, "model_ids": ["model-b"]},
        headers=admin_headers,
    )
    assert model_update.status_code == 200, model_update.text

    records = _audit_records(api_app, None)
    _assert_actions_once(
        records,
        {
            "model_policy.deployment.update",
            "provider.admin.create",
            "provider.admin.update",
            "model.admin.update",
        },
    )
    deployment = next(
        record
        for record in records
        if record.action == "model_policy.deployment.update"
    )
    assert all(record.team_id is None for record in records)
    assert json.loads(deployment.details)["scope"] == "deployment"
    _assert_audit_details_safe(records)


def test_evaluation_success_paths_are_audited_once(
    api_client, api_app, admin_headers, monkeypatch
):
    team = _create_team(api_client, admin_headers, "Audit Evaluation Team")
    dataset_response = api_client.post(
        "/api/v1/evals/datasets/create",
        json={
            "team_id": team["id"],
            "name": "Audit Set",
            "description": RAW_DOCUMENT_TEXT,
        },
        headers=admin_headers,
    )
    assert dataset_response.status_code == 201, dataset_response.text
    dataset = dataset_response.json()["data"]

    updated_dataset = api_client.post(
        "/api/v1/evals/datasets/update",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "name": "Audit Set v2",
            "description": RAW_DOCUMENT_TEXT,
        },
        headers=admin_headers,
    )
    assert updated_dataset.status_code == 200, updated_dataset.text

    case_response = api_client.post(
        "/api/v1/evals/datasets/cases/create",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "query_id": "q1",
            "query_type": "concept",
            "query": RAW_DOCUMENT_TEXT,
        },
        headers=admin_headers,
    )
    assert case_response.status_code == 201, case_response.text
    case_id = case_response.json()["data"]["id"]

    updated_case = api_client.post(
        "/api/v1/evals/datasets/cases/update",
        json={
            "team_id": team["id"],
            "case_id": case_id,
            "query": RAW_MODEL_TEXT,
        },
        headers=admin_headers,
    )
    assert updated_case.status_code == 200, updated_case.text

    imported = api_client.post(
        "/api/v1/evals/datasets/import",
        json={
            "team_id": team["id"],
            "dataset_id": dataset["id"],
            "content": json.dumps(
                {
                    "query_id": "q2",
                    "query_type": "concept",
                    "query": RAW_DOCUMENT_TEXT,
                }
            ),
        },
        headers=admin_headers,
    )
    assert imported.status_code == 201, imported.text

    def fake_collect(*_args, **_kwargs):
        return {
            "metrics": {"case_count": 2, "permission_leakage_count": 0},
            "report": {"cases": [], "raw": RAW_MODEL_TEXT},
        }

    monkeypatch.setattr(
        evaluations_module,
        "_collect_evaluation_result",
        fake_collect,
    )
    run_response = api_client.post(
        "/api/v1/evals/runs/start",
        json={"team_id": team["id"], "dataset_id": dataset["id"]},
        headers=admin_headers,
    )
    assert run_response.status_code == 202, run_response.text
    run_id = run_response.json()["data"]["id"]

    cancelled = api_client.post(
        "/api/v1/evals/runs/cancel",
        json={"team_id": team["id"], "run_id": run_id},
        headers=admin_headers,
    )
    assert cancelled.status_code == 409, cancelled.text
    assert cancelled.json()["error"]["code"] == "RESOURCE_STATE_CONFLICT"

    deleted_case = api_client.post(
        "/api/v1/evals/datasets/cases/delete",
        json={"team_id": team["id"], "case_id": case_id},
        headers=admin_headers,
    )
    assert deleted_case.status_code == 200, deleted_case.text

    archived = api_client.post(
        "/api/v1/evals/datasets/archive",
        json={"team_id": team["id"], "dataset_id": dataset["id"]},
        headers=admin_headers,
    )
    assert archived.status_code == 200, archived.text

    records = _audit_records(api_app, team["id"])
    _assert_actions_once(
        records,
        {
            "evaluation.dataset.create",
            "evaluation.dataset.update",
            "evaluation.dataset.archive",
            "evaluation.case.create",
            "evaluation.case.update",
            "evaluation.case.delete",
            "evaluation.case.import",
            "evaluation.run.start",
        },
    )
    _assert_audit_details_safe(records)


def test_source_and_credential_success_paths_are_audited_once(
    api_client, api_app, admin_headers, monkeypatch
):
    team = _create_team(api_client, admin_headers, "Audit Source Team")
    kb = _create_kb(api_client, admin_headers, team["id"], "Source KB")

    credential = api_client.post(
        "/api/v1/credentials/create",
        json={"team_id": team["id"], "name": "GitHub", "secret": SOURCE_SECRET},
        headers=admin_headers,
    )
    assert credential.status_code == 201, credential.text
    credential_id = credential.json()["data"]["id"]

    source = api_client.post(
        "/api/v1/sources/github/create",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "repo_url": "https://{0}@github.com/acme/handbook.git".format(
                SOURCE_SECRET
            ),
            "branch": "main",
            "path_filters": ["docs/"],
            "credentials_id": credential_id,
        },
        headers=admin_headers,
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["data"]["id"]

    updated = api_client.post(
        "/api/v1/sources/update",
        json={
            "team_id": team["id"],
            "source_id": source_id,
            "branch": "release",
            "path_filters": ["docs/", "runbooks/"],
        },
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text

    paused = api_client.post(
        "/api/v1/sources/pause",
        json={"team_id": team["id"], "source_id": source_id},
        headers=admin_headers,
    )
    assert paused.status_code == 200, paused.text

    resumed = api_client.post(
        "/api/v1/sources/resume",
        json={"team_id": team["id"], "source_id": source_id},
        headers=admin_headers,
    )
    assert resumed.status_code == 200, resumed.text

    def fake_sync(source, session, settings):
        source.status = "active"
        return GitHubSyncSummary(
            source_id=source.id,
            status="active",
            cursor="commit-sha",
            files_seen=1,
            documents_created=1,
            documents_updated=0,
            documents_unchanged=0,
            documents_deleted=0,
            documents_failed=0,
        )

    monkeypatch.setattr(github_source_module, "sync_github_source", fake_sync)
    synced = api_client.post(
        "/api/v1/sources/sync",
        json={"team_id": team["id"], "source_id": source_id},
        headers=admin_headers,
    )
    assert synced.status_code == 202, synced.text

    deleted_source = api_client.post(
        "/api/v1/sources/delete",
        json={"team_id": team["id"], "source_id": source_id},
        headers=admin_headers,
    )
    assert deleted_source.status_code == 200, deleted_source.text

    deleted_credential = api_client.post(
        "/api/v1/credentials/delete",
        json={"team_id": team["id"], "credential_id": credential_id},
        headers=admin_headers,
    )
    assert deleted_credential.status_code == 200, deleted_credential.text

    records = _audit_records(api_app, team["id"])
    _assert_actions_once(
        records,
        {
            "source.create",
            "source.update",
            "source.delete",
            "source.pause",
            "source.resume",
            "source.sync",
            "credential.create",
            "credential.delete",
        },
    )
    _assert_audit_details_safe(records)


def test_chunk_success_paths_are_audited_once(
    api_client, api_app, admin_headers
):
    team = _create_team(api_client, admin_headers, "Audit Chunk Team")
    kb = _create_kb(api_client, admin_headers, team["id"], "Chunk KB")
    upload = api_client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={
            "file": (
                "audit-chunks.md",
                ("# Chunk\n\n" + RAW_DOCUMENT_TEXT).encode("utf-8"),
            )
        },
        headers=admin_headers,
    )
    assert upload.status_code == 202, upload.text
    document_id = upload.json()["data"]["document"]["id"]

    with api_app.state.session_factory() as session:
        chunk = session.scalar(
            select(ChunkRecord).where(ChunkRecord.document_id == document_id)
        )
        assert chunk is not None
        chunk_id = chunk.id
        chunk_version = chunk.version

    updated = api_client.post(
        "/api/v1/chunks/update",
        json={
            "team_id": team["id"],
            "chunk_id": chunk_id,
            "content": RAW_MODEL_TEXT,
        },
        headers={**admin_headers, "If-Match": str(chunk_version)},
    )
    assert updated.status_code == 200, updated.text
    disabled = api_client.post(
        "/api/v1/chunks/disable",
        json={"team_id": team["id"], "chunk_ids": [chunk_id]},
        headers=admin_headers,
    )
    assert disabled.status_code == 200, disabled.text
    enabled = api_client.post(
        "/api/v1/chunks/enable",
        json={"team_id": team["id"], "chunk_ids": [chunk_id]},
        headers=admin_headers,
    )
    assert enabled.status_code == 200, enabled.text
    regenerated = api_client.post(
        "/api/v1/chunks/regenerate",
        json={"team_id": team["id"], "document_id": document_id},
        headers=admin_headers,
    )
    assert regenerated.status_code == 202, regenerated.text

    records = _audit_records(api_app, team["id"])
    _assert_actions_once(
        records,
        {
            "chunk.update",
            "chunk.disable",
            "chunk.enable",
            "chunk.regenerate",
        },
    )
    _assert_audit_details_safe(records)
