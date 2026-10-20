from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Sequence, Tuple

from backend.app.rag.chunking.identity import (
    build_chunk_id,
    build_logical_chunk_key,
    content_fingerprint,
    normalize_content,
)
from backend.app.rag.domain.models import (
    Chunk,
    DataClassification,
    Visibility,
)


_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_FENCE_START_RE = re.compile(r"^ {0,3}(`{3,}|~{3,}).*$")


@dataclass(frozen=True)
class _Section:
    heading_path: Tuple[str, ...]
    text: str


def _heading(line: str) -> Optional[Tuple[int, str]]:
    match = _ATX_HEADING_RE.match(line)
    if match is None:
        return None
    title = (match.group(2) or "").strip()
    title = re.sub(r"[ \t]+#+[ \t]*$", "", title)
    return len(match.group(1)), title


def _fence_start(line: str) -> Optional[Tuple[str, int]]:
    match = _FENCE_START_RE.match(line)
    if match is None:
        return None
    fence = match.group(1)
    return fence[0], len(fence)


def _closes_fence(line: str, fence: Tuple[str, int]) -> bool:
    marker, minimum_length = fence
    closing_re = re.compile(
        r"^ {0,3}"
        + re.escape(marker)
        + r"{"
        + str(minimum_length)
        + r",}[ \t]*$"
    )
    return closing_re.match(line) is not None


def _strip_blank_lines(lines: Sequence[str]) -> str:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end])


def _sections(text: str) -> List[_Section]:
    sections: List[_Section] = []
    heading_stack: List[Tuple[int, str]] = []
    heading_path: Tuple[str, ...] = ()
    section_lines: List[str] = []
    fence: Optional[Tuple[str, int]] = None

    def flush() -> None:
        section_text = _strip_blank_lines(section_lines)
        if section_text:
            sections.append(_Section(heading_path=heading_path, text=section_text))

    for line in normalize_content(text).split("\n"):
        if fence is not None:
            section_lines.append(line)
            if _closes_fence(line, fence):
                fence = None
            continue

        detected_fence = _fence_start(line)
        if detected_fence is not None:
            section_lines.append(line)
            fence = detected_fence
            continue

        detected_heading = _heading(line)
        if detected_heading is None:
            section_lines.append(line)
            continue

        flush()
        level, title = detected_heading
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, title))
        heading_path = tuple(heading for _, heading in heading_stack)
        section_lines = []

    flush()
    return sections


def _paragraph_blocks(text: str) -> List[str]:
    blocks: List[str] = []
    block_lines: List[str] = []
    fence: Optional[Tuple[str, int]] = None

    def flush() -> None:
        block = _strip_blank_lines(block_lines)
        if block:
            blocks.append(block)

    for line in text.split("\n"):
        if fence is not None:
            block_lines.append(line)
            if _closes_fence(line, fence):
                fence = None
            continue

        if not line.strip():
            flush()
            block_lines = []
            continue

        detected_fence = _fence_start(line)
        if detected_fence is not None:
            fence = detected_fence
        block_lines.append(line)

    flush()
    return blocks


def _split_section(text: str, max_chars: int) -> Iterator[str]:
    current = ""
    for block in _paragraph_blocks(text):
        if len(block) > max_chars:
            if current:
                yield current
                current = ""
            for start in range(0, len(block), max_chars):
                yield block[start : start + max_chars]
            continue

        candidate = block if not current else "{0}\n\n{1}".format(current, block)
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            yield current
        current = block

    if current:
        yield current


def chunk_markdown(
    document_version_id: str,
    source_path: str,
    content: str,
    max_chars: int = 1200,
    *,
    document_id: Optional[str] = None,
    team_id: str = "",
    knowledge_base_id: str = "",
    owner_user_id: str = "",
    visibility: Visibility = Visibility.TEAM_SHARED,
    data_classification: DataClassification = DataClassification.INTERNAL,
    product: Optional[str] = None,
    version_values: Tuple[str, ...] = (),
    document_file_name: str = "",
    source_url: str = "",
) -> List[Chunk]:
    """Split Markdown into bounded chunks while retaining heading structure."""

    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero")

    chunks: List[Chunk] = []
    key_occurrences = {}

    for section in _sections(content):
        section_parts = list(_split_section(section.text, max_chars))
        for part_index, part_text in enumerate(section_parts, start=1):
            part = part_index if len(section_parts) > 1 else None
            base_key = build_logical_chunk_key(
                source_path,
                section.heading_path,
                part=part,
            )
            occurrence = key_occurrences.get(base_key, 0) + 1
            key_occurrences[base_key] = occurrence
            logical_chunk_key = (
                base_key if occurrence == 1 else "{0}~{1}".format(base_key, occurrence)
            )
            content_hash = content_fingerprint(part_text)
            chunk_id = build_chunk_id(
                document_version_id,
                source_path,
                section.heading_path,
                content_hash,
                occurrence=occurrence,
                part=part,
            )
            source_locator = {
                "source_path": source_path,
                "heading_path": list(section.heading_path),
                "document_version_id": document_version_id,
            }
            if document_id:
                source_locator["document_id"] = document_id
            if document_file_name:
                source_locator["file_name"] = document_file_name
            if source_url:
                source_locator["source_url"] = source_url
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    document_id=document_id or document_version_id,
                    document_version_id=document_version_id,
                    team_id=team_id,
                    knowledge_base_id=knowledge_base_id,
                    owner_user_id=owner_user_id,
                    visibility=visibility,
                    data_classification=data_classification,
                    source_path=source_path,
                    heading_path=section.heading_path,
                    content=part_text,
                    logical_chunk_key=logical_chunk_key,
                    content_hash=content_hash,
                    source_locator=source_locator,
                    product=product,
                    version_values=version_values,
                )
            )

    return chunks
