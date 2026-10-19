def test_implemented_p0_paths_are_exposed_with_expected_methods(api_client):
    paths = api_client.app.openapi()["paths"]

    expected_methods = {
        "/api/v1/health": "get",
        "/api/v1/ready": "get",
        "/api/v1/version": "get",
        "/api/v1/auth/register": "post",
        "/api/v1/auth/login": "post",
        "/api/v1/auth/me": "get",
        "/api/v1/teams": "get",
        "/api/v1/teams/create": "post",
        "/api/v1/teams/detail": "get",
        "/api/v1/teams/update": "post",
        "/api/v1/kbs": "get",
        "/api/v1/kbs/create": "post",
        "/api/v1/kbs/detail": "get",
        "/api/v1/kbs/update": "post",
        "/api/v1/kbs/archive": "post",
    }

    assert all(path.startswith("/api/v1/") for path in paths)
    assert set(expected_methods).issubset(paths)
    assert all(
        method in paths[path] for path, method in expected_methods.items()
    )
    assert all("{" not in path for path in paths)
