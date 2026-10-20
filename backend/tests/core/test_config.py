import pytest

from backend.app.core.config import Settings


def test_default_settings_fail_closed_without_explicit_development():
    with pytest.raises(ValueError, match="32 bytes"):
        Settings()


def test_explicit_development_allows_local_secret():
    settings = Settings(environment="development")

    assert settings.jwt_secret


def test_default_model_service_urls_use_local_embedding_service_port():
    settings = Settings(environment="development")

    assert settings.embedding_url == "http://localhost:58001"
    assert settings.rerank_url == "http://localhost:58001"


def test_non_positive_token_ttl_is_rejected():
    with pytest.raises(ValueError, match="TTL"):
        Settings(environment="development", access_token_ttl_seconds=0)


def test_settings_from_env_fail_closed_without_runtime_values(monkeypatch):
    for name in (
        "TECHVAULT_DATABASE_URL",
        "TECHVAULT_JWT_SECRET",
        "TECHVAULT_JWT_ALGORITHM",
        "TECHVAULT_ACCESS_TOKEN_TTL_SECONDS",
        "TECHVAULT_ENVIRONMENT",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="32 bytes"):
        Settings.from_env()


def test_development_allows_short_secret():
    settings = Settings(environment="development", jwt_secret="short-secret")

    assert settings.jwt_secret == "short-secret"


def test_empty_jwt_secret_is_rejected_in_development():
    with pytest.raises(ValueError, match="JWT secret"):
        Settings(environment="development", jwt_secret="")


def test_unsafe_jwt_algorithm_is_rejected():
    with pytest.raises(ValueError, match="JWT algorithm"):
        Settings(environment="development", jwt_algorithm="none")


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
def test_hmac_jwt_algorithms_are_allowed(algorithm):
    settings = Settings(environment="development", jwt_algorithm=algorithm)

    assert settings.jwt_algorithm == algorithm


def test_weak_secret_is_rejected_outside_development():
    with pytest.raises(ValueError, match="JWT secret"):
        Settings(jwt_secret="short-secret", environment="production")


def test_public_default_secret_is_rejected_outside_development():
    with pytest.raises(ValueError, match="JWT secret"):
        Settings(environment="production")


def test_padded_public_default_secret_is_rejected_outside_development():
    with pytest.raises(ValueError, match="JWT secret"):
        Settings(
            environment="production",
            jwt_secret="dev-only-change-me".ljust(32),
        )


def test_registration_and_legacy_team_creation_bypasses_are_removed():
    settings = Settings(environment="development")

    assert not hasattr(settings, "allow_registration")
    assert not hasattr(settings, "allow_legacy_team_creation")


def test_settings_from_env_reads_runtime_values(monkeypatch):
    monkeypatch.setenv(
        "TECHVAULT_DATABASE_URL", "sqlite+pysqlite:///./test-techvault.db"
    )
    monkeypatch.setenv(
        "TECHVAULT_JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef"
    )
    monkeypatch.setenv("TECHVAULT_ACCESS_TOKEN_TTL_SECONDS", "120")
    monkeypatch.setenv("TECHVAULT_ENVIRONMENT", "test")
    monkeypatch.setenv(
        "TECHVAULT_MINIO_PUBLIC_URL", "https://downloads.example.test"
    )
    monkeypatch.setenv("TECHVAULT_S3_REGION", "eu-west-1")

    settings = Settings.from_env()

    assert settings.database_url == "sqlite+pysqlite:///./test-techvault.db"
    assert settings.jwt_secret == "test-secret-0123456789abcdef0123456789abcdef"
    assert settings.access_token_ttl_seconds == 120
    assert settings.environment == "test"
    assert settings.minio_public_url == "https://downloads.example.test"
    assert settings.s3_region == "eu-west-1"


def test_download_url_ttl_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("TECHVAULT_ENVIRONMENT", "development")
    monkeypatch.setenv("TECHVAULT_DOWNLOAD_URL_TTL_SECONDS", "180")

    settings = Settings.from_env()

    assert settings.download_url_ttl_seconds == 180


def test_download_url_ttl_must_be_within_sigv4_limit():
    with pytest.raises(ValueError, match="download URL TTL"):
        Settings(environment="development", download_url_ttl_seconds=0)
    with pytest.raises(ValueError, match="download URL TTL"):
        Settings(environment="development", download_url_ttl_seconds=604801)


def test_document_retention_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("TECHVAULT_ENVIRONMENT", "development")
    monkeypatch.setenv("TECHVAULT_DOCUMENT_RETENTION_DAYS", "14")

    settings = Settings.from_env()

    assert settings.document_retention_days == 14


@pytest.mark.parametrize("days", [0, 3651])
def test_document_retention_is_bounded(days):
    with pytest.raises(ValueError, match="document retention days"):
        Settings(environment="development", document_retention_days=days)
