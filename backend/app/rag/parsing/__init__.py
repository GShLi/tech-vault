"""Document parsing adapters for PDF, Markdown, DOCX and GitHub snapshots."""

from .documents import UnsupportedDocumentType, parse_document_text

__all__ = ["UnsupportedDocumentType", "parse_document_text"]

