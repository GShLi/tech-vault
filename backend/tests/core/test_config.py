from backend.app.core.config import Settings


def test_settings_from_env_reads_runtime_values(monkeypatch):
    monkeypatch.setenv(
        "TECHVAULT_DATABASE_URL", "sqlite+pysqlite:///./test-techvault.db"
    )
    monkeypatch.setenv(
        "TECHVAULT_JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef"
    )
    monkeypatch.setenv("TECHVAULT_ACCESS_TOKEN_TTL_SECONDS", "120")
    monkeypatch.setenv("TECHVAULT_ENVIRONMENT", "test")

    settings = Settings.from_env()

    assert settings.database_url == "sqlite+pysqlite:///./test-techvault.db"
    assert settings.jwt_secret == "test-secret-0123456789abcdef0123456789abcdef"
    assert settings.access_token_ttl_seconds == 120
    assert settings.environment == "test"
