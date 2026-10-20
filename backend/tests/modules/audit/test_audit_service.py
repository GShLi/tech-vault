import json

from backend.app.modules.audit.service import sanitize_audit_details


def test_sanitize_audit_details_removes_secret_and_raw_content_fields():
    details = {
        "source_id": "source-1",
        "secret": "never-store-this",
        "nested": {
            "api_key": "sk-live-should-not-survive",
            "query": "customer document text",
            "path_filters": ["docs/"],
        },
        "token_count": 42,
        "model_response": "raw model output",
        "note": "Authorization: Bearer abcdefghijklmnop and ghp_super-secret-1234",
    }

    sanitized = sanitize_audit_details(details)
    encoded = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)

    assert sanitized["source_id"] == "source-1"
    assert sanitized["nested"]["path_filters"] == ["docs/"]
    for forbidden in (
        "never-store-this",
        "sk-live-should-not-survive",
        "customer document text",
        "raw model output",
        "abcdefghijklmnop",
        "ghp_super-secret-1234",
    ):
        assert forbidden not in encoded
    for forbidden_key in (
        "secret",
        "api_key",
        "query",
        "token_count",
        "model_response",
    ):
        assert forbidden_key not in encoded


def test_sanitize_audit_details_redacts_credentials_embedded_in_urls():
    sanitized = sanitize_audit_details(
        {
            "endpoint": (
                "https://service-user:url-password@example.com/v1"
                "?api_key=query-secret&region=cn"
            )
        }
    )
    encoded = json.dumps(sanitized, ensure_ascii=False)

    assert "service-user" not in encoded
    assert "url-password" not in encoded
    assert "query-secret" not in encoded
    assert "example.com/v1" in encoded
    assert "region=cn" in encoded
