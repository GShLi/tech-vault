# Document Parsing and Semantic Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace character-based splitting with type-aware parsing, BGE-M3 token-budgeted semantic chunks, Parent-Child context, and fail-closed vectorization.

**Architecture:** Parser adapters emit a shared `DocumentNode` tree. A token-aware semantic chunker creates parent and child chunks with sentence/word-safe boundaries. Child chunks are indexed; parent chunks are persisted and hydrated as LLM context from PostgreSQL.

**Tech Stack:** FastAPI, SQLAlchemy, pypdf, PyMuPDF, python-docx, BGE-M3 FlagEmbedding service, Elasticsearch, Qdrant, pytest, Vue 3 diagnostics.

**Spec:** `docs/superpowers/specs/2026-10-21-document-parsing-semantic-chunking-design.md`

## Global Constraints

- Native electronic PDFs use PyMuPDF. Scanned and mixed PDFs are rejected with `PDF_SCANNED_UNSUPPORTED` and `PDF_MIXED_UNSUPPORTED`.
- Structure-first boundaries are heading, paragraph, list, sentence, whitespace, punctuation, then character fallback.
- Prose child budget: 480 target, 512 maximum, 64 overlap.
- Prose parent budget: 1200 target, 1400 maximum.
- Code child budget: 120 target, 160 maximum, 16 overlap.
- Table child maximum: 512 tokens.
- Token counts use the BGE-M3 tokenizer through `POST /tokenize`.
- Parent chunks are stored in PostgreSQL and are never written to Elasticsearch or Qdrant.
- Child overrides must be reflected in parent context; unsafe range updates block generation.
- Ingestion must fail closed when real tokenizer or embedding services are unavailable.
- Do not use hash embeddings during document ingestion outside tests.
- Do not mutate an active generation. Build, validate, then activate a new generation.
- Use Python 3.9-compatible annotations.
- Keep changes scoped to the existing FastAPI/SQLAlchemy/Vue patterns.

---

## File Structure

Create:

- `backend/app/rag/parsing/contracts.py` — `DocumentNode`, `ParsedDocument`, quality and parser interfaces.
- `backend/app/rag/parsing/router.py` — file-type and PDF-kind routing.
- `backend/app/rag/parsing/markdown_parser.py` — Markdown/TXT nodes.
- `backend/app/rag/parsing/docx_parser.py` — ordered DOCX paragraphs, headings and tables.
- `backend/app/rag/parsing/pdf_classifier.py` — native/scanned/mixed classification.
- `backend/app/rag/parsing/native_pdf_parser.py` — PyMuPDF native PDF parsing.
- `backend/app/rag/parsing/sentences.py` — safe sentence/word boundaries.
- `backend/app/rag/chunking/semantic.py` — token-aware Parent-Child construction.
- `backend/app/rag/chunking/quality.py` — parse/chunk/embedding quality reports.
- `backend/tests/parsing/test_document_nodes.py`
- `backend/tests/parsing/test_docx_parser.py`
- `backend/tests/parsing/test_pdf_classifier.py`
- `backend/tests/parsing/test_native_pdf_parser.py`
- `backend/tests/chunking/test_semantic_chunking.py`
- `backend/tests/chunking/test_chunk_quality.py`
- `backend/tests/embedding/test_tokenizer_service.py`
- `backend/tests/api/test_parent_child_context.py`

Modify:

- `pyproject.toml` — add PyMuPDF.
- `deploy/embedding_service.py` — add `/tokenize`.
- `backend/app/rag/embedding/service.py` — tokenizer client and fail-closed embedding option.
- `backend/app/rag/parsing/documents.py` — delegate legacy parsing to the router.
- `backend/app/rag/domain/models.py` — Parent-Child and parse metadata fields on `Chunk`.
- `backend/app/db/models.py` — new chunk/version/run metadata columns.
- `backend/app/db/session.py` — idempotent schema bridges.
- `backend/app/rag/ingestion/processor.py` — new parse/chunk/tokenize/embed pipeline.
- `backend/app/rag/indexing/elasticsearch.py` — child-only payload and filters.
- `backend/app/rag/indexing/qdrant.py` — child-only payload and filters.
- `backend/app/rag/retrieval/filters.py` — enforce `chunk_level=child`.
- `backend/app/api/v1/chats.py` — hydrate parent context before rerank/generation.
- `backend/app/api/v1/documents.py` — expose parse/chunk quality metadata.
- `backend/tests/api/test_documents.py`, `backend/tests/api/test_chat_retrieval_generation.py`
- `docs/api/api-contract.md`, `docs/product/page-map.md`

---

### Task 1: Parsing Contracts and PyMuPDF Dependency

**Files:**
- Create: `backend/app/rag/parsing/contracts.py`
- Create: `backend/tests/parsing/test_document_nodes.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `NodeType`, `DocumentNode`, `ParseQuality`, `ParsedDocument`, `DocumentParser`, `DocumentDescriptor`.

- [ ] **Step 1: Write failing contract tests**

```python
from backend.app.rag.parsing.contracts import (
    DocumentNode,
    NodeType,
    ParseQuality,
    ParsedDocument,
)


def test_document_node_keeps_structure_and_location():
    node = DocumentNode(
        node_id="node-1",
        node_type=NodeType.PARAGRAPH,
        text="Spring Boot requires Java 17.",
        heading_path=("Spring Boot", "Requirements"),
        page_no=2,
        bbox=(10.0, 20.0, 200.0, 60.0),
        reading_order=4,
        metadata={"font_size": 11.0},
        source_locator={"page_no": 2},
    )

    assert node.node_type.value == "paragraph"
    assert node.heading_path == ("Spring Boot", "Requirements")
    assert node.page_no == 2


def test_parsed_document_reports_parser_and_quality():
    parsed = ParsedDocument(
        nodes=[
            DocumentNode(
                node_id="node-1",
                node_type=NodeType.HEADING,
                text="Spring Boot",
                heading_path=("Spring Boot",),
                page_no=1,
                bbox=None,
                reading_order=1,
                metadata={},
                source_locator={"page_no": 1},
            )
        ],
        parser_name="markdown",
        parser_version="1",
        pdf_kind=None,
        warnings=(),
        quality=ParseQuality(
            character_count=12,
            node_count=1,
            heading_count=1,
            degraded_table_count=0,
            page_count=None,
        ),
    )

    assert parsed.parser_name == "markdown"
    assert parsed.quality.heading_count == 1
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_document_nodes.py -q
```

Expected: collection fails because `contracts.py` does not exist.

- [ ] **Step 3: Add PyMuPDF dependency**

```toml
# pyproject.toml [project.optional-dependencies].api
"PyMuPDF>=1.24,<2",
```

- [ ] **Step 4: Implement contracts**

```python
# backend/app/rag/parsing/contracts.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple, List


class NodeType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE = "code"
    PAGE_BREAK = "page_break"


@dataclass(frozen=True)
class DocumentDescriptor:
    file_name: str
    mime_type: str = ""
    pdf_kind: Optional[str] = None


@dataclass(frozen=True)
class DocumentNode:
    node_id: str
    node_type: NodeType
    text: str
    heading_path: Tuple[str, ...]
    page_no: Optional[int]
    bbox: Optional[Tuple[float, float, float, float]]
    reading_order: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_locator: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParseQuality:
    character_count: int
    node_count: int
    heading_count: int
    degraded_table_count: int
    page_count: Optional[int] = None
    garbled_ratio: float = 0.0
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedDocument:
    nodes: List[DocumentNode]
    parser_name: str
    parser_version: str
    pdf_kind: Optional[str]
    warnings: Tuple[str, ...]
    quality: ParseQuality


class DocumentParser(Protocol):
    def supports(self, descriptor: DocumentDescriptor) -> bool: ...

    def parse(
        self,
        source: Path,
        descriptor: DocumentDescriptor,
    ) -> ParsedDocument: ...
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_document_nodes.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml backend/app/rag/parsing/contracts.py backend/tests/parsing/test_document_nodes.py
git commit -m "feat: add structured document parsing contracts"
```

---

### Task 2: Markdown/TXT Parser and Router

**Files:**
- Create: `backend/app/rag/parsing/markdown_parser.py`
- Create: `backend/app/rag/parsing/router.py`
- Modify: `backend/app/rag/parsing/documents.py`
- Test: `backend/tests/parsing/test_document_nodes.py`

**Interfaces:**
- Consumes: `DocumentNode`, `ParsedDocument`, `DocumentDescriptor`.
- Produces: `MarkdownParser.parse(...)`, `parse_document(path, *, file_name, mime_type="") -> ParsedDocument`.

- [ ] **Step 1: Add failing Markdown parser test**

```python
from pathlib import Path
from backend.app.rag.parsing.contracts import NodeType
from backend.app.rag.parsing.router import parse_document


def test_markdown_router_preserves_headings_paragraphs_and_code(tmp_path: Path):
    source = tmp_path / "guide.md"
    source.write_text(
        "# Spring Boot\n\n"
        "Spring Boot requires Java 17.\n\n"
        "```java\n"
        "# this is code, not a heading\n"
        "```\n",
        encoding="utf-8",
    )

    parsed = parse_document(source, file_name="guide.md", mime_type="text/markdown")

    assert parsed.parser_name == "markdown"
    assert [node.node_type for node in parsed.nodes] == [
        NodeType.HEADING,
        NodeType.PARAGRAPH,
        NodeType.CODE,
    ]
    assert parsed.nodes[0].heading_path == ("Spring Boot",)
    assert "# this is code" in parsed.nodes[2].text
```

- [ ] **Step 2: Run test and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_document_nodes.py::test_markdown_router_preserves_headings_paragraphs_and_code -q
```

Expected: FAIL because `router.py` is missing.

- [ ] **Step 3: Implement Markdown parser**

```python
# backend/app/rag/parsing/markdown_parser.py
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import List, Tuple

from backend.app.rag.chunking.identity import normalize_content
from backend.app.rag.parsing.contracts import (
    DocumentDescriptor,
    DocumentNode,
    NodeType,
    ParseQuality,
    ParsedDocument,
)


_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*)$")
_FENCE = re.compile(r"^ {0,3}(```|~~~)")


