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
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})

# File signatures ("magic bytes"). The content must match the extension.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF",),
    ".docx": (b"PK\x03\x04",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}
_EXECUTABLE_MAGIC = (b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa")
_KIND_NAMES = {
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".png": "PNG image",
    ".jpg": "JPEG image",
}
VALID_STATUSES = ("effective", "superseded", "draft")
_DOC_ID_RE = re.compile(r"[A-Za-z]{2,6}(?:-[A-Za-z0-9]+)+")

_META_RE = re.compile(
    r"^\s*(doc-id|title|category|version|status|effective|owner)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+[A-Z][^.!?]{2,80}$")
_MIN_TEXT_CHARS = 20


@dataclass
class TextUnit:
    """A contiguous piece of text with its location in the source.

    content_type: text | table | chart | ocr | image
    source_method: text_layer | vision_ocr | docx | plain
    """

    text: str
    page: int | None = None
    section: str | None = None
    content_type: str = "text"
    source_method: str = "plain"
    asset_id: str | None = None
    bbox: list[float] | None = None


@dataclass
class Asset:
    """An image kept so the UI can show the original (page render, chart)."""

    asset_id: str
    kind: str  # page | image | chart
    page: int | None
    png: bytes
    width: int
    height: int


@dataclass
class ParsedDocument:
    """Validated, extracted document ready for chunking."""

    filename: str
    mime_type: str
    size_bytes: int
    metadata: dict[str, str] = field(default_factory=dict)
    units: list[TextUnit] = field(default_factory=list)
    pages: int | None = None
    assets: list[Asset] = field(default_factory=list)
    vision_input_tokens: int = 0
    vision_output_tokens: int = 0
    vision_calls: int = 0
    skipped_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


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
        raise ValidationError(file_too_large_message(len(content), max_bytes))
    if content.startswith(_EXECUTABLE_MAGIC):
        raise ValidationError(
            f"File has a {ext} extension but is an executable program. "
            "Renamed executables are rejected."
        )
    signatures = _MAGIC.get(ext)
    if signatures and not content.startswith(signatures):
        kind = _KIND_NAMES.get(ext, ext)
        raise ValidationError(
            f"File has a {ext} extension but is not a valid {kind} "
            "(content does not match the file type, or it is corrupted)."
        )
    if ext in (".txt", ".md") and b"\x00" in content:
        raise ValidationError("Text file contains binary data (corrupted?).")
    return ALLOWED_EXTENSIONS[ext]


def file_too_large_message(size: int, max_bytes: int) -> str:
    return (
        f"File is too large ({size / 1_048_576:.1f} MB). "
        f"Limit is {max_bytes / 1_048_576:.0f} MB."
    )


def normalize_metadata(overrides: dict[str, str | None] | None) -> dict[str, str]:
    """Validate metadata supplied with an upload (form fields)."""
    clean: dict[str, str] = {}
    for key, value in (overrides or {}).items():
        if value is None or not str(value).strip():
            continue
        value = str(value).strip()[:100]
        if key == "status":
            value = value.lower()
            if value not in VALID_STATUSES:
                raise ValidationError(
                    f"Status must be one of: {', '.join(VALID_STATUSES)}."
                )
        if key == "effective" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValidationError("Effective date must look like YYYY-MM-DD.")
        clean[key] = value
    return clean


def doc_id_from_filename(filename: str) -> str:
    """'TRV-POL-003_Travel.pdf' -> 'TRV-POL-003'; 'remote_work.txt' -> 'REMOTE-WORK'."""
    stem = Path(filename).stem
    first = stem.split("_")[0]
    if _DOC_ID_RE.fullmatch(first):
        return first.upper()
    return re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-").upper()[:60] or "DOC"


# ── Extraction ───────────────────────────────────────────────


def parse_document(
    filename: str,
    content: bytes,
    max_bytes: int,
    overrides: dict[str, str | None] | None = None,
) -> ParsedDocument:
    """Validate and extract a document into located text units.

    ``overrides`` (category, version, status, effective) come from the upload
    form and win over the file's own header; the filename is the last fallback.
    """
    mime = validate_upload(filename, content, max_bytes)
    ext = Path(filename).suffix.lower()
    form_meta = normalize_metadata(overrides)
    if ext in IMAGE_EXTENSIONS:
        raise ValidationError(
            "Images need vision OCR, which is not available in this build."
        )

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
    metadata.update(form_meta)
    if "status" in metadata:
        metadata["status"] = metadata["status"].lower()
    metadata.setdefault("doc-id", doc_id_from_filename(filename))
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
