from __future__ import annotations

import os
from dataclasses import dataclass


_DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./data/techvault.db"
_DEFAULT_JWT_SECRET = "dev-only-change-me"
_DEFAULT_JWT_ALGORITHM = "HS256"
_DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 900
_DEFAULT_REFRESH_TOKEN_TTL_SECONDS = 2592000
_DEFAULT_ENVIRONMENT = "production"
_ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})
_MIN_JWT_SECRET_BYTES = 32

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_DEFAULT_ES_URL = "http://localhost:9200"
_DEFAULT_QDRANT_URL = "http://localhost:6333"
_DEFAULT_MINIO_URL = "http://localhost:9000"
_DEFAULT_EMBEDDING_URL = "http://localhost:8001"
_DEFAULT_UPLOAD_DIR = "data/uploads"
_DEFAULT_ADMIN_EMAIL = "admin@techvault.local"
_DEFAULT_ADMIN_PASSWORD = "ChangeMe-123!"
_DEFAULT_ADMIN_DISPLAY_NAME = "TechVault Admin"
_DEFAULT_ALLOW_REGISTRATION = False
_DEFAULT_ALLOW_LEGACY_TEAM_CREATION = False
_DEFAULT_ENABLE_INDEXING = False


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = _DEFAULT_DATABASE_URL
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = _DEFAULT_JWT_ALGORITHM
    access_token_ttl_seconds: int = _DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    refresh_token_ttl_seconds: int = _DEFAULT_REFRESH_TOKEN_TTL_SECONDS
    environment: str = _DEFAULT_ENVIRONMENT
    redis_url: str = _DEFAULT_REDIS_URL
    es_url: str = _DEFAULT_ES_URL
    qdrant_url: str = _DEFAULT_QDRANT_URL
    minio_url: str = _DEFAULT_MINIO_URL
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "techvault"
    embedding_url: str = _DEFAULT_EMBEDDING_URL
    upload_dir: str = _DEFAULT_UPLOAD_DIR
    admin_email: str = _DEFAULT_ADMIN_EMAIL
    admin_password: str = _DEFAULT_ADMIN_PASSWORD
    admin_display_name: str = _DEFAULT_ADMIN_DISPLAY_NAME
    allow_registration: bool = _DEFAULT_ALLOW_REGISTRATION
    allow_legacy_team_creation: bool = _DEFAULT_ALLOW_LEGACY_TEAM_CREATION
    enable_indexing: bool = _DEFAULT_ENABLE_INDEXING

    def __post_init__(self) -> None:
        if self.access_token_ttl_seconds <= 0:
            raise ValueError("access token TTL must be positive")
        if self.refresh_token_ttl_seconds <= 0:
            raise ValueError("refresh token TTL must be positive")
        if self.jwt_algorithm not in _ALLOWED_JWT_ALGORITHMS:
            raise ValueError("JWT algorithm must be HS256, HS384, or HS512")
        if not self.jwt_secret:
            raise ValueError("JWT secret must not be empty")
        if self.environment != "development" and (
            self.jwt_secret.strip() == _DEFAULT_JWT_SECRET
            or len(self.jwt_secret.encode("utf-8")) < _MIN_JWT_SECRET_BYTES
        ):
            raise ValueError(
                "JWT secret must be at least 32 bytes outside development"
            )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("TECHVAULT_DATABASE_URL", _DEFAULT_DATABASE_URL),
            jwt_secret=os.getenv("TECHVAULT_JWT_SECRET", _DEFAULT_JWT_SECRET),
            jwt_algorithm=os.getenv(
                "TECHVAULT_JWT_ALGORITHM", _DEFAULT_JWT_ALGORITHM
            ),
            access_token_ttl_seconds=int(
                os.getenv(
                    "TECHVAULT_ACCESS_TOKEN_TTL_SECONDS",
                    str(_DEFAULT_ACCESS_TOKEN_TTL_SECONDS),
                )
            ),
            refresh_token_ttl_seconds=int(
                os.getenv(
                    "TECHVAULT_REFRESH_TOKEN_TTL_SECONDS",
                    str(_DEFAULT_REFRESH_TOKEN_TTL_SECONDS),
                )
            ),
            environment=os.getenv("TECHVAULT_ENVIRONMENT", _DEFAULT_ENVIRONMENT),
            redis_url=os.getenv("TECHVAULT_REDIS_URL", _DEFAULT_REDIS_URL),
            es_url=os.getenv("TECHVAULT_ES_URL", _DEFAULT_ES_URL),
            qdrant_url=os.getenv("TECHVAULT_QDRANT_URL", _DEFAULT_QDRANT_URL),
            minio_url=os.getenv("TECHVAULT_MINIO_URL", _DEFAULT_MINIO_URL),
            minio_access_key=os.getenv("TECHVAULT_MINIO_ACCESS_KEY", "minioadmin"),
            minio_secret_key=os.getenv("TECHVAULT_MINIO_SECRET_KEY", "minioadmin"),
            minio_bucket=os.getenv("TECHVAULT_MINIO_BUCKET", "techvault"),
            embedding_url=os.getenv("TECHVAULT_EMBEDDING_URL", _DEFAULT_EMBEDDING_URL),
            upload_dir=os.getenv("TECHVAULT_UPLOAD_DIR", _DEFAULT_UPLOAD_DIR),
            admin_email=os.getenv("TECHVAULT_ADMIN_EMAIL", _DEFAULT_ADMIN_EMAIL),
            admin_password=os.getenv(
                "TECHVAULT_ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD
            ),
            admin_display_name=os.getenv(
                "TECHVAULT_ADMIN_DISPLAY_NAME", _DEFAULT_ADMIN_DISPLAY_NAME
            ),
            allow_registration=_env_bool(
                "TECHVAULT_ALLOW_REGISTRATION", _DEFAULT_ALLOW_REGISTRATION
            ),
            allow_legacy_team_creation=_env_bool(
                "TECHVAULT_ALLOW_LEGACY_TEAM_CREATION",
                _DEFAULT_ALLOW_LEGACY_TEAM_CREATION,
            ),
            enable_indexing=_env_bool(
                "TECHVAULT_ENABLE_INDEXING", _DEFAULT_ENABLE_INDEXING
            ),
        )
