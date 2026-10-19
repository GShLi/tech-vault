def test_health_endpoint_uses_envelope_and_request_id(api_client):
    response = api_client.get(
        "/api/v1/health",
        headers={"X-Request-Id": "req-test-1"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-test-1"
    assert response.json() == {
        "data": {"status": "ok"},
        "meta": {"request_id": "req-test-1"},
    }


def test_unknown_route_uses_error_envelope(api_client):
    response = api_client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"] == response.headers["X-Request-Id"]


def test_ready_and_version_are_public(api_client):
    ready = api_client.get("/api/v1/ready")
    version = api_client.get("/api/v1/version")

    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready"
    assert version.status_code == 200
    assert version.json()["data"]["version"]
