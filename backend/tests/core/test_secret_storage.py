import pytest
from cryptography.fernet import InvalidToken

from backend.app.core.config import Settings
from backend.app.core.secrets import decrypt_secret, encrypt_secret


def _settings(secret="test-secret-at-least-32-bytes-long"):
    return Settings(environment="test", jwt_secret=secret)


def test_secret_round_trip_does_not_store_plaintext():
    encrypted = encrypt_secret("ghp_super-secret-1234", _settings())

    assert "ghp_super-secret-1234" not in encrypted
    assert decrypt_secret(encrypted, _settings()) == "ghp_super-secret-1234"


def test_secret_cannot_be_decrypted_with_another_deployment_key():
    encrypted = encrypt_secret("secret", _settings())

    with pytest.raises(InvalidToken):
        decrypt_secret(encrypted, _settings("another-secret-at-least-32-bytes"))
