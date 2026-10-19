from backend.app.core.passwords import hash_password, verify_password


def test_password_hash_round_trips_without_storing_plaintext():
    encoded = hash_password("correct horse battery staple")

    assert "correct horse battery staple" not in encoded
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_malformed_password_hash_is_rejected():
    assert not verify_password("anything", "not-a-valid-hash")
