from typing import Any, Dict, List, Optional


def envelope(data: Any, request_id: str) -> Dict[str, Any]:
    return {"data": data, "meta": {"request_id": request_id}}


def page_envelope(
    items: List[Any],
    request_id: str,
    next_cursor: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "data": items,
        "meta": {
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
            "request_id": request_id,
        },
    }
