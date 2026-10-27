"""Document intake (FR-01) and content preparation (FR-02).

Validates file type, size and integrity, then extracts text into
page/section-aware units with document metadata (Doc-ID, title,
category, version, status, effective date).

Synthetic demo documents declare metadata in a header block::

    Doc-ID: HR-POL-007
    Title: Data Retention Policy
    Category: HR
    Version: 2.0
    Status: effective
    Effective: 2025-01-01
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.core.exceptions import ValidationError

ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

_META_RE = re.compile(
    r"^\s*(doc-id|title|category|version|status|effective|owner)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+[A-Z][^.!?]{2,80}$")
_MIN_TEXT_CHARS = 20


@dataclass
class TextUnit:
    """A contiguous piece of text with its location in the source."""

    text: str
    page: int | None = None
    section: str | None = None


@dataclass
class ParsedDocument:
    """Validated, extracted document ready for chunking."""

    filename: str
    mime_type: str
    size_bytes: int
    metadata: dict[str, str] = field(default_factory=dict)
    units: list[TextUnit] = field(default_factory=list)
    pages: int | None = None


# ── Validation ───────────────────────────────────────────────


def validate_upload(filename: str, content: bytes, max_bytes: int) -> str:
    """Validate an upload and return its canonical MIME type.

    Raises:
        ValidationError: unsupported type, empty, too large or corrupted.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{ext or 'none'}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )
    if not content:
        raise ValidationError("File is empty.")
    if len(content) > max_bytes:
        raise ValidationError(
            f"File is too large ({len(content) / 1_048_576:.1f} MB). "
            f"Limit is {max_bytes / 1_048_576:.0f} MB."
        )
    if ext == ".pdf" and not content.startswith(b"%PDF"):
        raise ValidationError("File has a .pdf extension but is not a valid PDF.")
    if ext == ".docx" and not content.startswith(b"PK"):
        raise ValidationError("File has a .docx extension but is not a valid DOCX.")
    if ext in (".txt", ".md") and b"\x00" in content:
        raise ValidationError("Text file contains binary data (corrupted?).")
    return ALLOWED_EXTENSIONS[ext]


# ── Extraction ───────────────────────────────────────────────


def parse_document(filename: str, content: bytes, max_bytes: int) -> ParsedDocument:
    """Validate and extract a document into located text units."""
    mime = validate_upload(filename, content, max_bytes)
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        units, pages = _extract_pdf(content)
    elif ext == ".docx":
        units, pages = _extract_docx(content), None
    else:
        units, pages = _extract_text(_decode_text(content), markdown=ext == ".md"), None

    metadata, units = _pull_metadata(units)
    units = [u for u in units if u.text.strip()]

    total_chars = sum(len(u.text.strip()) for u in units)
    if total_chars < _MIN_TEXT_CHARS:
        if ext == ".pdf":
            raise ValidationError(
                "PDF contains no extractable text. Scanned or handwritten documents "
                "require OCR, which is not enabled in this demo build."
            )
        raise ValidationError("Document contains no meaningful text.")

    stem = Path(filename).stem
    metadata.setdefault("doc-id", stem.split("_")[0].upper())
    metadata.setdefault("title", stem.replace("_", " "))
    return ParsedDocument(
        filename=filename,
        mime_type=mime,
        size_bytes=len(content),
        metadata=metadata,
        units=units,
        pages=pages,
    )


def _decode_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _heading_of(line: str, markdown: bool) -> str | None:
    """Return the heading text if the line looks like a section heading."""
    stripped = line.strip()
    if not stripped:
        return None
    if markdown and stripped.startswith("#"):
        return stripped.lstrip("#").strip() or None
    if _NUMBERED_HEADING_RE.match(stripped):
        return stripped
    if (
        stripped.isupper()
        and 3 <= len(stripped) <= 60
        and any(c.isalpha() for c in stripped)
        and not _META_RE.match(stripped)
    ):
        return stripped.title()
    return None


def _split_sections(
    text: str, page: int | None, current: str | None, markdown: bool
) -> tuple[list[TextUnit], str | None]:
    """Split text at heading lines, carrying the active section forward."""
    units: list[TextUnit] = []
    buf: list[str] = []
    for line in text.splitlines():
        heading = _heading_of(line, markdown)
        if heading:
            if "".join(buf).strip():
                units.append(TextUnit("\n".join(buf).strip(), page, current))
            buf = []
            current = heading
        else:
            buf.append(line)
    if "".join(buf).strip():
        units.append(TextUnit("\n".join(buf).strip(), page, current))
    return units, current


def _extract_text(text: str, markdown: bool) -> list[TextUnit]:
    units, _ = _split_sections(text, None, None, markdown)
    return units


def _extract_pdf(content: bytes) -> tuple[list[TextUnit], int]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        page_texts = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise ValidationError(f"PDF could not be parsed (corrupted?): {exc}") from exc

    units: list[TextUnit] = []
    section: str | None = None
    for page_no, text in enumerate(page_texts, start=1):
        page_units, section = _split_sections(text, page_no, section, markdown=False)
        units.extend(page_units)
    return units, len(page_texts)


def _extract_docx(content: bytes) -> list[TextUnit]:
    try:
        import docx

        document = docx.Document(io.BytesIO(content))
    except Exception as exc:
        raise ValidationError(f"DOCX could not be parsed (corrupted?): {exc}") from exc

    units: list[TextUnit] = []
    section: str | None = None
    buf: list[str] = []
    for para in document.paragraphs:
        style = (para.style.name if para.style is not None else "") or ""
        text = para.text.strip()
        if not text:
            continue
        if style.lower().startswith(("heading", "title")):
            if buf:
                units.append(TextUnit("\n".join(buf), None, section))
            buf = []
            section = text
        else:
            buf.append(text)
    # Tables are flattened row by row so their facts stay searchable.
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                buf.append(" | ".join(cells))
    if buf:
        units.append(TextUnit("\n".join(buf), None, section))
    return units


def _pull_metadata(units: list[TextUnit]) -> tuple[dict[str, str], list[TextUnit]]:
    """Extract ``Key: value`` metadata lines from the start of the document."""
    metadata: dict[str, str] = {}
    cleaned: list[TextUnit] = []
    for idx, unit in enumerate(units):
        if idx > 1:
            cleaned.append(unit)
            continue
        kept: list[str] = []
        for line in unit.text.splitlines():
            match = _META_RE.match(line)
            if match and match.group(1).lower() not in metadata:
                metadata[match.group(1).lower()] = match.group(2)
            else:
                kept.append(line)
        cleaned.append(TextUnit("\n".join(kept).strip(), unit.page, unit.section))
    if "status" in metadata:
        metadata["status"] = metadata["status"].lower()
    return metadata, cleaned
