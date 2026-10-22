import re

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from .contracts import DocumentNode, NodeType, parsed_document


def parse_docx(source):
    document = Document(source)
    nodes, headings = [], []
    for element in document.element.body.iterchildren():
        metadata = {}
        if isinstance(element, CT_P):
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = paragraph.style.name if paragraph.style else ""
            match = re.match(r"^(?:Heading|标题)\s*([1-6])$", style, re.I)
            level = int(match[1]) if match else 1 if style.lower() == "title" else 0
            runs = [run for run in paragraph.runs if run.text.strip()]
            if not level and len(text) < 120 and runs and all(
                run.bold and run.font.size and run.font.size.pt >= 14 for run in runs
            ):
                level = 2
            if level:
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, text))
            kind = NodeType.HEADING if level else NodeType.PARAGRAPH
            if not level and ("list" in style.lower() or paragraph._p.xpath("./w:pPr/w:numPr")):
                kind = NodeType.LIST
            metadata = {"style": style}
        elif isinstance(element, CT_Tbl):
            rows = [[cell.text.strip().replace("\n", " ").replace("|", "\\|") for cell in row.cells]
                    for row in Table(element, document).rows]
            rows = [row for row in rows if any(row)]
            if not rows:
                continue
            text = "\n".join("| " + " | ".join(row) + " |" for row in rows)
            kind = NodeType.TABLE
            metadata = {"rows": rows, "header": rows[0]}
        else:
            continue
        nodes.append(DocumentNode(
            "node-{0}".format(len(nodes)), kind, text,
            tuple(title for _, title in headings), reading_order=len(nodes), metadata=metadata,
        ))
    return parsed_document(nodes, "docx")
