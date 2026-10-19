import pytest

from backend.app.core.config import Settings


def test_development_allows_short_secret():
    settings = Settings(jwt_secret="short-secret")

    assert settings.jwt_secret == "short-secret"


def test_empty_jwt_secret_is_rejected_in_development():
    with pytest.raises(ValueError, match="JWT secret"):
        Settings(jwt_secret="")


def test_unsafe_jwt_algorithm_is_rejected():
    with pytest.raises(ValueError, match="JWT algorithm"):
        Settings(jwt_algorithm="none")


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
def test_hmac_jwt_algorithms_are_allowed(algorithm):
    settings = Settings(jwt_algorithm=algorithm)

    assert settings.jwt_algorithm == algorithm


def test_weak_secret_is_rejected_outside_development():
    with pytest.raises(ValueError, match="JWT secret"):
        Settings(jwt_secret="short-secret", environment="production")


def test_public_default_secret_is_rejected_outside_development():
    with pytest.raises(ValueError, match="JWT secret"):
        Settings(environment="production")


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
