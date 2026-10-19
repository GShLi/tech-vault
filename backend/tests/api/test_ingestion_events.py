from backend.tests.api.conftest import admin_headers_for


def _upload(client, headers, file_name, content):
    team = client.post(
        "/api/v1/teams/create",
        json={"name": "SSE Team"},
        headers=headers,
    ).json()["data"]
    kb = client.post(
        "/api/v1/kbs/create",
        json={"team_id": team["id"], "name": "SSE KB"},
        headers=headers,
    ).json()["data"]
    response = client.post(
        "/api/v1/docs/upload",
        data={"team_id": team["id"], "kb_id": kb["id"]},
        files={"file": (file_name, content)},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return team, response.json()["data"]


def test_ingestion_events_emit_completed_terminal_event(api_client):
    headers = admin_headers_for(api_client)
    team, upload = _upload(
        api_client,
        headers,
        "complete.md",
        b"# Complete\n\nTerminal event.",
    )

    response = api_client.get(
        "/api/v1/ingestions/events",
        params={"team_id": team["id"], "run_id": upload["ingestion_run_id"]},
        headers=headers,
    )

    assert response.status_code == 200
    assert "event: completed" in response.text
    assert '"status": "completed"' in response.text
    assert "event: failed" not in response.text


def test_ingestion_events_emit_failed_terminal_event_for_empty_document(api_client):
    headers = admin_headers_for(api_client)
    team, upload = _upload(api_client, headers, "empty.md", b"")

    response = api_client.get(
        "/api/v1/ingestions/events",
        params={"team_id": team["id"], "run_id": upload["ingestion_run_id"]},
        headers=headers,
    )

    assert response.status_code == 200
    assert "event: failed" in response.text
    assert '"error_code": "EMPTY_DOCUMENT"' in response.text
    assert "event: completed" not in response.text
