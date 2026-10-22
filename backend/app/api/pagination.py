import base64
import binascii
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.app.api.envelope import page_envelope
from backend.app.api.errors import ApiError
from backend.app.core.ids import is_valid_ulid


_MAX_PAGE_LIMIT = 100
_CHUNK_ID_PATTERN = re.compile(r"(?:chd|par)_[0-9a-f]{64}\Z")


def _encode_payload(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_payload(cursor: str) -> dict:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.b64decode(
                padded.encode("ascii"),
                altchars=b"-_",
                validate=True,
            ).decode("utf-8")
        )
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be an object")
        return payload
    except (
        TypeError,
        ValueError,
        UnicodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as error:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid cursor.") from error


def _valid_cursor_id(item_id: str) -> bool:
    return is_valid_ulid(item_id) or bool(_CHUNK_ID_PATTERN.fullmatch(item_id))


def encode_cursor(created_at: datetime, item_id: str) -> str:
    if not _valid_cursor_id(item_id):
        raise ValueError("cursor id is invalid")
    return _encode_payload(
        {
            "created_at": created_at.astimezone(timezone.utc).isoformat(),
            "id": item_id,
        }
    )


def decode_cursor(cursor: str) -> Tuple[datetime, str]:
    try:
        payload = _decode_payload(cursor)
        raw_created_at = payload["created_at"]
        if not isinstance(raw_created_at, str) or "T" not in raw_created_at:
            raise ValueError("cursor created_at is invalid")
        created_at = datetime.fromisoformat(raw_created_at)
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("cursor created_at must include a timezone")
        item_id = payload["id"]
        if not isinstance(item_id, str) or not _valid_cursor_id(item_id):
            raise ValueError("cursor id is invalid")
        if cursor != encode_cursor(created_at, item_id):
            raise ValueError("cursor is not canonical")
        return created_at, item_id
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as error:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid cursor.") from error


def encode_offset_cursor(offset: int) -> str:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("cursor offset is invalid")
    return _encode_payload({"offset": offset})


def decode_offset_cursor(cursor: str) -> int:
    try:
        payload = _decode_payload(cursor)
        if set(payload) != {"offset"}:
            raise ValueError("cursor payload is invalid")
        offset = payload["offset"]
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("cursor offset is invalid")
        if cursor != encode_offset_cursor(offset):
            raise ValueError("cursor is not canonical")
        return offset
    except (KeyError, TypeError, ValueError) as error:
        raise ApiError(400, "INVALID_ARGUMENT", "Invalid cursor.") from error


def normalize_page_limit(limit: int) -> int:
    return max(1, min(limit, _MAX_PAGE_LIMIT))


def apply_cursor(
    query,
    *,
    timestamp_column,
    id_column,
    cursor: Optional[str],
    descending: bool = True,
):
    if cursor is None:
        return query
    after_timestamp, after_id = decode_cursor(cursor)
    if descending:
        return query.where(
            or_(
                timestamp_column < after_timestamp,
                and_(timestamp_column == after_timestamp, id_column < after_id),
            )
        )
    return query.where(
        or_(
            timestamp_column > after_timestamp,
            and_(timestamp_column == after_timestamp, id_column > after_id),
        )
    )


def _page_cursor(rows: List[Any], limit: int, timestamp_getter, id_getter) -> Optional[str]:
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    if not has_more or not page_rows:
        return None
    last = page_rows[-1]
    return encode_cursor(timestamp_getter(last), id_getter(last))


def paginate_scalars(
    session: Session,
    query,
    *,
    timestamp_column,
    id_column,
    cursor: Optional[str],
    limit: int,
    request_id: str,
    view: Callable[[Any], Any],
    descending: bool = True,
):
    page_limit = normalize_page_limit(limit)
    query = apply_cursor(
        query,
        timestamp_column=timestamp_column,
        id_column=id_column,
        cursor=cursor,
        descending=descending,
    )
    direction = (
        (timestamp_column.desc(), id_column.desc())
        if descending
        else (timestamp_column.asc(), id_column.asc())
    )
    rows = session.scalars(query.order_by(*direction).limit(page_limit + 1)).all()
    next_cursor = _page_cursor(
        rows,
        page_limit,
        lambda row: getattr(row, timestamp_column.key),
        lambda row: getattr(row, id_column.key),
    )
    return page_envelope([view(row) for row in rows[:page_limit]], request_id, next_cursor)


def paginate_rows(
    session: Session,
    query,
    *,
    timestamp_column,
    id_column,
    cursor: Optional[str],
    limit: int,
    request_id: str,
    view: Callable[[Any], Any],
    descending: bool = True,
):
    page_limit = normalize_page_limit(limit)
    query = apply_cursor(
        query,
        timestamp_column=timestamp_column,
        id_column=id_column,
        cursor=cursor,
        descending=descending,
    )
    direction = (
        (timestamp_column.desc(), id_column.desc())
        if descending
        else (timestamp_column.asc(), id_column.asc())
    )
    rows = session.execute(query.order_by(*direction).limit(page_limit + 1)).all()
    next_cursor = _page_cursor(
        rows,
        page_limit,
        lambda row: getattr(row[0], timestamp_column.key),
        lambda row: getattr(row[0], id_column.key),
    )
    return page_envelope([view(row) for row in rows[:page_limit]], request_id, next_cursor)


def paginate_items(
    items: List[Any],
    *,
    limit: int,
    request_id: str,
    cursor: Optional[str],
    view: Callable[[Any], Any],
):
    page_limit = normalize_page_limit(limit)
    offset = decode_offset_cursor(cursor) if cursor is not None else 0
    page_rows = items[offset : offset + page_limit]
    next_offset = offset + len(page_rows)
    next_cursor = (
        encode_offset_cursor(next_offset) if next_offset < len(items) else None
    )
    return page_envelope([view(row) for row in page_rows], request_id, next_cursor)
