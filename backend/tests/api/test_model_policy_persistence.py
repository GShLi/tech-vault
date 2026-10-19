def _create_team(api_client, admin_headers):
    return api_client.post(
        "/api/v1/teams/create",
        json={"name": "Policy Team"},
        headers=admin_headers,
    ).json()["data"]


def test_deployment_policy_persists_and_caps_team_policy(api_client, admin_headers):
    default = api_client.get("/api/v1/admin/model-policy", headers=admin_headers)
    assert default.status_code == 200
    assert default.json()["data"]["mode"] == "local_only"

    updated = api_client.post(
        "/api/v1/admin/model-policy/update",
        json={
            "mode": "external_allowed",
            "max_data_classification": "internal",
            "allowed_provider_ids": [],
        },
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["mode"] == "external_allowed"
    assert updated.json()["data"]["version"] == 2

    persisted = api_client.get("/api/v1/admin/model-policy", headers=admin_headers)
    assert persisted.json()["data"]["mode"] == "external_allowed"
    assert persisted.json()["data"]["max_data_classification"] == "internal"

    team = _create_team(api_client, admin_headers)
    team_updated = api_client.post(
        "/api/v1/model-policy/update",
        json={
            "team_id": team["id"],
            "mode": "external_allowed",
            "max_data_classification": "public",
        },
        headers=admin_headers,
    )
    assert team_updated.status_code == 200
    assert team_updated.json()["data"]["mode"] == "external_allowed"

    too_wide = api_client.post(
        "/api/v1/model-policy/update",
        json={
            "team_id": team["id"],
            "mode": "external_allowed",
            "max_data_classification": "private",
        },
        headers=admin_headers,
    )
    assert too_wide.status_code == 409
    assert too_wide.json()["error"]["code"] == "DEPLOYMENT_POLICY_LIMIT"

    api_client.post(
        "/api/v1/admin/model-policy/update",
        json={"mode": "local_only", "max_data_classification": "internal"},
        headers=admin_headers,
    )
    wider_than_deployment = api_client.post(
        "/api/v1/model-policy/update",
        json={"team_id": team["id"], "mode": "external_allowed"},
        headers=admin_headers,
    )
    assert wider_than_deployment.status_code == 409
    assert wider_than_deployment.json()["error"]["code"] == "DEPLOYMENT_POLICY_LIMIT"


def test_confidential_input_is_normalized_to_canonical_restricted(
    api_client, admin_headers
):
    updated = api_client.post(
        "/api/v1/admin/model-policy/update",
        json={
            "mode": "local_only",
            "max_data_classification": "confidential",
        },
        headers=admin_headers,
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["max_data_classification"] == "restricted"


def test_team_provider_rejects_non_list_model_ids(api_client, admin_headers):
    team = _create_team(api_client, admin_headers)

    response = api_client.post(
        "/api/v1/providers/create",
        json={
            "team_id": team["id"],
            "name": "Invalid Provider",
            "provider_type": "openai_chat_completions",
            "base_url": "https://provider.invalid",
            "api_key": "sk-test",
            "model_ids": "model-a",
        },
        headers=admin_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_admin_provider_update_rejects_invalid_status_and_model_ids(
    api_client, admin_headers
):
    created = api_client.post(
        "/api/v1/admin/providers/create",
        json={
            "name": "Validated Provider",
            "provider_type": "openai_chat_completions",
            "base_url": "https://provider.invalid",
            "api_key": "sk-test",
            "model_ids": ["model-a"],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    provider_id = created.json()["data"]["id"]

    invalid_status = api_client.post(
        "/api/v1/admin/providers/update",
        json={"provider_id": provider_id, "status": "retired"},
        headers=admin_headers,
    )
    invalid_models = api_client.post(
        "/api/v1/admin/providers/update",
        json={"provider_id": provider_id, "model_ids": {"model-a": True}},
        headers=admin_headers,
    )

    assert invalid_status.status_code == 422
    assert invalid_status.json()["error"]["code"] == "VALIDATION_FAILED"
    assert invalid_models.status_code == 422
    assert invalid_models.json()["error"]["code"] == "VALIDATION_FAILED"

    providers = api_client.get("/api/v1/admin/providers", headers=admin_headers)
    provider = next(
        item for item in providers.json()["data"] if item["id"] == provider_id
    )
    assert provider["status"] == "active"


def test_knowledge_base_policy_cannot_exceed_team_or_deployment(
    api_client, admin_headers
):
    api_client.post(
        "/api/v1/admin/model-policy/update",
        json={"mode": "external_allowed"},
        headers=admin_headers,
    )
    team = _create_team(api_client, admin_headers)
    team_updated = api_client.post(
        "/api/v1/model-policy/update",
        json={"team_id": team["id"], "mode": "external_allowed"},
        headers=admin_headers,
    )
    assert team_updated.status_code == 200, team_updated.text
    kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Policy KB"},
        headers=admin_headers,
    ).json()["data"]

    updated = api_client.post(
        "/api/v1/kbs/policy/update",
        json={
            "team_id": team["id"],
            "kb_id": kb["id"],
            "mode": "external_allowed",
        },
        headers={**admin_headers, "If-Match": "1"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["mode"] == "external_allowed"
    assert updated.json()["data"]["version"] == 2

    second_kb = api_client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "Second Policy KB"},
        headers=admin_headers,
    ).json()["data"]
    api_client.post(
        "/api/v1/model-policy/update",
        json={"team_id": team["id"], "mode": "local_only"},
        headers=admin_headers,
    )
    too_wide = api_client.post(
        "/api/v1/kbs/policy/update",
        json={
            "team_id": team["id"],
            "kb_id": second_kb["id"],
            "mode": "external_allowed",
        },
        headers={**admin_headers, "If-Match": "1"},
    )
    assert too_wide.status_code == 409
    assert too_wide.json()["error"]["code"] == "TEAM_POLICY_LIMIT"

    missing_match = api_client.post(
        "/api/v1/kbs/policy/update",
        json={
            "team_id": team["id"],
            "kb_id": second_kb["id"],
            "mode": "local_only",
        },
        headers=admin_headers,
    )
    assert missing_match.status_code == 400
