import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Tuple

from backend.app.api.errors import ApiError


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
            base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        )
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        item_id = payload["id"]
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("cursor id is missing")
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
