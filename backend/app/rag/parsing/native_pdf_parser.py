"""Conservative native PDF parsing; unsupported visual content stays explicit."""
import re
import statistics
from collections import Counter
from dataclasses import replace

import pymupdf

from .contracts import DocumentNode, NodeType, ParseError, parsed_document


def parse_pdf(source, *, max_pages=1000):
    nodes, headings, page_kinds, warnings = [], [], [], []
    with pymupdf.open(source) as document:
        if document.needs_pass:
            raise ParseError("PDF_LAYOUT_PARSE_FAILED", "Encrypted PDF requires a password.")
        if len(document) > max_pages:
            raise ParseError("DOCUMENT_LIMIT_EXCEEDED", "PDF page limit exceeded.")
        margins = Counter()
        pages = []
        for page in document:
            data = page.get_text("dict")
            blocks = data.get("blocks", [])
            text = page.get_text("text")
            image_area = sum(
                max(0, (block["bbox"][2] - block["bbox"][0]) * (block["bbox"][3] - block["bbox"][1]))
                for block in blocks if block.get("type") == 1
            )
            ratio = min(1, image_area / max(1, (page.rect.width * page.rect.height)))
            chars = len(re.sub(r"\s", "", text))
            page_kinds.append("scanned" if chars < 50 and ratio >= .3 else "mixed" if ratio >= .3 else "native")
            seen = set()
            for block in blocks:
                if block.get("type") != 0:
                    continue
                body = " ".join(span["text"] for line in block["lines"] for span in line["spans"]).strip()
                box = block["bbox"]
                if len(body) < 120 and (box[3] <= page.rect.height * .08 or box[1] >= page.rect.height * .92):
                    seen.add(re.sub(r"\d+", "#", body))
            margins.update(seen)
            pages.append(blocks)
        kind = "scanned" if page_kinds and page_kinds.count("scanned") > len(page_kinds) / 2 else "mixed" if any(k != "native" for k in page_kinds) else "native"
        if kind != "native":
            raise ParseError("PDF_{0}_UNSUPPORTED".format(kind.upper()), details={"pdf_kind": kind, "page_kinds": page_kinds})
        repeated = {key for key, count in margins.items() if count >= max(2, len(document) * .3)}
        for page_no, (page, blocks) in enumerate(zip(document, pages), 1):
            page_nodes, table_boxes = [], []
            try:
                tables = page.find_tables().tables
            except Exception:
                tables = []
                warnings.append("table_detection_unavailable:page-{0}".format(page_no))
            for table in tables:
                rows = table.extract()
                if not rows:
                    continue
                box = tuple(table.bbox)
                table_boxes.append(pymupdf.Rect(box))
                text = "\n".join("| " + " | ".join(str(cell or "").replace("\n", " ") for cell in row) + " |" for row in rows)
                page_nodes.append(DocumentNode("", NodeType.TABLE, text, page_no=page_no, bbox=box, metadata={"rows": rows, "header": rows[0]}))
            sizes = [span["size"] for block in blocks if block.get("type") == 0 for line in block["lines"] for span in line["spans"] if span["text"].strip()]
            median = statistics.median(sizes or [11])
            for block in blocks:
                if block.get("type") != 0:
                    continue
                box = tuple(block["bbox"])
                spans = [span for line in block["lines"] for span in line["spans"]]
                text = "\n".join("".join(span["text"] for span in line["spans"]) for line in block["lines"]).strip()
                if not text or any(table.contains(pymupdf.Rect(box)) for table in table_boxes):
                    continue
                margin = box[3] <= page.rect.height * .08 or box[1] >= page.rect.height * .92
                if margin and re.sub(r"\d+", "#", " ".join(text.split())) in repeated:
                    continue
                size = max((span["size"] for span in spans), default=median)
                heading = len(text) <= 120 and (size >= median + 1.5 or all(span.get("flags", 0) & 16 for span in spans))
                page_nodes.append(DocumentNode("", NodeType.HEADING if heading else NodeType.PARAGRAPH, text,
                    page_no=page_no, bbox=box, metadata={"level": 1 if size >= median + 4 else 2,
                    "table_parse_degraded": not tables and bool(warnings) and page_no == int(warnings[-1].split("-")[-1])}))
            # Cluster only non-spanning blocks; full-width blocks separate column bands.
            spanning = sorted([node for node in page_nodes if node.bbox[2] - node.bbox[0] > page.rect.width * .65], key=lambda node: node.bbox[1])
            remaining = [node for node in page_nodes if node not in spanning]
            ordered = []
            for boundary in spanning + [None]:
                band = [node for node in remaining if boundary is None or node.bbox[1] < boundary.bbox[1]]
                columns = []
                for node in sorted(band, key=lambda node: node.bbox[0]):
                    if not columns or node.bbox[0] - columns[-1][0].bbox[0] > page.rect.width * .15:
                        columns.append([])
                    columns[-1].append(node)
                for column in columns:
                    ordered.extend(sorted(column, key=lambda node: (node.bbox[1], node.bbox[0])))
                remaining = [node for node in remaining if node not in band]
                if boundary:
                    ordered.append(boundary)
            for node in ordered:
                if node.node_type == NodeType.HEADING:
                    level = node.metadata["level"]
                    while headings and headings[-1][0] >= level:
                        headings.pop()
                    headings.append((level, node.text))
                nodes.append(replace(node, node_id="node-{0}".format(len(nodes)), reading_order=len(nodes),
                    heading_path=tuple(title for _, title in headings), source_locator={"page_no": page_no, "bbox": list(node.bbox)}))
            nodes.append(DocumentNode("page-{0}".format(page_no), NodeType.PAGE_BREAK, "", page_no=page_no))
    return parsed_document(nodes, "pymupdf-native", pdf_kind="native", warnings=warnings, metadata={"page_kinds": page_kinds})
