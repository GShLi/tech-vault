def test_implemented_p0_paths_are_exposed_without_path_parameters(api_client):
    paths = set(api_client.app.openapi()["paths"])

    required = {
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/version",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/teams",
        "/api/v1/teams/create",
        "/api/v1/teams/detail",
        "/api/v1/teams/update",
        "/api/v1/kbs",
        "/api/v1/kbs/create",
        "/api/v1/kbs/detail",
        "/api/v1/kbs/update",
        "/api/v1/kbs/archive",
    }

    assert required.issubset(paths)
    assert all("{" not in path for path in paths)
