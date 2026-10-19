"""Encryption helpers for write-only application credentials."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from backend.app.core.config import Settings


def _fernet(settings: Settings) -> Fernet:
    key = hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str, settings: Settings) -> str:
    return _fernet(settings).decrypt(value.encode("ascii")).decode("utf-8")
