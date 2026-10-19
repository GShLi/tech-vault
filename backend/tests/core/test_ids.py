import pytest

from backend.app.core.ids import is_valid_ulid, new_ulid


def test_new_ulid_is_canonical_and_time_sortable():
    earlier = new_ulid(now_ms=1000)
    later = new_ulid(now_ms=2000)

    assert len(earlier) == 26
    assert is_valid_ulid(earlier)
    assert earlier < later


def test_is_valid_ulid_rejects_bad_values():
    assert not is_valid_ulid("")
    assert not is_valid_ulid("0" * 25)
    assert not is_valid_ulid("I" * 26)


def test_is_valid_ulid_rejects_timestamp_prefix_above_seven():
    assert is_valid_ulid("7" + "0" * 25)
    assert not is_valid_ulid("8" + "0" * 25)


def test_new_ulid_rejects_timestamp_overflow():
    with pytest.raises(ValueError):
        new_ulid(now_ms=1 << 48)
