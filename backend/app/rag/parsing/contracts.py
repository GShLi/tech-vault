"""Structured, format-independent document parsing contracts."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ParseError(ValueError):
    def __init__(self, code: str, message: str = "", details=None):
        super().__init__(message or code)
        self.code = code
        self.details = details or {}


class NodeType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE = "code"
    PAGE_BREAK = "page_break"


@dataclass(frozen=True)
class DocumentNode:
    node_id: str
    node_type: NodeType
    text: str
    heading_path: Tuple[str, ...] = ()
    page_no: Optional[int] = None
    bbox: Optional[Tuple[float, float, float, float]] = None
    reading_order: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_locator: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParseQuality:
    character_count: int
    node_count: int
    heading_count: int
    degraded_table_count: int = 0
    page_count: int = 0
    garbled_ratio: float = 0.0


@dataclass(frozen=True)
class ParsedDocument:
    nodes: List[DocumentNode]
    parser_name: str
    parser_version: str
    pdf_kind: Optional[str]
    warnings: Tuple[str, ...]
    quality: ParseQuality
    metadata: Dict[str, Any] = field(default_factory=dict)


def parsed_document(nodes, name, *, pdf_kind=None, warnings=(), metadata=None):
    text = "\n".join(node.text for node in nodes)
    if not text.strip():
        raise ParseError("EMPTY_DOCUMENT")
    return ParsedDocument(
        nodes, name, "2", pdf_kind, tuple(warnings),
        ParseQuality(
            len(text), len(nodes),
            sum(node.node_type == NodeType.HEADING for node in nodes),
            sum(bool(node.metadata.get("table_parse_degraded")) for node in nodes),
            max((node.page_no or 0 for node in nodes), default=0),
            text.count("\ufffd") / max(1, len(text)),
        ),
        metadata or {},
    )