class MarkdownParser:
    def supports(self, descriptor: DocumentDescriptor) -> bool:
        return Path(descriptor.file_name).suffix.lower() in {".md", ".txt"}

    def parse(self, source: Path, descriptor: DocumentDescriptor) -> ParsedDocument:
        text = normalize_content(source.read_text(encoding="utf-8-sig"))
        lines = text.split("\n")
        nodes: List[DocumentNode] = []
        heading_stack: List[Tuple[int, str]] = []
        buffer: List[str] = []
        node_type = NodeType.PARAGRAPH
        fence = ""

        def heading_path() -> Tuple[str, ...]:
            return tuple(title for _, title in heading_stack)

        def flush() -> None:
            nonlocal buffer
            body = "\n".join(buffer).strip()
            if body:
                digest = hashlib.sha1(
                    "{0}\0{1}".format(node_type.value, body).encode("utf-8")
                ).hexdigest()[:16]
                nodes.append(
                    DocumentNode(
                        node_id="md-" + digest,
                        node_type=node_type,
                        text=body,
                        heading_path=heading_path(),
                        page_no=None,
                        bbox=None,
                        reading_order=len(nodes) + 1,
                        metadata={},
                        source_locator={"file_name": descriptor.file_name},
                    )
                )
            buffer = []

        for line in lines:
            if fence:
                buffer.append(line)
                if line.strip().startswith(fence):
                    flush()
                    fence = ""
                continue

            fence_match = _FENCE.match(line)
            if fence_match:
                flush()
                node_type = NodeType.CODE
                fence = fence_match.group(1)
                buffer.append(line)
                continue

            heading = _HEADING.match(line)
            if heading:
                flush()
                level = len(heading.group(1))
                title = heading.group(2).strip()
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, title))
                nodes.append(
                    DocumentNode(
                        node_id="md-heading-{0}".format(len(nodes) + 1),
                        node_type=NodeType.HEADING,
                        text=title,
                        heading_path=heading_path(),
                        page_no=None,
                        bbox=None,
                        reading_order=len(nodes) + 1,
                        metadata={"level": level},
                        source_locator={"file_name": descriptor.file_name},
                    )
                )
                node_type = NodeType.PARAGRAPH
                continue

            if not line.strip():
                flush()
                node_type = NodeType.PARAGRAPH
                continue

            buffer.append(line)
        flush()
        warnings = ()
        quality = ParseQuality(
            character_count=len(text),
            node_count=len(nodes),
            heading_count=sum(
                1 for node in nodes if node.node_type is NodeType.HEADING
            ),
            degraded_table_count=0,
            warnings=warnings,
        )
        return ParsedDocument(
            nodes=nodes,
            parser_name="markdown",
            parser_version="1",
            pdf_kind=None,
            warnings=warnings,
            quality=quality,
        )
```

- [ ] **Step 4: Implement router for Markdown/TXT and leave explicit PDF errors**

```python
# backend/app/rag/parsing/router.py
from pathlib import Path
from typing import Optional

from backend.app.rag.parsing.contracts import ParsedDocument
from backend.app.rag.parsing.markdown_parser import MarkdownParser


def parse_document(
    source: Path,
    *,
    file_name: str,
    mime_type: str = "",
) -> ParsedDocument:
    from backend.app.rag.parsing.contracts import DocumentDescriptor

    descriptor = DocumentDescriptor(file_name=file_name, mime_type=mime_type)
    suffix = Path(file_name).suffix.lower()
    if suffix in {".md", ".txt"}:
        return MarkdownParser().parse(source, descriptor)
    raise ValueError("No parser registered for {0}".format(suffix))
```

`documents.py` keeps `UnsupportedDocumentType` and exports:

```python
def parse_document_text(
    path,
    *,
    file_name: Optional[str] = None,
    mime_type: str = "",
) -> str:
    parsed = parse_document(
        Path(path),
        file_name=file_name or Path(path).name,
        mime_type=mime_type,
    )
    return "\n\n".join(node.text for node in parsed.nodes)
```

This compatibility function is removed in Task 12 after the ingestion processor migrates.

- [ ] **Step 5: Add Markdown list and table nodes**

Tests:

```python
def test_markdown_parser_emits_list_and_table_nodes(tmp_path: Path):
    source = tmp_path / "types.md"
    source.write_text(
        "# Data\n\n"
        "- Java\n"
        "- Spring\n\n"
        "| Version | JDK |\n"
        "| --- | --- |\n"
        "| 3.2 | 17 |\n",
        encoding="utf-8",
    )
    parsed = parse_document(source, file_name="types.md", mime_type="text/markdown")
    assert [node.node_type for node in parsed.nodes][-2:] == [
        NodeType.LIST,
        NodeType.TABLE,
    ]
```

Implementation:

```python
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def _block_type(lines):
    nonempty = [line for line in lines if line.strip()]
    if nonempty and all(_LIST_ITEM.match(line) for line in nonempty):
        return NodeType.LIST
    if (
        len(nonempty) >= 2
        and all(line.strip().startswith("|") for line in nonempty)
    ):
        return NodeType.TABLE
    return NodeType.PARAGRAPH
```

In `flush()`, replace the fixed `node_type` with:

```python
detected_type = (
    node_type
    if node_type is NodeType.CODE
    else _block_type(buffer)
)
```

Use `detected_type` for the node and metadata. Table nodes additionally store
`rows=[line.strip().strip("|").split("|") for line in buffer]`.

- [ ] **Step 6: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_document_nodes.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/rag/parsing/markdown_parser.py backend/app/rag/parsing/router.py backend/app/rag/parsing/documents.py backend/tests/parsing/test_document_nodes.py
git commit -m "feat: add structured markdown parser and router"
```

---

### Task 3: Ordered DOCX Parser

**Files:**
- Create: `backend/app/rag/parsing/docx_parser.py`
- Create: `backend/tests/parsing/test_docx_parser.py`
- Modify: `backend/app/rag/parsing/router.py`

**Interfaces:**
- Consumes: `DocumentNode`, `ParsedDocument`, `DocumentDescriptor`.
- Produces: `DocxParser.parse(...)` preserving paragraph/table order.

- [ ] **Step 1: Write failing DOCX order test**

```python
from pathlib import Path
from docx import Document

from backend.app.rag.parsing.contracts import NodeType
from backend.app.rag.parsing.router import parse_document


def test_docx_preserves_paragraph_and_table_order(tmp_path: Path):
    path = tmp_path / "guide.docx"
    document = Document()
    document.add_heading("Requirements", level=1)
    document.add_paragraph("Spring Boot requires Java 17.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Version"
    table.cell(1, 0).text = "Java"
    table.cell(1, 1).text = "17"
    document.add_paragraph("Installation follows.")
    document.save(path)

    parsed = parse_document(
        path,
        file_name="guide.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert [node.node_type for node in parsed.nodes] == [
        NodeType.HEADING,
        NodeType.PARAGRAPH,
        NodeType.TABLE,
        NodeType.PARAGRAPH,
    ]
    assert parsed.nodes[2].metadata["rows"][1] == ["Java", "17"]
```

- [ ] **Step 2: Run test and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_docx_parser.py -q
```

Expected: FAIL because no `.docx` parser is routed.

- [ ] **Step 3: Implement DOCX parser**

```python
# backend/app/rag/parsing/docx_parser.py
from __future__ import annotations

from pathlib import Path
from typing import List

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from backend.app.rag.parsing.contracts import (
    DocumentDescriptor,
    DocumentNode,
    NodeType,
    ParseQuality,
    ParsedDocument,
)


def _iter_blocks(document):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


class DocxParser:
    def supports(self, descriptor: DocumentDescriptor) -> bool:
        return Path(descriptor.file_name).suffix.lower() == ".docx"

    def parse(self, source: Path, descriptor: DocumentDescriptor) -> ParsedDocument:
        document = Document(str(source))
        nodes: List[DocumentNode] = []
        heading_stack = []

        def heading_path():
            return tuple(title for _, title in heading_stack)

        for block in _iter_blocks(document):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                style = block.style.name if block.style is not None else ""
                level = 0
                if style.casefold() == "title":
                    level = 1
                elif style.casefold().startswith("heading "):
                    suffix = style.split()[-1]
                    if suffix.isdigit() and 1 <= int(suffix) <= 6:
                        level = int(suffix)
                if level:
                    while heading_stack and heading_stack[-1][0] >= level:
                        heading_stack.pop()
                    heading_stack.append((level, text))
                    node_type = NodeType.HEADING
                else:
                    node_type = NodeType.PARAGRAPH
                nodes.append(
                    DocumentNode(
                        node_id="docx-{0}".format(len(nodes) + 1),
                        node_type=node_type,
                        text=text,
                        heading_path=heading_path(),
                        page_no=None,
                        bbox=None,
                        reading_order=len(nodes) + 1,
                        metadata={"style": style, "level": level},
                        source_locator={"file_name": descriptor.file_name},
                    )
                )
            else:
                rows = [
                    [cell.text.strip() for cell in row.cells]
                    for row in block.rows
                ]
                rows = [row for row in rows if any(row)]
                if not rows:
                    continue
                markdown = "\n".join(
                    "| " + " | ".join(row) + " |" for row in rows
                )
                nodes.append(
                    DocumentNode(
                        node_id="docx-table-{0}".format(len(nodes) + 1),
                        node_type=NodeType.TABLE,
                        text=markdown,
                        heading_path=heading_path(),
                        page_no=None,
                        bbox=None,
                        reading_order=len(nodes) + 1,
                        metadata={"rows": rows, "header": rows[0]},
                        source_locator={"file_name": descriptor.file_name},
                    )
                )

        warnings = ()
        quality = ParseQuality(
            character_count=sum(len(node.text) for node in nodes),
            node_count=len(nodes),
            heading_count=sum(
                1 for node in nodes if node.node_type is NodeType.HEADING
            ),
            degraded_table_count=0,
            warnings=warnings,
        )
        return ParsedDocument(
            nodes=nodes,
            parser_name="docx",
            parser_version="1",
            pdf_kind=None,
            warnings=warnings,
            quality=quality,
        )
```

Router:

```python
if suffix == ".docx":
    from backend.app.rag.parsing.docx_parser import DocxParser
    return DocxParser().parse(source, descriptor)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_docx_parser.py backend/tests/parsing/test_document_nodes.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/parsing/docx_parser.py backend/app/rag/parsing/router.py backend/tests/parsing/test_docx_parser.py
git commit -m "feat: parse docx blocks in source order"
```

---

### Task 4: PDF Classification

**Files:**
- Create: `backend/app/rag/parsing/pdf_classifier.py`
- Create: `backend/tests/parsing/test_pdf_classifier.py`
- Modify: `backend/app/rag/parsing/router.py`

**Interfaces:**
- Produces: `PdfClassification`, `classify_pdf(path) -> PdfClassification`.
- Produces: router errors `PDF_SCANNED_UNSUPPORTED`, `PDF_MIXED_UNSUPPORTED`.

- [ ] **Step 1: Write failing classifier tests with generated PDFs**

```python
from pathlib import Path

import pymupdf

from backend.app.rag.parsing.pdf_classifier import classify_pdf


def _new_pdf(path: Path, *, text: str, draw_image: bool):
    document = pymupdf.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    if draw_image:
        page.draw_rect(pymupdf.Rect(72, 100, 500, 700), fill=(0.8, 0.8, 0.8))
    document.save(path)
    document.close()


def test_pdf_classifier_detects_native_text_pdf(tmp_path: Path):
    path = tmp_path / "native.pdf"
    _new_pdf(path, text="Spring Boot requires Java 17. " * 10, draw_image=False)
    assert classify_pdf(path).kind == "native"


def test_pdf_classifier_detects_scanned_pdf(tmp_path: Path):
    path = tmp_path / "scanned.pdf"
    _new_pdf(path, text="", draw_image=True)
    assert classify_pdf(path).kind == "scanned"


def test_pdf_classifier_detects_mixed_pdf(tmp_path: Path):
    path = tmp_path / "mixed.pdf"
    _new_pdf(path, text="Readable text " * 20, draw_image=True)
    assert classify_pdf(path).kind == "mixed"
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_pdf_classifier.py -q
```

Expected: FAIL because the classifier is missing.

- [ ] **Step 3: Implement classifier**

```python
# backend/app/rag/parsing/pdf_classifier.py
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import pymupdf


