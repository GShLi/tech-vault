from __future__ import annotations

import os
from dataclasses import dataclass


_DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./data/techvault.db"
_DEFAULT_JWT_SECRET = "dev-only-change-me"
_DEFAULT_JWT_ALGORITHM = "HS256"
_DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 900
_DEFAULT_ENVIRONMENT = "development"


@dataclass(frozen=True)
class Settings:
    database_url: str = _DEFAULT_DATABASE_URL
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = _DEFAULT_JWT_ALGORITHM
    access_token_ttl_seconds: int = _DEFAULT_ACCESS_TOKEN_TTL_SECONDS
    environment: str = _DEFAULT_ENVIRONMENT

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

