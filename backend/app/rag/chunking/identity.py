from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Optional, Sequence


_SLUG_SEPARATOR_RE = re.compile(r"[^\w.-]+", re.UNICODE)
_REPEATED_SEPARATOR_RE = re.compile(r"-{2,}")


def normalize_content(text: str) -> str:
    """Normalize line endings and insignificant trailing whitespace."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def content_fingerprint(text: str) -> str:
    normalized = normalize_content(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = _SLUG_SEPARATOR_RE.sub("-", normalized)
    normalized = _REPEATED_SEPARATOR_RE.sub("-", normalized)
    return normalized.strip("-.")


def build_logical_chunk_key(
    source_path: str,
    heading_path: Sequence[str],
    part: Optional[int] = None,
) -> str:
    """Build a content-independent key for a structural chunk position."""

    if heading_path:
        heading_fragment = "/".join(_slug(heading) or "section" for heading in heading_path)
        key = "{0}#{1}".format(source_path, heading_fragment)
    else:
        key = source_path

    if part is not None:
        key = "{0}#part-{1}".format(key, part)
    return key


def build_chunk_id(
    document_version_id: str,
    source_path: str,
    heading_path: Sequence[str],
    content_hash: str,
    occurrence: int = 1,
    part: Optional[int] = None,
) -> str:
    """Build a deterministic ID from document, structure, content, and position."""

    if occurrence < 1:
        raise ValueError("occurrence must be at least 1")

    structural_path = "/".join(_slug(heading) for heading in heading_path)
    identity_parts = (
        document_version_id,
        source_path,
        structural_path,
        content_hash,
        "" if part is None else str(part),
        str(occurrence),
    )
    digest = hashlib.sha256("\x00".join(identity_parts).encode("utf-8")).hexdigest()
    return "chk_{0}".format(digest)