@dataclass(frozen=True)
class PdfClassification:
    kind: str
    page_kinds: Tuple[str, ...]
    text_characters: Tuple[int, ...]
    image_area_ratios: Tuple[float, ...]


def _page_metrics(page) -> tuple:
    text = page.get_text("text").strip()
    page_area = max(1.0, page.rect.width * page.rect.height)
    image_area = 0.0
    for block in page.get_text("blocks"):
        block_type = block[6] if len(block) > 6 else 0
        if block_type != 1:
            continue
        rect = pymupdf.Rect(block[:4])
        image_area += max(0.0, rect.width * rect.height)
    return len(text), min(1.0, image_area / page_area)


def classify_pdf(path: Path) -> PdfClassification:
    document = pymupdf.open(str(path))
    page_kinds = []
    chars = []
    image_ratios = []
    try:
        for page in document:
            character_count, image_ratio = _page_metrics(page)
            chars.append(character_count)
            image_ratios.append(image_ratio)
            if character_count < 50 and image_ratio >= 0.3:
                page_kinds.append("scanned")
            elif image_ratio >= 0.3:
                page_kinds.append("mixed")
            else:
                page_kinds.append("native")
    finally:
        document.close()
    scanned = sum(1 for kind in page_kinds if kind == "scanned")
    mixed = sum(1 for kind in page_kinds if kind == "mixed")
    majority = len(page_kinds) // 2 + 1
    if scanned >= majority:
        kind = "scanned"
    elif mixed >= majority:
        kind = "mixed"
    elif scanned + mixed:
        kind = "mixed"
    else:
        kind = "native"
    return PdfClassification(
        kind=kind,
        page_kinds=tuple(page_kinds),
        text_characters=tuple(chars),
        image_area_ratios=tuple(image_ratios),
    )
```

Router PDF branch:

```python
if suffix == ".pdf":
    from backend.app.rag.parsing.pdf_classifier import classify_pdf
    classification = classify_pdf(source)
    if classification.kind == "scanned":
        raise UnsupportedDocumentType("PDF_SCANNED_UNSUPPORTED")
    if classification.kind == "mixed":
        raise UnsupportedDocumentType("PDF_MIXED_UNSUPPORTED")
    from backend.app.rag.parsing.native_pdf_parser import NativePdfParser
    return NativePdfParser().parse(source, descriptor, classification)
```

`UnsupportedDocumentType` must expose a stable `code` attribute in addition to its
message.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_pdf_classifier.py -q
```

Expected: PASS. The mixed fixture depends on PyMuPDF image block reporting; if it
reports the rectangle as a drawing rather than an image block, adjust the fixture to
insert a real image and retain the same heuristic assertions.

- [ ] **Step 5: Commit**

```bash
git add backend/app/rag/parsing/pdf_classifier.py backend/app/rag/parsing/router.py backend/tests/parsing/test_pdf_classifier.py
git commit -m "feat: classify native scanned and mixed PDFs"
```

---

### Task 5: Native PDF Parsing

**Files:**
- Create: `backend/app/rag/parsing/native_pdf_parser.py`
- Create: `backend/tests/parsing/test_native_pdf_parser.py`
- Modify: `backend/app/rag/parsing/router.py`

**Interfaces:**
- Consumes: `PdfClassification`, `DocumentNode`.
- Produces: `NativePdfParser.parse(source, descriptor, classification) -> ParsedDocument`.
- Node metadata includes `font_size`, `bold`, `block_type`, `column`, and optional table rows.

- [ ] **Step 1: Write failing native PDF tests**

```python
from pathlib import Path

import pymupdf

from backend.app.rag.parsing.contracts import NodeType
from backend.app.rag.parsing.router import parse_document


def test_native_pdf_preserves_page_heading_and_paragraph(tmp_path: Path):
    path = tmp_path / "spring.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "System Requirements", fontsize=18)
    page.insert_text(
        (72, 110),
        "Spring Boot requires Java SDK v17 or higher.",
        fontsize=11,
    )
    document.save(path)
    document.close()

    parsed = parse_document(path, file_name="spring.pdf", mime_type="application/pdf")

    assert parsed.pdf_kind == "native"
    assert any(node.node_type is NodeType.HEADING for node in parsed.nodes)
    paragraph = next(
        node for node in parsed.nodes if "Java SDK v17" in node.text
    )
    assert paragraph.page_no == 1
    assert paragraph.source_locator["page_no"] == 1
```

- [ ] **Step 2: Run test and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_native_pdf_parser.py -q
```

Expected: FAIL because `NativePdfParser` is missing.

- [ ] **Step 3: Implement native PDF parser**

```python
# backend/app/rag/parsing/native_pdf_parser.py
from __future__ import annotations

import hashlib
import re
import statistics
from pathlib import Path
from typing import List, Tuple

import pymupdf

from backend.app.rag.parsing.contracts import (
    DocumentDescriptor,
    DocumentNode,
    NodeType,
    ParseQuality,
    ParsedDocument,
)
from backend.app.rag.parsing.pdf_classifier import PdfClassification


def _node_id(prefix: str, text: str, order: int) -> str:
    digest = hashlib.sha1(
        "{0}\0{1}\0{2}".format(prefix, text, order).encode("utf-8")
    ).hexdigest()[:16]
    return prefix + "-" + digest


def _block_tuple(block) -> tuple:
    return (
        float(block[0]),
        float(block[1]),
        float(block[2]),
        float(block[3]),
        str(block[4] or "").strip(),
        int(block[5]),
        int(block[6]) if len(block) > 6 else 0,
    )


class NativePdfParser:
    def supports(self, descriptor: DocumentDescriptor) -> bool:
        return (
            Path(descriptor.file_name).suffix.lower() == ".pdf"
            and descriptor.pdf_kind == "native"
        )

    def parse(
        self,
        source: Path,
        descriptor: DocumentDescriptor,
        classification: PdfClassification,
    ) -> ParsedDocument:
        document = pymupdf.open(str(source))
        nodes: List[DocumentNode] = []
        warnings: List[str] = []
        heading_stack: List[Tuple[int, str]] = []
        reading_order = 0

        try:
            page_font_sizes = []
            for page in document:
                sizes = []
                for block in page.get_text("dict").get("blocks", []):
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            if str(span.get("text", "")).strip():
                                sizes.append(float(span.get("size", 0.0)))
                page_font_sizes.append(sizes)
            body_median = statistics.median(
                [size for sizes in page_font_sizes for size in sizes] or [11.0]
            )

            for page_number, page in enumerate(document, start=1):
                page_dict = page.get_text("dict")
                blocks = sorted(
                    (_block_tuple(block) for block in page.get_text("blocks")),
                    key=lambda item: (round(item[0] / 40), item[1], item[0]),
                )
                for block in blocks:
                    x0, y0, x1, y1, text, block_no, block_type = block
                    if block_type != 0 or not text:
                        continue
                    reading_order += 1
                    lines = [
                        line.strip()
                        for line in text.splitlines()
                        if line.strip()
                    ]
                    font_size = body_median
                    bold = False
                    for candidate in page_dict.get("blocks", []):
                        if tuple(candidate.get("bbox", ())) != (x0, y0, x1, y1):
                            continue
                        spans = [
                            span
                            for line in candidate.get("lines", [])
                            for span in line.get("spans", [])
                        ]
                        if spans:
                            font_size = max(
                                float(span.get("size", body_median))
                                for span in spans
                            )
                            bold = any(
                                int(span.get("flags", 0)) & 16
                                for span in spans
                            )
                        break
                    is_heading = (
                        len(text) <= 160
                        and len(lines) <= 3
                        and (font_size >= body_median + 1.5 or bold)
                    )
                    if is_heading:
                        level = 1 if font_size >= body_median + 4 else 2
                        title = " ".join(lines)
                        while heading_stack and heading_stack[-1][0] >= level:
                            heading_stack.pop()
                        heading_stack.append((level, title))
                        node_type = NodeType.HEADING
                    else:
                        node_type = NodeType.PARAGRAPH
                    heading_path = tuple(title for _, title in heading_stack)
                    source_locator = {
                        "page_no": page_number,
                        "bbox": [x0, y0, x1, y1],
                        "file_name": descriptor.file_name,
                    }
                    nodes.append(
                        DocumentNode(
                            node_id=_node_id(
                                "pdf-page-{0}".format(page_number),
                                text,
                                reading_order,
                            ),
                            node_type=node_type,
                            text=" ".join(lines),
                            heading_path=heading_path,
                            page_no=page_number,
                            bbox=(x0, y0, x1, y1),
                            reading_order=reading_order,
                            metadata={
                                "font_size": font_size,
                                "bold": bold,
                                "block_no": block_no,
                                "column": round(x0 / 40),
                            },
                            source_locator=source_locator,
                        )
                    )

                try:
                    tables = page.find_tables()
                except Exception:
                    tables = None
                if tables is not None:
                    for table in tables.tables:
                        rows = table.extract()
                        if not rows:
                            continue
                        reading_order += 1
                        markdown = "\n".join(
                            "| " + " | ".join(
                                str(cell or "").strip() for cell in row
                            ) + " |"
                            for row in rows
                        )
                        nodes.append(
                            DocumentNode(
                                node_id=_node_id(
                                    "pdf-table-{0}".format(page_number),
                                    markdown,
                                    reading_order,
                                ),
                                node_type=NodeType.TABLE,
                                text=markdown,
                                heading_path=tuple(
                                    title for _, title in heading_stack
                                ),
                                page_no=page_number,
                                bbox=tuple(float(value) for value in table.bbox),
                                reading_order=reading_order,
                                metadata={
                                    "rows": rows,
                                    "header": rows[0],
                                    "table_parse_degraded": False,
                                },
                                source_locator={
                                    "page_no": page_number,
                                    "bbox": [float(value) for value in table.bbox],
                                    "file_name": descriptor.file_name,
                                },
                            )
                        )
        finally:
            document.close()

        if not any(node.text.strip() for node in nodes):
            raise RuntimeError("PDF_LAYOUT_PARSE_FAILED")

        quality = ParseQuality(
            character_count=sum(len(node.text) for node in nodes),
            node_count=len(nodes),
            heading_count=sum(
                1 for node in nodes if node.node_type is NodeType.HEADING
            ),
            degraded_table_count=sum(
                1
                for node in nodes
                if node.metadata.get("table_parse_degraded")
            ),
            page_count=len(classification.page_kinds),
            warnings=tuple(warnings),
        )
        return ParsedDocument(
            nodes=nodes,
            parser_name="pymupdf-native",
            parser_version="1",
            pdf_kind=classification.kind,
            warnings=tuple(warnings),
            quality=quality,
        )
```

Before appending a page's text and table nodes to the global list, merge them into
one `page_nodes` list and sort by `(round(bbox[0] / 40), bbox[1], bbox[0])` so a
detected table is not incorrectly moved to the end of the page. After sorting,
reassign global reading order and recompute heading context from heading nodes in
that ordered list:

```python
from dataclasses import replace

page_nodes.sort(
    key=lambda node: (
        round((node.bbox or (0.0, 0.0, 0.0, 0.0))[0] / 40),
        (node.bbox or (0.0, 0.0, 0.0, 0.0))[1],
        (node.bbox or (0.0, 0.0, 0.0, 0.0))[0],
    )
)
for offset, node in enumerate(page_nodes, start=1):
    page_nodes[offset - 1] = replace(
        node,
        reading_order=reading_order + offset,
    )
