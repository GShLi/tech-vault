import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_implemented_p0_paths_are_exposed_with_expected_methods(api_client):
    paths = api_client.app.openapi()["paths"]

    expected_methods = {
        "/api/v1/health": "get",
        "/api/v1/ready": "get",
        "/api/v1/version": "get",
        "/api/v1/auth/login": "post",
        "/api/v1/auth/me": "get",
        "/api/v1/auth/password/change": "post",
        "/api/v1/admin/users/create": "post",
        "/api/v1/admin/users/update": "post",
        "/api/v1/admin/audit": "get",
        "/api/v1/admin/audit/detail": "get",
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
    assert "/api/v1/auth/register" not in paths
    assert set(expected_methods).issubset(paths)
    assert all(
        method in paths[path] for path, method in expected_methods.items()
    )
    assert all("{" not in path for path in paths)


def test_every_p0_api_contract_path_is_implemented(api_client):
    contract = (ROOT / "docs" / "api" / "api-contract.md").read_text(
        encoding="utf-8"
    )
    rows = re.findall(
        r"\| `(GET|POST|PUT|DELETE|PATCH)` \| `([^`?]+)(?:\?[^`]*)?` "
        r"\| [^\n]*\| P0 \|",
        contract,
    )
    paths = api_client.app.openapi()["paths"]

    missing = [
        "{0} {1}".format(method, path)
        for method, path in rows
        if "/api/v1" + path not in paths
        or method.lower() not in paths["/api/v1" + path]
    ]
    assert rows
    assert ("POST", "/auth/register") not in rows
    assert missing == []
