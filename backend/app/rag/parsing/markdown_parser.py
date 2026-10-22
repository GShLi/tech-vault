import re
from pathlib import Path

from .contracts import DocumentNode, NodeType, parsed_document
from backend.app.rag.chunking.identity import normalize_content


def parse_markdown(source: Path, *, plain_text=False):
    nodes = []
    headings = []
    buffer = []
    kind = NodeType.PARAGRAPH
    fence = None

    def flush():
        nonlocal buffer
        text = "\n".join(buffer).strip("\n")
        if text.strip():
            nodes.append(DocumentNode(
                "node-{0}".format(len(nodes)), kind, text,
                tuple(title for _, title in headings),
                reading_order=len(nodes),
            ))
        buffer = []

    for line in normalize_content(source.read_text(encoding="utf-8-sig")).split("\n"):
        if plain_text:
            if not line.strip():
                flush()
            else:
                buffer.append(line)
            continue
        if fence:
            buffer.append(line)
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + r"{" + str(fence[1]) + r",}\s*", line):
                flush()
                fence = None
                kind = NodeType.PARAGRAPH
            continue
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if match:
            flush()
            kind = NodeType.CODE
            fence = (match[1][0], len(match[1]))
            buffer.append(line)
            continue
        match = re.match(r"^ {0,3}(#{1,6})(?:\s+(.+?)\s*#*\s*|\s*)$", line)
        if match:
            flush()
            level, title = len(match[1]), (match[2] or "").strip()
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
            nodes.append(DocumentNode(
                "node-{0}".format(len(nodes)), NodeType.HEADING, title,
                tuple(value for _, value in headings), reading_order=len(nodes),
            ))
            kind = NodeType.PARAGRAPH
            continue
        if not line.strip():
            flush()
            kind = NodeType.PARAGRAPH
            continue
        next_kind = (
            NodeType.TABLE if line.strip().startswith("|") and line.count("|") >= 2
            else NodeType.LIST if re.match(r"^\s*(?:[-*+] |\d+[.)] )", line)
            else NodeType.PARAGRAPH
        )
        if next_kind != kind:
            flush()
        kind = next_kind
        buffer.append(line)
    flush()
    return parsed_document(nodes, "text" if plain_text else "markdown")