reading_order += len(page_nodes)
nodes.extend(page_nodes)
```

Router passes `descriptor` with `pdf_kind="native"`:

```python
from dataclasses import replace
descriptor = replace(descriptor, pdf_kind=classification.kind)
return NativePdfParser().parse(source, descriptor, classification)
```

- [ ] **Step 4: Remove repeated page headers and footers**

Add a parser test:

```python
def test_native_pdf_removes_repeated_page_headers_and_footers(tmp_path: Path):
    path = tmp_path / "headers.pdf"
    document = pymupdf.open()
    for page_no in range(1, 4):
        page = document.new_page()
        page.insert_text((40, 20), "Spring Boot Reference", fontsize=8)
        page.insert_text(
            (72, 120),
            "Body page {0} with Java 17 requirements.".format(page_no),
            fontsize=11,
        )
        page.insert_text(
            (40, 820),
            "Page {0} of 3".format(page_no),
            fontsize=8,
        )
    document.save(path)
    document.close()

    parsed = parse_document(path, file_name="headers.pdf", mime_type="application/pdf")

    text = "\n".join(node.text for node in parsed.nodes)
    assert "Spring Boot Reference" not in text
    assert "Page 1 of 3" not in text
    assert "Body page 1" in text
```

Implementation:

```python
def _margin_key(block, page_height):
    x0, y0, x1, y1, text = block[:5]
    normalized = " ".join(str(text).split())
    if not normalized:
        return None
    if y0 <= page_height * 0.08 or y1 >= page_height * 0.92:
        return re.sub(r"\d+", "{}", normalized)
    return None


def _repeated_margin_keys(document):
    counts = {}
    for page in document:
        seen = set()
        for block in page.get_text("blocks"):
            key = _margin_key(block, page.rect.height)
            if key and key not in seen:
                seen.add(key)
                counts[key] = counts.get(key, 0) + 1
    threshold = max(2, int(len(document) * 0.3 + 0.999))
    return {key for key, count in counts.items() if count >= threshold}
```

Before processing page blocks:

```python
repeated_margins = _repeated_margin_keys(document)
```

Inside the block loop, skip a block when:

```python
margin_key = _margin_key(block, page.rect.height)
if margin_key in repeated_margins:
    continue
```

This removes repeated margin lines. Page numbers with changing digits are normalized
to the same key before counting.

- [ ] **Step 5: Run PDF parser tests**

```bash
.venv/bin/python -m pytest backend/tests/parsing/test_native_pdf_parser.py backend/tests/parsing/test_pdf_classifier.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/rag/parsing/native_pdf_parser.py backend/app/rag/parsing/router.py backend/tests/parsing/test_native_pdf_parser.py
git commit -m "feat: parse native PDFs with layout metadata"
```

---

### Task 6: BGE-M3 Tokenizer Endpoint and Client

**Files:**
- Modify: `deploy/embedding_service.py`
- Modify: `backend/app/rag/embedding/service.py`
- Create: `backend/tests/embedding/test_tokenizer_service.py`

**Interfaces:**
- Produces: `POST /tokenize` and `EmbeddingClient.tokenize(texts) -> List[int]`.
- Produces: `EmbeddingError` for tokenizer/embedding outages.

- [ ] **Step 1: Write failing tokenizer service tests**

```python
import httpx
import pytest

from backend.app.rag.embedding.service import EmbeddingClient, EmbeddingError


def test_embedding_client_uses_tokenize_endpoint():
    def handler(request):
        assert request.url.path == "/tokenize"
        return httpx.Response(
            200,
            json={
                "counts": [3, 5],
                "model": "BAAI/bge-m3",
                "max_length": 8192,
            },
        )

    client = EmbeddingClient(
        "http://embedding",
        transport=httpx.MockTransport(handler),
    )
    assert client.tokenize(["a b c", "d e f g h"]) == [3, 5]


def test_tokenizer_error_is_not_silently_hidden():
    client = EmbeddingClient(
        "http://embedding",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"detail": "loading"})
        ),
    )
    with pytest.raises(EmbeddingError) as error:
        client.tokenize(["text"])
    assert error.value.code == "TOKENIZER_UNAVAILABLE"
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/embedding/test_tokenizer_service.py -q
```

Expected: FAIL because tokenizer support is missing.

- [ ] **Step 3: Add the embedding-service endpoint**

```python
# deploy/embedding_service.py
class TokenizeRequest(BaseModel):
    texts: List[str]


class TokenizeResponse(BaseModel):
    counts: List[int]
    model: str
    max_length: int


@app.post("/tokenize", response_model=TokenizeResponse)
def tokenize(body: TokenizeRequest):
    model = _get_embedder()
    tokenizer = model.tokenizer
    encoded = tokenizer(
        body.texts,
        add_special_tokens=True,
        truncation=False,
        padding=False,
    )
    counts = [len(ids) for ids in encoded["input_ids"]]
    return TokenizeResponse(
        counts=counts,
        model=MODEL_NAME,
        max_length=int(getattr(tokenizer, "model_max_length", 8192)),
    )
