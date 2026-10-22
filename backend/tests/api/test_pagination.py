import base64
import json
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


@pytest.mark.parametrize("cursor", ["!!!!", "AA==="])
def test_decode_cursor_rejects_invalid_base64_characters_and_padding(cursor):
    _assert_invalid(cursor)


def test_decode_cursor_rejects_json_list_payload():
    _assert_invalid(
        _encoded(
            '[{"created_at":"2026-10-19T12:00:00+00:00",'
            '"id":"00000000000000000000000000"}]'
        )
    )


def test_decode_cursor_rejects_object_missing_id():
    _assert_invalid(
        _encoded('{"created_at":"2026-10-19T12:00:00+00:00"}')
    )


def test_decode_cursor_rejects_non_string_created_at():
    _assert_invalid(
        _encoded(
            '{"created_at":20261019,'
            '"id":"00000000000000000000000000"}'
        )
    )


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


@pytest.mark.parametrize("prefix", ["chd_", "par_"])
def test_cursor_round_trips_deterministic_chunk_id(prefix):
    created_at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    chunk_id = prefix + "a" * 64

    assert decode_cursor(encode_cursor(created_at, chunk_id)) == (created_at, chunk_id)


@pytest.mark.parametrize("chunk_id", [
    "chk_" + "a" * 64,
    "chd_" + "a" * 63,
    "par_" + "a" * 65,
    "chd_" + "g" * 64,
    "par_" + "A" * 64,
    "chd_" + "a" * 64 + "\n",
])
def test_cursor_rejects_obsolete_or_malformed_chunk_ids(chunk_id):
    created_at = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="cursor id is invalid"):
        encode_cursor(created_at, chunk_id)
    _assert_invalid(_encoded(json.dumps({
        "created_at": created_at.isoformat(), "id": chunk_id,
    }, separators=(",", ":"))))
