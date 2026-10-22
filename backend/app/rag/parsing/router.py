from pathlib import Path

from .contracts import ParseError
from .markdown_parser import parse_markdown
from .docx_parser import parse_docx


MIME_TYPES = {
    ".md": {"text/markdown", "text/plain", "text/x-markdown"},
    ".txt": {"text/plain"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
}


def validate_document_type(file_name, mime_type=""):
    suffix = Path(file_name).suffix.lower()
    if suffix not in MIME_TYPES:
        raise ParseError("UNSUPPORTED_FILE_TYPE")
    mime = mime_type.split(";", 1)[0].strip().lower()
    if mime and mime != "application/octet-stream" and mime not in MIME_TYPES[suffix]:
        raise ParseError("DOCUMENT_TYPE_MISMATCH")
    return mime if mime and mime != "application/octet-stream" else sorted(MIME_TYPES[suffix])[0]


def parse_document(source, *, file_name=None, mime_type="", max_pages=1000):
    source = Path(source)
    file_name = file_name or source.name
    validate_document_type(file_name, mime_type)
    suffix = Path(file_name).suffix.lower()
    try:
        if suffix in {".md", ".txt"}:
            return parse_markdown(source, plain_text=suffix == ".txt")
        if suffix == ".docx":
            return parse_docx(source)
        from .native_pdf_parser import parse_pdf
        return parse_pdf(source, max_pages=max_pages)
    except ParseError:
        raise
    except Exception as error:
        raise ParseError("DOCUMENT_PARSE_FAILED", "The document could not be parsed.") from error