```

- [ ] **Step 4: Extend the client**

```python
# backend/app/rag/embedding/service.py
class EmbeddingError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class EmbeddingClient:
    def __init__(
        self,
        base_url: str,
        dimension: int = 1024,
        timeout: float = 30.0,
        transport=None,
        allow_hash_fallback: bool = True,
    ):
        self._base = base_url.rstrip("/")
        self._dimension = dimension
        self._timeout = timeout
        self._transport = transport
        self._allow_hash_fallback = allow_hash_fallback

    def tokenize(self, texts: List[str]) -> List[int]:
        if not texts:
            return []
        try:
            with httpx.Client(
                base_url=self._base,
                timeout=self._timeout,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = client.post("/tokenize", json={"texts": texts})
                response.raise_for_status()
                counts = response.json()["counts"]
                if len(counts) != len(texts) or any(
                    not isinstance(value, int) or value < 0 for value in counts
                ):
                    raise ValueError("invalid tokenizer response")
                return counts
        except Exception as error:
            raise EmbeddingError(
                503,
                "TOKENIZER_UNAVAILABLE",
                "The tokenizer service is unavailable.",
            ) from error
```

`embed` catches transport errors and uses `hash_embedding` only when
`allow_hash_fallback=True`. Otherwise it raises `EMBEDDING_UNAVAILABLE`.

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/embedding/test_tokenizer_service.py backend/tests/embedding/test_embedding_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add deploy/embedding_service.py backend/app/rag/embedding/service.py backend/tests/embedding/test_tokenizer_service.py
git commit -m "feat: add BGE-M3 tokenizer service"
```

---

### Task 7: Safe Sentence Boundaries and Semantic Chunking

**Files:**
- Create: `backend/app/rag/parsing/sentences.py`
- Create: `backend/app/rag/chunking/semantic.py`
- Create: `backend/tests/chunking/test_semantic_chunking.py`

**Interfaces:**
- Produces: `split_sentences(text) -> List[str]`.
- Produces: `ChunkBudget`, `SemanticChunker`, `ChunkingResult`.
- `SemanticChunker.__init__(tokenize: Callable[[List[str]], List[int]], budget: ChunkBudget)`.
- `SemanticChunker.chunk(nodes, metadata) -> ChunkingResult`.

- [ ] **Step 1: Write failing boundary tests**

```python
from backend.app.rag.parsing.sentences import split_sentences


def test_sentence_splitter_keeps_versions_urls_and_words():
    text = (
        "Spring Boot requires Java 17. "
        "See https://example.com/api/v1 for details. "
        "Use spring.threads.virtual.enabled=true."
    )
    assert split_sentences(text) == [
        "Spring Boot requires Java 17.",
        "See https://example.com/api/v1 for details.",
        "Use spring.threads.virtual.enabled=true.",
    ]


def test_sentence_splitter_never_returns_half_an_english_word():
    from backend.app.rag.chunking.semantic import _safe_character_split

    pieces = _safe_character_split(
        "supercalifragilisticexpialidocious",
        max_chars=10,
    )
    assert pieces == ["supercalifragilisticexpialidocious"]
```

- [ ] **Step 2: Write failing semantic chunk tests**

```python
from backend.app.rag.chunking.semantic import ChunkBudget, SemanticChunker
from backend.app.rag.parsing.contracts import DocumentNode, NodeType


def _node(text: str, order: int, heading=("Spring",)):
    return DocumentNode(
        node_id="node-{0}".format(order),
        node_type=NodeType.PARAGRAPH,
        text=text,
        heading_path=heading,
        page_no=1,
        bbox=None,
        reading_order=order,
        metadata={},
        source_locator={"page_no": 1},
    )


def test_semantic_chunker_builds_parent_and_children_without_word_splits():
    tokenize = lambda texts: [len(text.split()) for text in texts]
    chunker = SemanticChunker(
        tokenize=tokenize,
        budget=ChunkBudget(
            child_target=10,
            child_max=12,
            child_overlap=2,
            parent_target=30,
            parent_max=36,
        ),
    )
    result = chunker.chunk(
        [
            _node(
                "Spring Boot requires Java 17. "
                "It supports virtual threads.",
                1,
            ),
            _node(
                "Install the JDK before running the application.",
                2,
            ),
        ],
        document_version_id="dv-1",
        source_path="guide.md",
        tokenizer_model="BAAI/bge-m3",
    )

    assert result.parents
    assert result.children
    assert all(
        child.parent_chunk_id for child in result.children
    )
    assert all(
        "supercalifragilistic" not in child.content
        for child in result.children
    )
    assert all(
        child.token_count <= chunker.budget.child_max
        for child in result.children
    )
```

- [ ] **Step 3: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/chunking/test_semantic_chunking.py -q
```

Expected: collection fails because the modules are missing.

- [ ] **Step 4: Implement sentence splitting**

```python
# backend/app/rag/parsing/sentences.py
from __future__ import annotations

import re
from typing import List


_PROTECTED = re.compile(
    r"(https?://\S+|[\w.-]+@[\w.-]+|\b\d+(?:\.\d+){1,3}\b|"
    r"\b[A-Za-z_][A-Za-z0-9_.-]*=[^\s]+)"
)


def split_sentences(text: str) -> List[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    protected = {}

    def protect(match):
        key = "__PROTECTED_{0}__".format(len(protected))
        protected[key] = match.group(0)
        return key

    masked = _PROTECTED.sub(protect, normalized)
    parts = re.split(r"(?<=[。！？；.!?;])\s+", masked)
    sentences = []
    for part in parts:
        restored = part.strip()
        for key, value in protected.items():
            restored = restored.replace(key, value)
        if restored:
            sentences.append(restored)
    return sentences
```

- [ ] **Step 5: Implement semantic models and safe fallback**

```python
# backend/app/rag/chunking/semantic.py
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from backend.app.rag.parsing.contracts import DocumentNode, NodeType


_SAFE_WORD_RE = re.compile(r"[\w.-]+")


@dataclass(frozen=True)
class ChunkBudget:
    child_target: int = 480
    child_max: int = 512
    child_overlap: int = 64
    parent_target: int = 1200
    parent_max: int = 1400
    code_target: int = 120
    code_max: int = 160
    code_overlap: int = 16
    table_max: int = 512
    minimum_child: int = 64


@dataclass(frozen=True)
class ParentChunkDraft:
    parent_id: str
    content: str
    token_count: int
    heading_path: Tuple[str, ...]
    page_start: Optional[int]
    page_end: Optional[int]


@dataclass(frozen=True)
class ChildChunkDraft:
    child_id: str
    parent_chunk_id: str
    child_order: int
    content: str
    token_count: int
    parent_start_offset: int
    parent_end_offset: int
    overlap_before_tokens: int
    node_type: str
    page_no: Optional[int]
    unsafe_split: bool


@dataclass(frozen=True)
class ChunkingResult:
    parents: List[ParentChunkDraft]
    children: List[ChildChunkDraft]


def _word_tokens(text: str) -> List[str]:
    return _SAFE_WORD_RE.findall(text)


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return prefix + digest


def _safe_character_split(text: str, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    pieces = []
    current = ""
    for token in re.split(r"(\s+)", text):
        if not token:
            continue
        if len(current) + len(token) <= max_chars:
            current += token
            continue
        if current.strip():
            pieces.append(current.strip())
        current = token
    if current.strip():
        pieces.append(current.strip())
    return pieces or [text]


class SemanticChunker:
    def __init__(
        self,
        *,
        tokenize: Callable[[List[str]], List[int]],
        budget: ChunkBudget = ChunkBudget(),
    ) -> None:
        self.tokenize = tokenize
        self.budget = budget

    def chunk(
        self,
        nodes: Sequence[DocumentNode],
        *,
        document_version_id: str,
        source_path: str,
        tokenizer_model: str,
    ) -> ChunkingResult:
        parents: List[ParentChunkDraft] = []
        children: List[ChildChunkDraft] = []
        current_nodes: List[DocumentNode] = []
        current_text = ""

        def flush_parent() -> None:
            nonlocal current_nodes, current_text
            if not current_text.strip():
                current_nodes = []
                current_text = ""
                return
            parent_id = _stable_id(
                "par_",
                document_version_id,
                source_path,
                current_text,
            )
            token_count = self._count([current_text])[0]
            page_numbers = [
                node.page_no for node in current_nodes if node.page_no is not None
            ]
            parent = ParentChunkDraft(
                parent_id=parent_id,
                content=current_text.strip(),
                token_count=token_count,
                heading_path=current_nodes[0].heading_path,
                page_start=min(page_numbers) if page_numbers else None,
                page_end=max(page_numbers) if page_numbers else None,
            )
            parents.append(parent)
            self._build_children(parent, current_nodes, children)
            current_nodes = []
            current_text = ""

        for node in nodes:
            if node.node_type is NodeType.HEADING:
                if current_text and node.heading_path != current_nodes[0].heading_path:
                    flush_parent()
                current_nodes.append(node)
                current_text = node.text if not current_text else current_text + "\n\n" + node.text
                continue
            piece = node.text.strip()
            if not piece:
                continue
            candidate = piece if not current_text else current_text + "\n\n" + piece
            count = self._count([candidate])[0]
            if current_text and count > self.budget.parent_max:
                flush_parent()
            current_nodes.append(node)
            current_text = piece if not current_text else current_text + "\n\n" + piece
        flush_parent()
        return ChunkingResult(parents=parents, children=children)

    def _count(self, texts: List[str]) -> List[int]:
        counts = self.tokenize(texts)
        if len(counts) != len(texts):
            raise RuntimeError("TOKENIZER_RESPONSE_INVALID")
        return counts

    def _build_children(
        self,
        parent: ParentChunkDraft,
        nodes: Sequence[DocumentNode],
        output: List[ChildChunkDraft],
    ) -> None:
        units: List[str] = []
        for node in nodes:
            if node.node_type is NodeType.CODE:
                units.extend(self._split_code(node.text))
            elif node.node_type is NodeType.TABLE:
                units.extend(self._split_table(node.text))
            else:
                units.extend(
                    sentence
                    for sentence in self._split_text(node.text)
                    if sentence
                )
        self._pack_units(parent, units, output)

    def _split_text(self, text: str) -> List[str]:
        from backend.app.rag.parsing.sentences import split_sentences
        return split_sentences(text)

    def _split_code(self, text: str) -> List[str]:
        if self._count([text])[0] <= self.budget.code_max:
            return [text]
        lines = text.splitlines(keepends=True)
        return self._pack_by_tokens(
            lines,
            target=self.budget.code_target,
            maximum=self.budget.code_max,
        )

    def _split_table(self, text: str) -> List[str]:
        if self._count([text])[0] <= self.budget.table_max:
            return [text]
        lines = text.splitlines()
        if len(lines) <= 1:
            return [text]
        header = lines[0]
        rows = lines[1:]
        groups = []
        current = [header]
        for row in rows:
            candidate = "\n".join(current + [row])
            if self._count([candidate])[0] > self.budget.table_max and len(current) > 1:
                groups.append("\n".join(current))
                current = [header, row]
            else:
                current.append(row)
        if len(current) > 1:
            groups.append("\n".join(current))
        return groups

    def _pack_by_tokens(
        self,
        pieces: Sequence[str],
        *,
        target: int,
        maximum: int,
    ) -> List[str]:
        groups = []
        current = ""
        for piece in pieces:
            candidate = piece if not current else current + piece
            if current and self._count([candidate])[0] > maximum:
                groups.append(current)
                current = piece
            else:
                current = candidate
        if current:
            groups.append(current)
        return groups

    def _pack_units(
        self,
        parent: ParentChunkDraft,
        units: Sequence[str],
        output: List[ChildChunkDraft],
    ) -> None:
        children: List[str] = []
        current = ""
        for unit in units:
            candidate = unit if not current else current + " " + unit
            if current and self._count([candidate])[0] > self.budget.child_max:
                children.append(current.strip())
                current = unit
            else:
                current = candidate
        if current.strip():
            children.append(current.strip())
        search_offset = 0
        for order, content in enumerate(children, start=1):
            start = parent.content.find(content, search_offset)
            if start < 0:
                start = search_offset
            end = start + len(content)
            search_offset = max(start, end - 1)
            output.append(
                ChildChunkDraft(
                    child_id=_stable_id(
                        "chd_",
                        parent.parent_id,
                        str(order),
                        content,
                    ),
                    parent_chunk_id=parent.parent_id,
                    child_order=order,
                    content=content,
                    token_count=self._count([content])[0],
                    parent_start_offset=start,
                    parent_end_offset=end,
                    overlap_before_tokens=0,
                    node_type=NodeType.PARAGRAPH.value,
                    page_no=parent.page_start,
                    unsafe_split=False,
                )
            )
```

This first implementation preserves whole sentences and code lines. Task 9 adds overlap,
minimum merging, table/code node typing and unsafe-split marking.

- [ ] **Step 6: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/chunking/test_semantic_chunking.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/rag/parsing/sentences.py backend/app/rag/chunking/semantic.py backend/tests/chunking/test_semantic_chunking.py
git commit -m "feat: add token-aware semantic chunking"
```

---

### Task 8: Overlap, Minimum Merge and Unsafe Split Reporting

**Files:**
- Modify: `backend/app/rag/chunking/semantic.py`
- Modify: `backend/tests/chunking/test_semantic_chunking.py`

**Interfaces:**
- Extends: `ChildChunkDraft.overlap_before_tokens`, `unsafe_split`.
- Produces: deterministic overlap and small-child merge.

- [ ] **Step 1: Add failing overlap and no-word-cut tests**

```python
def test_semantic_chunker_applies_sentence_overlap():
    tokenize = lambda texts: [len(text.split()) for text in texts]
    chunker = SemanticChunker(
        tokenize=tokenize,
        budget=ChunkBudget(
            child_target=6,
            child_max=8,
            child_overlap=3,
            parent_target=30,
            parent_max=40,
        ),
    )
    result = chunker.chunk(
        [_node("One two three. Four five six. Seven eight nine.", 1)],
        document_version_id="dv-1",
        source_path="overlap.md",
        tokenizer_model="BAAI/bge-m3",
    )

    assert len(result.children) >= 2
    assert result.children[1].overlap_before_tokens > 0
    assert result.children[1].content.startswith("Four")


def test_semantic_chunker_marks_character_fallback():
    tokenize = lambda texts: [max(1, len(text) // 4) for text in texts]
    chunker = SemanticChunker(
        tokenize=tokenize,
        budget=ChunkBudget(child_target=8, child_max=10, child_overlap=0),
    )
    result = chunker.chunk(
        [_node("A" * 100, 1)],
        document_version_id="dv-1",
        source_path="fallback.md",
        tokenizer_model="BAAI/bge-m3",
    )

    assert any(child.unsafe_split for child in result.children)
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/chunking/test_semantic_chunking.py -q -k "overlap or character_fallback"
```

Expected: FAIL because overlap is always zero and unsafe fallback is not marked.

- [ ] **Step 3: Implement overlap selection**

```python
def _overlap_units(
    previous_units: Sequence[str],
    limit: int,
    count: Callable[[List[str]], List[int]],
) -> List[str]:
    selected = []
    for unit in reversed(previous_units):
        candidate = [unit] + selected
        if count([" ".join(candidate)])[0] > limit:
            break
        selected = candidate
    return selected
```

Update `_pack_units` to keep the previous unit list. When flushing a child, prepend
selected overlap units to the next child. Record:

```python
overlap_text = " ".join(overlap_units)
overlap_before_tokens = (
    self._count([overlap_text])[0] if overlap_text else 0
)
```

The next child content is:

```python
content = overlap_text + " " + next_content if overlap_text else next_content
```

Do not apply overlap across parent boundaries.

- [ ] **Step 4: Implement safe character fallback**

When a single sentence exceeds `child_max`, split at whitespace/punctuation:

```python
def _fallback_units(
    text: str,
    maximum: int,
    count: Callable[[List[str]], List[int]],
) -> Tuple[List[str], bool]:
    pieces = []
    current = ""
    unsafe = False
    for token in re.split(r"(\s+|[，。！？；,.!?;])", text):
        if not token:
            continue
        candidate = current + token
        if current and count([candidate])[0] > maximum:
            pieces.append(current.strip())
            current = token
        else:
            current = candidate
    if current.strip():
        pieces.append(current.strip())
    if any(len(piece) > maximum * 4 for piece in pieces):
        unsafe = True
    return pieces, unsafe
```

Never split an English word or identifier when any safe separator exists. Mark
`unsafe_split=True` only when the fallback still cuts a single long token.

- [ ] **Step 5: Merge small trailing child**

If a child has fewer than `minimum_child` tokens and its parent has a previous
child, merge when the result remains under `child_max`; otherwise keep it and add
`small_chunk=true` metadata for quality reporting.

- [ ] **Step 6: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/chunking/test_semantic_chunking.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/rag/chunking/semantic.py backend/tests/chunking/test_semantic_chunking.py
git commit -m "feat: add semantic chunk overlap and safe fallback"
```

---

### Task 9: Chunk Domain, Persistence and Parent-Child Relationships

**Files:**
- Modify: `backend/app/rag/domain/models.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/session.py`
- Modify: `backend/tests/db/test_session.py`

**Interfaces:**
- Extends `Chunk` and `ChunkRecord` with all Parent-Child, token and provenance fields.
- Produces: idempotent migrations for legacy databases.

- [ ] **Step 1: Write failing migration test**

```python
def test_create_schema_adds_parent_child_chunk_fields():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE chunks ("
                "id VARCHAR(68) PRIMARY KEY, "
                "document_id VARCHAR(26) NOT NULL, "
                "content TEXT NOT NULL"
                ")"
            )
        )

    create_schema(engine)
    create_schema(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("chunks")}
    assert {
        "parent_chunk_id",
        "chunk_level",
        "child_order",
        "node_type",
        "token_count",
        "page_no",
        "parse_version",
        "chunking_version",
        "embedding_model",
        "tokenizer_model",
        "parent_start_offset",
        "parent_end_offset",
        "overlap_before_tokens",
    }.issubset(columns)
    document_columns = {
        column["name"] for column in inspect(engine).get_columns("documents")
    }
    assert "mime_type" in document_columns
    version_columns = {
        column["name"]
        for column in inspect(engine).get_columns("document_versions")
    }
    assert {"parse_metadata", "chunking_metadata"}.issubset(version_columns)
    run_columns = {
        column["name"] for column in inspect(engine).get_columns("ingestion_runs")
    }
    assert {"quality_metrics", "failure_details"}.issubset(run_columns)
```

- [ ] **Step 2: Run test and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/db/test_session.py::test_create_schema_adds_parent_child_chunk_fields -q
```

Expected: FAIL because the new columns are missing.

- [ ] **Step 3: Extend the domain model**

```python
@dataclass(frozen=True)
class Chunk:
    # preserve all existing fields
    parent_chunk_id: Optional[str] = None
    chunk_level: str = "child"
    child_order: int = 1
    node_type: str = "paragraph"
    token_count: int = 0
    page_no: Optional[int] = None
    parse_version: str = ""
    chunking_version: str = ""
    embedding_model: str = ""
    tokenizer_model: str = ""
    parent_start_offset: int = 0
    parent_end_offset: int = 0
    overlap_before_tokens: int = 0
```

- [ ] **Step 4: Extend SQLAlchemy records**

`ChunkRecord`:

```python
parent_chunk_id: Mapped[Optional[str]] = mapped_column(String(70), nullable=True)
chunk_level: Mapped[str] = mapped_column(String(12), default="child")
child_order: Mapped[int] = mapped_column(Integer, default=1)
node_type: Mapped[str] = mapped_column(String(20), default="paragraph")
token_count: Mapped[int] = mapped_column(Integer, default=0)
page_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
parse_version: Mapped[str] = mapped_column(String(40), default="")
chunking_version: Mapped[str] = mapped_column(String(40), default="")
embedding_model: Mapped[str] = mapped_column(String(120), default="")
tokenizer_model: Mapped[str] = mapped_column(String(120), default="")
parent_start_offset: Mapped[int] = mapped_column(Integer, default=0)
parent_end_offset: Mapped[int] = mapped_column(Integer, default=0)
overlap_before_tokens: Mapped[int] = mapped_column(Integer, default=0)
```

`Document`:

```python
mime_type: Mapped[str] = mapped_column(String(120), default="")
```

`DocumentVersion`:

```python
parse_metadata: Mapped[str] = mapped_column(Text, default="{}")
chunking_metadata: Mapped[str] = mapped_column(Text, default="{}")
```

`IngestionRun`:

```python
quality_metrics: Mapped[str] = mapped_column(Text, default="{}")
failure_details: Mapped[str] = mapped_column(Text, default="{}")
```

- [ ] **Step 5: Add idempotent schema bridge**

```python
def _bridge_parent_child_chunks(engine: Engine) -> None:
    inspector = inspect(engine)
    additions = {
        "chunks": {
            "parent_chunk_id": "VARCHAR(70)",
            "chunk_level": "VARCHAR(12) NOT NULL DEFAULT 'child'",
            "child_order": "INTEGER NOT NULL DEFAULT 1",
            "node_type": "VARCHAR(20) NOT NULL DEFAULT 'paragraph'",
            "token_count": "INTEGER NOT NULL DEFAULT 0",
            "page_no": "INTEGER",
            "parse_version": "VARCHAR(40) NOT NULL DEFAULT ''",
            "chunking_version": "VARCHAR(40) NOT NULL DEFAULT ''",
            "embedding_model": "VARCHAR(120) NOT NULL DEFAULT ''",
            "tokenizer_model": "VARCHAR(120) NOT NULL DEFAULT ''",
            "parent_start_offset": "INTEGER NOT NULL DEFAULT 0",
            "parent_end_offset": "INTEGER NOT NULL DEFAULT 0",
            "overlap_before_tokens": "INTEGER NOT NULL DEFAULT 0",
        },
        "document_versions": {
            "parse_metadata": "TEXT NOT NULL DEFAULT '{}'",
            "chunking_metadata": "TEXT NOT NULL DEFAULT '{}'",
        },
        "ingestion_runs": {
            "quality_metrics": "TEXT NOT NULL DEFAULT '{}'",
            "failure_details": "TEXT NOT NULL DEFAULT '{}'",
        },
        "documents": {
            "mime_type": "VARCHAR(120) NOT NULL DEFAULT ''",
        },
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {
                column["name"]
                for column in inspector.get_columns(table)
            }
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(
                        text(
                            "ALTER TABLE {0} ADD COLUMN {1} {2}".format(
                                table, name, definition
                            )
                        )
                    )
```

Call `_bridge_parent_child_chunks(engine)` in `create_schema`.

- [ ] **Step 6: Run DB tests**

```bash
.venv/bin/python -m pytest backend/tests/db/test_session.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/rag/domain/models.py backend/app/db/models.py backend/app/db/session.py backend/tests/db/test_session.py
git commit -m "feat: persist parent-child chunk metadata"
```

---

### Task 10: Ingestion Pipeline Integration

**Files:**
- Modify: `backend/app/rag/ingestion/processor.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/v1/documents.py`
- Modify: `backend/tests/indexing/test_processor_documents.py`
- Modify: `backend/tests/indexing/test_processor_generation.py`

**Interfaces:**
- Consumes: `parse_document`, `SemanticChunker`, `EmbeddingClient.tokenize`.
- Produces: `assemble_chunk_rows(chunking, metadata) -> List[Chunk]`; parent and child
  `Chunk` rows; child-only embedding and indexing.

Upload must store the validated `UploadFile.content_type` in `Document.mime_type`;
source extensions and MIME types are checked before the document is queued.

- [ ] **Step 1: Write failing processor test**

```python
from backend.app.rag.chunking.semantic import (
    ChildChunkDraft,
    ChunkingResult,
    ParentChunkDraft,
)
from backend.app.rag.ingestion.processor import assemble_chunk_rows


def test_assemble_chunk_rows_links_children_to_parents():
    parent = ParentChunkDraft(
        parent_id="parent-1",
        content="Spring Boot requires Java 17.",
        token_count=6,
        heading_path=("Requirements",),
        page_start=1,
        page_end=1,
    )
    child = ChildChunkDraft(
        child_id="child-1",
        parent_chunk_id="parent-1",
        child_order=1,
        content="Spring Boot requires Java 17.",
        token_count=6,
        parent_start_offset=0,
        parent_end_offset=29,
        overlap_before_tokens=0,
        node_type="paragraph",
        page_no=1,
        unsafe_split=False,
    )

    rows = assemble_chunk_rows(
        ChunkingResult(parents=[parent], children=[child]),
        document_id="doc-1",
        document_version_id="dv-1",
        source_path="guide.md",
        team_id="team-1",
        knowledge_base_id="kb-1",
        owner_user_id="user-1",
        visibility="team_shared",
        data_classification="internal",
        product=None,
        version_values=(),
        parse_version="parse-1",
        chunking_version="chunk-1",
        tokenizer_model="BAAI/bge-m3",
    )

    assert [row.chunk_level for row in rows] == ["parent", "child"]
    assert rows[1].parent_chunk_id == rows[0].chunk_id
    assert rows[0].content_vector == []
```

- [ ] **Step 2: Run test and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/indexing/test_processor_documents.py -q -k parent_and_child
```

Expected: FAIL because the processor emits one flat chunk list.

Implement `assemble_chunk_rows` in `processor.py` before wiring the full ingestion
transaction:

```python
def assemble_chunk_rows(
    chunking,
    *,
    document_id,
    document_version_id,
    source_path,
    team_id,
    knowledge_base_id,
    owner_user_id,
    visibility,
    data_classification,
    product,
    version_values,
    parse_version,
    chunking_version,
    tokenizer_model,
):
    rows = []
    for parent in chunking.parents:
        rows.append(
            Chunk(
                # existing required fields
                chunk_id=parent.parent_id,
                document_id=document_id,
                document_version_id=document_version_id,
                team_id=team_id,
                knowledge_base_id=knowledge_base_id,
                owner_user_id=owner_user_id,
                visibility=Visibility(visibility),
                data_classification=DataClassification(data_classification),
                source_path=source_path,
                heading_path=parent.heading_path,
                content=parent.content,
                logical_chunk_key=parent.parent_id,
                content_hash=content_fingerprint(parent.content),
                source_locator={
                    "page_no": parent.page_start,
                    "heading_path": list(parent.heading_path),
                },
                product=product,
                version_values=tuple(version_values),
                parent_chunk_id=None,
                chunk_level="parent",
                child_order=0,
                node_type="parent",
                token_count=parent.token_count,
                page_no=parent.page_start,
                parse_version=parse_version,
                chunking_version=chunking_version,
                tokenizer_model=tokenizer_model,
            )
        )
    for child in chunking.children:
        rows.append(
            Chunk(
                chunk_id=child.child_id,
                document_id=document_id,
                document_version_id=document_version_id,
                team_id=team_id,
                knowledge_base_id=knowledge_base_id,
                owner_user_id=owner_user_id,
                visibility=Visibility(visibility),
                data_classification=DataClassification(data_classification),
                source_path=source_path,
                heading_path=next(
                    parent.heading_path
                    for parent in chunking.parents
                    if parent.parent_id == child.parent_chunk_id
                ),
                content=child.content,
                logical_chunk_key=child.child_id,
                content_hash=content_fingerprint(child.content),
                source_locator={"page_no": child.page_no},
                product=product,
                version_values=tuple(version_values),
                parent_chunk_id=child.parent_chunk_id,
                chunk_level="child",
                child_order=child.child_order,
                node_type=child.node_type,
                token_count=child.token_count,
                page_no=child.page_no,
                parse_version=parse_version,
                chunking_version=chunking_version,
                tokenizer_model=tokenizer_model,
                parent_start_offset=child.parent_start_offset,
                parent_end_offset=child.parent_end_offset,
                overlap_before_tokens=child.overlap_before_tokens,
            )
        )
    return rows
```

- [ ] **Step 3: Add parser/chunker settings**

```python
# backend/app/core/config.py
parse_version: str = "2026-10-21"
chunking_version: str = "2026-10-21"
chunk_child_target_tokens: int = 480
chunk_child_max_tokens: int = 512
chunk_child_overlap_tokens: int = 64
chunk_parent_target_tokens: int = 1200
chunk_parent_max_tokens: int = 1400
```

Read each from the corresponding `TECHVAULT_*` environment variable.

- [ ] **Step 4: Replace flat parsing/chunking**

```python
from backend.app.rag.parsing.router import parse_document
from backend.app.rag.chunking.semantic import ChunkBudget, SemanticChunker

parsed = parse_document(
    path,
    file_name=document.file_name,
    mime_type=document.mime_type or "",
)
tokenizer = EmbeddingClient(
    settings.embedding_url,
    allow_hash_fallback=False,
)
chunker = SemanticChunker(
    tokenize=tokenizer.tokenize,
    budget=ChunkBudget(
        child_target=settings.chunk_child_target_tokens,
        child_max=settings.chunk_child_max_tokens,
        child_overlap=settings.chunk_child_overlap_tokens,
        parent_target=settings.chunk_parent_target_tokens,
        parent_max=settings.chunk_parent_max_tokens,
    ),
)
chunking = chunker.chunk(
    parsed.nodes,
    document_version_id=document.current_version_id or document.id,
    source_path=document.file_name,
    tokenizer_model="BAAI/bge-m3",
)
```

Convert `ParentChunkDraft` into parent `Chunk` rows first. Convert
`ChildChunkDraft` into child rows and link each child to its parent. Populate all
permission, product, version and source-locator fields from `Document`.

- [ ] **Step 5: Persist chunk metadata**

Before processing, create or update `DocumentVersion.parse_metadata`:

```python
version.parse_metadata = json.dumps(
    {
        "parser_name": parsed.parser_name,
        "parser_version": parsed.parser_version,
        "pdf_kind": parsed.pdf_kind,
        "warnings": list(parsed.warnings),
        "quality": asdict(parsed.quality),
    },
    ensure_ascii=False,
)
version.chunking_metadata = json.dumps(
    {
        "chunking_version": settings.chunking_version,
        "tokenizer_model": "BAAI/bge-m3",
        "parent_count": len(chunking.parents),
        "child_count": len(chunking.children),
        "token_counts": [child.token_count for child in chunking.children],
    },
    ensure_ascii=False,
)
```

Persist parent and child rows in one transaction. Parent rows have
`chunk_level="parent"` and no vector. Child rows have `chunk_level="child"` and
`parent_chunk_id`.

- [ ] **Step 6: Preserve chunk override behavior**

Apply overrides to child logical keys only. Parent context is reconstructed during
retrieval from parent text plus active child overrides and parent offsets. If an
override range is invalid, mark the parent context invalid and fail generation
activation for the affected document version.

- [ ] **Step 7: Run processor tests**

```bash
.venv/bin/python -m pytest backend/tests/indexing/test_processor_documents.py backend/tests/indexing/test_processor_generation.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/rag/ingestion/processor.py backend/app/core/config.py backend/tests/indexing/test_processor_documents.py backend/tests/indexing/test_processor_generation.py
git commit -m "feat: run semantic parent-child ingestion"
```

---

### Task 11: Child-Only Embedding and Index Payloads

**Files:**
- Modify: `backend/app/rag/ingestion/processor.py`
- Modify: `backend/app/rag/indexing/elasticsearch.py`
- Modify: `backend/app/rag/indexing/qdrant.py`
- Modify: `backend/app/rag/retrieval/filters.py`
- Modify: `backend/tests/indexing/test_engine_writers.py`
- Modify: `backend/tests/retrieval/test_engine_filters.py`

**Interfaces:**
- Consumes: child and parent chunks from Task 10.
- Produces: child-only vectors and index writes; `chunk_level=child` filters.

- [ ] **Step 1: Write failing child-only index tests**

```python
def test_elasticsearch_payload_contains_parent_child_metadata():
    chunk = Chunk(
        chunk_id="child-1",
        document_id="doc-1",
        document_version_id="dv-1",
        team_id="team-1",
        knowledge_base_id="kb-1",
        owner_user_id="user-1",
        visibility=Visibility.TEAM_SHARED,
        data_classification=DataClassification.INTERNAL,
        source_path="guide.md",
        heading_path=("Requirements",),
        content="Java 17 is required.",
        logical_chunk_key="guide.md#requirements",
        content_hash="hash",
        parent_chunk_id="parent-1",
        chunk_level="child",
        child_order=1,
        node_type="paragraph",
        token_count=8,
        page_no=2,
    )
    payload = ElasticsearchIndexWriter("http://es")._document(chunk)
    assert payload["parent_chunk_id"] == "parent-1"
    assert payload["chunk_level"] == "child"
    assert payload["token_count"] == 8
    assert payload["page_no"] == 2


def test_retrieval_filters_require_child_chunks():
    filters = RetrievalFilters(
        team_id="team-1",
        knowledge_base_ids=("kb-1",),
        viewer_user_id="user-1",
    )
    assert "chunk_level" in str(elasticsearch_bool_query(filters))
    assert "chunk_level" in str(qdrant_filter(filters))
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/indexing/test_engine_writers.py backend/tests/retrieval/test_engine_filters.py -q -k "parent_child or child_chunks"
```

Expected: FAIL because the payload and filters are missing.

- [ ] **Step 3: Embed only children**

```python
indexable_chunks = [
    chunk
    for chunk in chunks
    if chunk.chunk_status is ChunkStatus.ENABLED
    and chunk.chunk_level == "child"
]
vectors = embedder.embed(
    [
        "Document: {0}\nSection: {1}\nContent: {2}".format(
            document.file_name,
            " / ".join(chunk.heading_path),
            chunk.content,
        )
        for chunk in indexable_chunks
    ]
)
```

Parent rows keep an empty `content_vector` and are excluded from
`staged_chunks`.

- [ ] **Step 4: Add payload fields and filters**

ES document payload:

```python
"parent_chunk_id": chunk.parent_chunk_id,
"chunk_level": chunk.chunk_level,
"child_order": chunk.child_order,
"node_type": chunk.node_type,
"token_count": chunk.token_count,
"page_no": chunk.page_no,
"parse_version": chunk.parse_version,
"chunking_version": chunk.chunking_version,
"embedding_model": chunk.embedding_model,
"tokenizer_model": chunk.tokenizer_model,
```

Qdrant payload uses the same keys.

ES filter:

```python
must.append({"term": {"chunk_level": "child"}})
```

Qdrant filter:

```python
must.append({"key": "chunk_level", "match": {"value": "child"}})
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest backend/tests/indexing/test_engine_writers.py backend/tests/retrieval/test_engine_filters.py backend/tests/indexing/test_processor_documents.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/rag/ingestion/processor.py backend/app/rag/indexing/elasticsearch.py backend/app/rag/indexing/qdrant.py backend/app/rag/retrieval/filters.py backend/tests/indexing/test_engine_writers.py backend/tests/retrieval/test_engine_filters.py
git commit -m "feat: index child chunks only"
```

---

### Task 12: Parent Context Hydration During Retrieval

**Files:**
- Create: `backend/app/rag/context/parents.py`
- Create: `backend/tests/api/test_parent_child_context.py`
- Modify: `backend/app/api/v1/chats.py`
- Modify: `backend/app/rag/retrieval/in_memory.py`

**Interfaces:**
- Produces: `hydrate_parent_chunks(session, chunks) -> List[RetrievedChunk]`.
- Returned chunks have parent content and parent chunk IDs; candidate Trace rows keep
  child IDs.

- [ ] **Step 1: Write failing parent hydration test**

```python
from backend.app.db.models import ChunkOverride, ChunkRecord, Document
from backend.app.rag.context.parents import hydrate_parent_chunks
from backend.app.rag.domain.models import RetrievedChunk


def test_parent_hydration_deduplicates_and_applies_child_overrides(api_app):
    with api_app.state.session_factory() as session:
        session.add(
            Document(
                id="doc-1",
                knowledge_base_id="kb-1",
                owner_user_id="user-1",
                file_name="guide.md",
            )
        )
        session.add(
            ChunkRecord(
                id="parent-1",
                document_id="doc-1",
                team_id="team-1",
                knowledge_base_id="kb-1",
                owner_user_id="user-1",
                content="Java 17. Install the JDK.",
                chunk_level="parent",
            )
        )
        session.add_all(
            [
                ChunkRecord(
                    id="child-1",
                    document_id="doc-1",
                    team_id="team-1",
                    knowledge_base_id="kb-1",
                    owner_user_id="user-1",
                    content="Java 17.",
                    parent_chunk_id="parent-1",
                    chunk_level="child",
                    child_order=1,
                    parent_start_offset=0,
                    parent_end_offset=8,
                    logical_chunk_key="child-1",
                ),
                ChunkRecord(
                    id="child-2",
                    document_id="doc-1",
                    team_id="team-1",
                    knowledge_base_id="kb-1",
                    owner_user_id="user-1",
                    content="Install the JDK.",
                    parent_chunk_id="parent-1",
                    chunk_level="child",
                    child_order=2,
                    parent_start_offset=9,
                    parent_end_offset=25,
                    logical_chunk_key="child-2",
                ),
                ChunkOverride(
                    team_id="team-1",
                    document_id="doc-1",
                    logical_chunk_key="child-1",
                    content="Java 21.",
                    status="active",
                    created_by="user-1",
                    updated_by="user-1",
                ),
            ]
        )
        session.commit()

        hydrated = hydrate_parent_chunks(
            session,
            [
                RetrievedChunk(
                    chunk_id="child-1",
                    parent_chunk_id="parent-1",
                    document_version_id="dv-1",
                    content="Java 17.",
                    fused_rank=1,
                ),
                RetrievedChunk(
                    chunk_id="child-2",
                    parent_chunk_id="parent-1",
                    document_version_id="dv-1",
                    content="Install the JDK.",
                    fused_rank=2,
                ),
            ],
        )

    assert len(hydrated) == 1
    assert hydrated[0].chunk_id == "parent-1"
    assert hydrated[0].content == "Java 21. Install the JDK."
```

- [ ] **Step 2: Run test and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/api/test_parent_child_context.py -q
```

Expected: FAIL because hydration does not exist.

- [ ] **Step 3: Implement hydration**

```python
# backend/app/rag/context/parents.py
from typing import Dict, List, Sequence
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import ChunkOverride, ChunkRecord
from backend.app.rag.domain.models import RetrievedChunk


def _effective_parent_content(
    session: Session,
    parent: ChunkRecord,
    children: Sequence[ChunkRecord],
) -> str:
    content = parent.content
    overrides = {
        row.logical_chunk_key: row
        for row in session.scalars(
            select(ChunkOverride).where(
                ChunkOverride.document_id == parent.document_id,
                ChunkOverride.status == "active",
                ChunkOverride.content.is_not(None),
            )
        ).all()
    }
    edits = []
    for child in children:
        override = overrides.get(child.logical_chunk_key)
        if override is None or not override.content.strip():
            continue
        if child.parent_start_offset > child.parent_end_offset:
            raise RuntimeError("PARENT_CHILD_INTEGRITY_FAILED")
        edits.append((child.parent_start_offset, child.parent_end_offset, override.content))
    for start, end, value in sorted(edits, reverse=True):
        if start < 0 or end > len(content) or start >= end:
            raise RuntimeError("PARENT_CHILD_INTEGRITY_FAILED")
        content = content[:start] + value + content[end:]
    return content


def hydrate_parent_chunks(
    session: Session,
    chunks: Sequence[RetrievedChunk],
) -> List[RetrievedChunk]:
    parent_ids = [
        chunk.parent_chunk_id
        for chunk in chunks
        if chunk.parent_chunk_id
    ]
    if not parent_ids:
        return list(chunks)
    parents = {
        row.id: row
        for row in session.scalars(
            select(ChunkRecord).where(ChunkRecord.id.in_(set(parent_ids)))
        ).all()
    }
    children_by_parent: Dict[str, List[ChunkRecord]] = {}
    for row in session.scalars(
        select(ChunkRecord).where(
            ChunkRecord.parent_chunk_id.in_(set(parent_ids))
        )
    ).all():
        children_by_parent.setdefault(row.parent_chunk_id, []).append(row)
    hydrated = []
    seen = set()
    for chunk in chunks:
        parent_id = chunk.parent_chunk_id
        if not parent_id or parent_id in seen:
            continue
        parent = parents.get(parent_id)
        if parent is None:
            raise RuntimeError("PARENT_CHILD_INTEGRITY_FAILED")
        content = _effective_parent_content(
            session,
            parent,
            sorted(
                children_by_parent.get(parent_id, []),
                key=lambda row: row.child_order,
            ),
        )
        hydrated.append(
            replace(
                chunk,
                chunk_id=parent.id,
                content=content,
                parent_chunk_id=None,
                fused_rank=len(hydrated) + 1,
            )
        )
        seen.add(parent_id)
    return hydrated
```

- [ ] **Step 4: Add parent linkage to retrieved chunks**

```python
@dataclass(frozen=True)
class RetrievedChunk:
    # preserve existing fields
    parent_chunk_id: Optional[str] = None
```

Populate it in ES/Qdrant adapters from payload.

- [ ] **Step 5: Hydrate before rerank and generation**

In both stream and non-stream chat paths:

```python
parent_context = hydrate_parent_chunks(
    session,
    list(result.rrf_candidates or result.chunks),
)
reranked = await asyncio.to_thread(
    gateway.rerank,
    rewrite.rewritten_query,
    parent_context,
    top_n=10,
    classification=classification,
)
context_chunks = reranked[:8]
```

The non-stream path uses the request `session`. The streaming path opens a short-lived
`session_factory()` context for hydration and closes it before rerank; never reuse
the request-scoped session inside `stream_events`.

Trace `bm25_candidates`, `dense_candidates` and `rrf_candidates` remain child rows.
`final_context` stores hydrated parent rows.

- [ ] **Step 6: Run API tests**

```bash
.venv/bin/python -m pytest backend/tests/api/test_parent_child_context.py backend/tests/api/test_chat_retrieval_generation.py backend/tests/retrieval/test_dual_engine.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/rag/context/parents.py backend/app/rag/domain/models.py backend/app/api/v1/chats.py backend/app/rag/retrieval/in_memory.py backend/tests/api/test_parent_child_context.py
git commit -m "feat: hydrate parent context for retrieval"
```

---

### Task 13: Quality Reports, Error Mapping, Documentation and End-to-End Verification

**Files:**
- Create: `backend/app/rag/chunking/quality.py`
- Create: `backend/tests/chunking/test_chunk_quality.py`
- Modify: `backend/app/rag/ingestion/processor.py`
- Modify: `backend/app/api/v1/documents.py`
- Modify: `backend/tests/e2e/test_provider_chat_flow.py`
- Modify: `docs/api/api-contract.md`
- Modify: `docs/product/page-map.md`
- Modify: `deploy/README.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: parsed nodes, chunking result and embedding result.
- Produces: quality report JSON on document version/run and stable error mapping.

- [ ] **Step 1: Write failing chunk quality tests**

```python
from backend.app.rag.chunking.quality import (
    chunk_quality_report,
    embedding_quality_report,
)


def test_chunk_quality_reports_unsafe_and_orphan_chunks():
    report = chunk_quality_report(
        child_token_counts=[5, 480, 600],
        parent_ids={"parent-1"},
        child_parent_ids=["parent-1", "parent-2", "parent-2"],
        unsafe_split_count=1,
    )

    assert report["passed"] is False
    assert "CHILD_TOKEN_LIMIT_EXCEEDED" in report["errors"]
    assert "MISSING_PARENT" in report["errors"]
    assert "UNSAFE_SPLIT" in report["warnings"]


def test_embedding_quality_rejects_dimension_and_fallback():
    report = embedding_quality_report(
        vectors=[[1.0, 0.0], [1.0]],
        expected_count=2,
        expected_dimension=1024,
        fallback_used=True,
    )

    assert report["passed"] is False
    assert "EMBEDDING_DIMENSION_MISMATCH" in report["errors"]
    assert "EMBEDDING_FALLBACK_FORBIDDEN" in report["errors"]
```

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/python -m pytest backend/tests/chunking/test_chunk_quality.py -q
```

Expected: FAIL because quality helpers are missing.

- [ ] **Step 3: Implement quality helpers**

```python
# backend/app/rag/chunking/quality.py
from typing import Dict, List, Sequence


def chunk_quality_report(
    *,
    child_token_counts: Sequence[int],
    parent_ids: set,
    child_parent_ids: Sequence[str],
    unsafe_split_count: int,
) -> Dict:
    errors = []
    warnings = []
    if any(count > 512 for count in child_token_counts):
        errors.append("CHILD_TOKEN_LIMIT_EXCEEDED")
    if any(parent_id not in parent_ids for parent_id in child_parent_ids):
        errors.append("MISSING_PARENT")
    if unsafe_split_count:
        warnings.append("UNSAFE_SPLIT")
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "total_chunks": len(child_token_counts),
        "min_tokens": min(child_token_counts) if child_token_counts else 0,
        "max_tokens": max(child_token_counts) if child_token_counts else 0,
        "average_tokens": (
            sum(child_token_counts) / len(child_token_counts)
            if child_token_counts
            else 0.0
        ),
    }


def embedding_quality_report(
    *,
    vectors: Sequence[Sequence[float]],
    expected_count: int,
    expected_dimension: int,
    fallback_used: bool,
) -> Dict:
    errors = []
    if len(vectors) != expected_count:
        errors.append("EMBEDDING_COUNT_MISMATCH")
    if any(len(vector) != expected_dimension for vector in vectors):
        errors.append("EMBEDDING_DIMENSION_MISMATCH")
    if fallback_used:
        errors.append("EMBEDDING_FALLBACK_FORBIDDEN")
    return {
        "passed": not errors,
        "errors": errors,
        "count": len(vectors),
        "dimension": expected_dimension,
    }
```

- [ ] **Step 4: Map quality and service failures**

In `process_document`, map:

```python
ERROR_MAP = {
    "PDF_SCANNED_UNSUPPORTED": (False, "PDF_SCANNED_UNSUPPORTED"),
    "PDF_MIXED_UNSUPPORTED": (False, "PDF_MIXED_UNSUPPORTED"),
    "PDF_LAYOUT_PARSE_FAILED": (True, "PDF_LAYOUT_PARSE_FAILED"),
    "TOKENIZER_UNAVAILABLE": (True, "TOKENIZER_UNAVAILABLE"),
    "EMBEDDING_UNAVAILABLE": (True, "EMBEDDING_UNAVAILABLE"),
    "CHUNK_QUALITY_FAILED": (False, "CHUNK_QUALITY_FAILED"),
    "PARENT_CHILD_INTEGRITY_FAILED": (False, "PARENT_CHILD_INTEGRITY_FAILED"),
}
```

Persist the selected error in `IngestionRun.error_code`, set `retryable`, and write
structured diagnostics to `failure_details`.

- [ ] **Step 5: Expose quality metrics**

`GET /docs/detail` includes:

```python
"parse_quality": json.loads(version.parse_metadata or "{}").get("quality", {}),
"chunk_quality": json.loads(run.quality_metrics or "{}"),
```

The document detail view displays parser version, PDF kind, child/parent counts,
maximum token count, unsafe split count and current error code.

- [ ] **Step 6: Add end-to-end fixtures**

Create representative fixtures inside tests rather than committing large binaries:

- Markdown with headings and fenced code
- DOCX with heading, paragraph, table and trailing paragraph
- native PDF with text blocks and a command
- scanned PDF classification fixture

The E2E test must assert:

- parent and child rows exist
- only children have vectors
- ES/Qdrant contain child payloads
- retrieval returns parent context
- Trace candidate rows contain child IDs
- final context contains parent IDs
- scanned PDF returns `PDF_SCANNED_UNSUPPORTED`

- [ ] **Step 7: Update documentation**

Document:

- Parser router and PDF kinds
- PyMuPDF dependency
- `/tokenize` endpoint
- Parent-Child lifecycle
- token budgets and overlap
- fail-closed embedding behavior
- error codes
- new generation rebuild requirement

- [ ] **Step 8: Run full regression**

```bash
.venv/bin/python -m pytest -q
cd frontend && npm test
cd frontend && npm run build
```

Expected: all tests and the frontend build pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/rag/chunking/quality.py backend/app/rag/ingestion/processor.py backend/app/api/v1/documents.py backend/tests/chunking/test_chunk_quality.py backend/tests/e2e/test_provider_chat_flow.py docs/api/api-contract.md docs/product/page-map.md deploy/README.md README.md
git commit -m "docs: complete semantic parsing pipeline"
```

---

## Self-Review

Spec coverage:

- Parser router and file/MIME validation: Tasks 2, 4, 10.
- PyMuPDF dependency and native PDF parsing: Tasks 1, 4, 5.
- Scanned/mixed classification and rejection: Task 4.
- Shared `DocumentNode` model: Task 1.
- Markdown/TXT parser, lists and tables: Task 2.
- Ordered DOCX paragraph/table parser: Task 3.
- PDF reading order, heading heuristics and table extraction: Task 5.
- Repeated header/footer removal: Task 5.
- BGE-M3 tokenizer endpoint and client: Task 6.
- Sentence-safe, token-budgeted semantic chunks: Tasks 7 and 8.
- Overlap, minimum merge and unsafe fallback: Task 8.
- Parent-Child persistence and offsets: Task 9.
- Ingestion pipeline and parse/chunk metadata: Task 10.
- Child-only embedding and index payloads: Task 11.
- Parent context hydration and override application: Task 12.
- Parser/chunk/embedding quality reports: Task 13.
- Fail-closed embedding behavior: Tasks 6, 10, 11, 13.
- New-generation rollout and rollback: Tasks 10, 11, 13.
- Documentation and end-to-end verification: Task 13.

Type consistency:

- `DocumentNode`, `ParsedDocument`, `ParseQuality` are defined in Task 1 and used by
  Tasks 2 through 8.
- `ParentChunkDraft`, `ChildChunkDraft`, `ChunkingResult`, `ChunkBudget` are defined
  in Task 7 and used by Tasks 8 and 10.
- `Chunk`/`ChunkRecord` fields defined in Task 9 are used consistently by Tasks 10
  through 13.
- Parent/child IDs use a four-character prefix plus a full SHA-256 digest, keeping
  every ID at 68 characters.

Placeholder scan:

- No `TBD`, `TODO`, `FIXME`, `assert True`, or “similar to another task” markers.







