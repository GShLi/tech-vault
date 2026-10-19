import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Tuple

from backend.app.api.errors import ApiError
from backend.app.core.ids import is_valid_ulid


def encode_cursor(created_at: datetime, item_id: str) -> str:
    payload = json.dumps(
        {
            "created_at": created_at.astimezone(timezone.utc).isoformat(),
            "id": item_id,
        },
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> Tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.b64decode(
                padded.encode("ascii"),
                altchars=b"-_",
                validate=True,
            ).decode("utf-8")
        )
        raw_created_at = payload["created_at"]
        if not isinstance(raw_created_at, str) or "T" not in raw_created_at:
            raise ValueError("cursor created_at is invalid")
        created_at = datetime.fromisoformat(raw_created_at)
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("cursor created_at must include a timezone")
        item_id = payload["id"]
        if not isinstance(item_id, str) or not is_valid_ulid(item_id):
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
