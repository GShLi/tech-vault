def _register(client, email="member@example.com", password="password-123"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "Member"},
    )


def test_register_login_and_me(api_client):
    registered = _register(api_client)
    assert registered.status_code == 201
    assert registered.json()["data"]["email"] == "member@example.com"
    assert "password_hash" not in registered.json()["data"]

    logged_in = api_client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "password-123"},
    )
    assert logged_in.status_code == 200
    token = logged_in.json()["data"]["access_token"]

    me = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer " + token},
    )
    assert me.status_code == 200
    assert me.json()["data"]["user"]["display_name"] == "Member"


def test_duplicate_email_and_wrong_password_use_error_envelopes(api_client):
    assert _register(api_client).status_code == 201
    duplicate = _register(api_client)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_RESOURCE"

    wrong = api_client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "wrong-password"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_requires_a_valid_token(api_client):
    missing = api_client.get("/api/v1/auth/me")
    invalid = api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
