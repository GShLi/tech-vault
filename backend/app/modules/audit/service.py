from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app.db.models import AuditLog


_FORBIDDEN_KEYS = frozenset(
    {
        "authorization",
        "body",
        "content",
        "document_content",
        "document_text",
        "message",
        "messages",
        "model_raw",
        "model_request",
        "model_response",
        "password",
        "passwd",
        "prompt",
        "query",
        "raw",
        "request",
        "response",
        "secret",
    }
)
_FORBIDDEN_KEY_FRAGMENTS = (
    "apikey",
    "authorization",
    "credentialsecret",
    "password",
    "privatekey",
    "secret",
    "token",
)
_CONTENT_KEY_SUFFIXES = ("body", "content", "prompt", "request", "response", "query")
_URL_USERINFO_PATTERN = re.compile(r"(?i)\b(https?://)[^/\s:@]+:[^@\s/]+@")
_URL_SECRET_QUERY_PATTERN = re.compile(
    r"(?i)([?&](?:api[_-]?key|authorization|password|secret|token)=)[^&#\s]+"
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"),
    re.compile(
        r"(?i)\b((?:api[_-]?key|secret|token|password)\s*[:=]\s*)[^\s,;&#]+"
    ),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _is_forbidden_key(key: object) -> bool:
    normalized = _normalized_key(key)
    if normalized in {_normalized_key(item) for item in _FORBIDDEN_KEYS}:
        return True
    if any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS):
        return True
    return any(normalized.endswith(suffix) for suffix in _CONTENT_KEY_SUFFIXES)


def _sanitize_string(value: str) -> str:
    sanitized = _URL_USERINFO_PATTERN.sub(r"\1[REDACTED]@", value)
    sanitized = _URL_SECRET_QUERY_PATTERN.sub(r"\1[REDACTED]", sanitized)
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        if pattern.groups:
            sanitized = pattern.sub(r"\1[REDACTED]", sanitized)
        else:
            sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def _sanitize_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, Enum):
        return _sanitize_value(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_value(item)
            for key, item in value.items()
            if not _is_forbidden_key(key)
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize_value(item) for item in value]
    return _sanitize_string(str(value))


def sanitize_audit_details(details: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Return JSON-safe audit details without credentials or raw content."""

    if not details:
        return {}
    sanitized = _sanitize_value(details)
    return sanitized if isinstance(sanitized, dict) else {}


def write_audit(
    session: Session,
    *,
    team_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[Mapping[str, Any]] = None,
) -> AuditLog:
    """Add one sanitized audit record to the caller's transaction."""

    record = AuditLog(
        team_id=team_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=json.dumps(
            sanitize_audit_details(details),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    session.add(record)
    return record


def audit_details(record: AuditLog) -> dict[str, Any]:
    try:
        value = json.loads(record.details or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
