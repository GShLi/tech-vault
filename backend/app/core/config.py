from __future__ import annotations

import os
from dataclasses import dataclass


_DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./data/techvault.db"
_DEFAULT_JWT_SECRET = "dev-only-change-me"
_DEFAULT_JWT_ALGORITHM = "HS256"
_DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 900
_DEFAULT_ENVIRONMENT = "development"
_ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})
_MIN_JWT_SECRET_BYTES = 32


@dataclass(frozen=True)
class Settings:
    database_url: str = _DEFAULT_DATABASE_URL
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = _DEFAULT_JWT_ALGORITHM
    access_token_ttl_seconds: int = _DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    environment: str = _DEFAULT_ENVIRONMENT

    def __post_init__(self) -> None:
        if self.jwt_algorithm not in _ALLOWED_JWT_ALGORITHMS:
            raise ValueError("JWT algorithm must be HS256, HS384, or HS512")
        if not self.jwt_secret:
            raise ValueError("JWT secret must not be empty")
        if self.environment != "development" and (
            self.jwt_secret == _DEFAULT_JWT_SECRET
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
            environment=os.getenv("TECHVAULT_ENVIRONMENT", _DEFAULT_ENVIRONMENT),
        )

