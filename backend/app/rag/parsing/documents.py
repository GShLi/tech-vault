"""Text export of structured documents for existing tooling."""
from .contracts import NodeType, ParseError
from .router import parse_document

UnsupportedDocumentType = ParseError


def parse_document_text(path):
    parsed = parse_document(path)
    blocks = []
    current_page = None
    for node in parsed.nodes:
        if node.page_no is not None and node.page_no != current_page:
            blocks.append(f"# Page {node.page_no}")
            current_page = node.page_no
        if not node.text:
            continue
        if node.node_type == NodeType.HEADING:
            level = max(1, min(6, int(node.metadata.get("level", 1))))
            blocks.append(f"{'#' * level} {node.text}")
        else:
            blocks.append(node.text)
    return "\n\n".join(blocks)
