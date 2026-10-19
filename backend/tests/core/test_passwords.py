import base64
import hashlib

import pytest

from backend.app.core.passwords import hash_password, verify_password


def _hash_with_parameters(password, n, r, p):
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=32,
    )
    return "scrypt${0}${1}${2}${3}${4}".format(
        n,
        r,
        p,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def test_short_password_is_rejected():
    with pytest.raises(ValueError, match="at least 8 characters"):
        hash_password("short")


def test_password_hash_round_trips_without_storing_plaintext():
    encoded = hash_password("correct horse battery staple")

    assert "correct horse battery staple" not in encoded
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_malformed_password_hash_is_rejected():
    assert not verify_password("anything", "not-a-valid-hash")


@pytest.mark.parametrize(
    ("n", "r", "p"),
    [
        (2**13, 8, 1),
        (2**14, 7, 1),
        (2**14, 8, 2),
    ],
)
def test_noncanonical_scrypt_parameters_are_rejected(n, r, p):
    password = "correct horse battery staple"
    encoded = _hash_with_parameters(password, n=n, r=r, p=p)

    assert not verify_password(password, encoded)
