import base64
from datetime import datetime, timezone

import pytest

from backend.app.api.errors import ApiError
from backend.app.api.pagination import decode_cursor, encode_cursor


def _encoded(payload: str) -> str:
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _assert_invalid(cursor: str) -> None:
    with pytest.raises(ApiError) as error:
        decode_cursor(cursor)
    assert error.value.status_code == 400
    assert error.value.code == "INVALID_ARGUMENT"


def test_decode_cursor_rejects_valid_base64_with_malformed_json():
    _assert_invalid(_encoded("{not-json"))


def test_decode_cursor_rejects_date_only_timestamp():
    _assert_invalid(
        _encoded(
            '{"created_at":"2026-10-19",'
            '"id":"00000000000000000000000000"}'
        )
    )


def test_decode_cursor_rejects_non_ulid_id():
    _assert_invalid(
        _encoded(
            '{"created_at":"2026-10-19T12:00:00+00:00",'
            '"id":"not-a-ulid"}'
        )
    )


def test_decode_cursor_rejects_trailing_space():
    cursor = encode_cursor(
        datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc),
        "00000000000000000000000000",
    )

    _assert_invalid(cursor + " ")


def test_decode_cursor_rejects_noncanonical_payload():
    _assert_invalid(
        _encoded(
            '{"id":"00000000000000000000000000",'
            '"created_at":"2026-10-19T12:00:00+00:00"}'
        )
    )
