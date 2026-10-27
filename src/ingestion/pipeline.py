"""Ingestion pipeline: text extraction, chunking, and embedding.

This module is intentionally decoupled from SQLAlchemy so it can
run in the worker process without importing the full web stack.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Protocol

from src.core.exceptions import ValidationError
from src.core.logging import get_logger

logger = get_logger(__name__)

# ── Data Structures ──────────────────────────────────────────


@dataclass(frozen=True)
class ChunkData:
    """A processed chunk ready for database insertion."""

    content: str
    embedding: list[float]
    chunk_index: int
    page_number: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


# ── Protocols ────────────────────────────────────────────────


class Embedder(Protocol):
    """Interface for embedding models (dependency injection)."""

    def encode(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...


# ── Text Extraction ──────────────────────────────────────────

_SUPPORTED_TEXT_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
    }
)


def extract_text(content: bytes, mime_type: str | None) -> str:
    """Extract plain text from file content based on MIME type.

    Supports text files natively and PDF via pypdf (optional).

    Raises:
        ValidationError: If the file type is unsupported.
    """
    mime = (mime_type or "").lower().split(";")[0].strip()

    if mime in _SUPPORTED_TEXT_TYPES or mime == "":
        return content.decode("utf-8", errors="replace")

    if mime == "application/pdf":
        return _extract_pdf_text(content)

    raise ValidationError(
        f"Unsupported file type: '{mime}'. "
        "Supported: text/plain, text/markdown, application/pdf."
    )


def _extract_pdf_text(content: bytes) -> str:
    """Extract text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValidationError(
            "PDF support requires pypdf. Install with: pip install pypdf"
        ) from exc

    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)

    if not pages:
        raise ValidationError("PDF contains no extractable text.")

    return "\n\n".join(pages)


# ── Text Chunking ────────────────────────────────────────────


class RecursiveTextChunker:
    """Split text into overlapping chunks using hierarchical separators.

    Tries to split on paragraph boundaries first, then sentences,
    then words, then characters. This preserves semantic coherence
    at each level.
    """

    _SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

    def __init__(self, chunk_size: int = 2048, chunk_overlap: int = 256) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size.")
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk(self, text: str) -> list[str]:
        """Split text into chunks."""
        text = text.strip()
        if not text:
            return []

        chunks = self._split(text, self._SEPARATORS)
        return [c for c in chunks if c.strip()]

    def _split(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text using the first effective separator."""
        if len(text) <= self._chunk_size:
            return [text]

        sep = separators[0] if separators else ""
        remaining_seps = separators[1:] if separators else []

        if sep == "":
            # Last resort: hard split by character
            return self._hard_split(text)

        parts = text.split(sep)
        chunks: list[str] = []
        current = ""

        for part in parts:
            candidate = f"{current}{sep}{part}" if current else part

            if len(candidate) <= self._chunk_size:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                # If the part itself is too large, recurse with finer seps
                if len(part) > self._chunk_size and remaining_seps:
                    chunks.extend(self._split(part, remaining_seps))
                else:
                    current = part

        if current:
            chunks.append(current)

        # Apply overlap
        return self._apply_overlap(chunks)

    def _hard_split(self, text: str) -> list[str]:
        """Split by fixed character count as a last resort."""
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + self._chunk_size
            chunks.append(text[start:end])
            start = end - self._chunk_overlap
        return chunks

    def _apply_overlap(self, chunks: list[str]) -> list[str]:
        """Add trailing overlap from the next chunk's beginning."""
        if len(chunks) <= 1 or self._chunk_overlap == 0:
            return chunks

        result: list[str] = []
        for i, chunk in enumerate(chunks):
            if i < len(chunks) - 1:
                next_chunk = chunks[i + 1]
                overlap_text = next_chunk[: self._chunk_overlap]
                result.append(chunk + overlap_text)
            else:
                result.append(chunk)
        return result


class SemanticTextChunker:
    """Split text into chunks based on semantic shifts.

    Uses a local embedding model to compute similarity between
    adjacent sentence windows, and splits where similarity drops.
    """

    def __init__(
        self,
        embedder: Embedder,
        threshold_percentile: float = 60.0,
        max_chunk_size: int = 2048,
        buffer_size: int = 1,
    ) -> None:
        self._embedder = embedder
        self._threshold_percentile = threshold_percentile
        self._max_chunk_size = max_chunk_size
        self._buffer_size = buffer_size

    def chunk(self, text: str) -> list[str]:
        """Split text into semantically cohesive chunks."""
        import re

        text = text.strip()
        if not text:
            return []

        # Split into sentences
        sentence_endings = re.compile(r"(?<=[.!?])\s+")
        sentences = [s.strip() for s in sentence_endings.split(text) if s.strip()]

        if len(sentences) <= 1:
            return sentences

        # Build overlapping window texts to smooth out context
        windows = []
        for i in range(len(sentences)):
            start = max(0, i - self._buffer_size)
            end = min(len(sentences), i + self._buffer_size + 1)
            window_text = " ".join(sentences[start:end])
            windows.append(window_text)

        # Batch encode windows to get embeddings
        embeddings = self._embedder.encode(windows)

        # Compute cosine similarity between adjacent windows
        similarities = []
        for i in range(len(embeddings) - 1):
            vec1 = embeddings[i]
            vec2 = embeddings[i + 1]
            sim = sum(a * b for a, b in zip(vec1, vec2))
            similarities.append(sim)

        # Compute distances (1.0 - similarity)
        distances = [1.0 - sim for sim in similarities]

        if not distances:
            return [" ".join(sentences)]

        # Determine distance threshold via percentile
        threshold = self._percentile(distances, self._threshold_percentile)

        # Find boundaries where distance exceeds threshold
        split_indices = []
        for idx, dist in enumerate(distances):
            if dist >= threshold:
                split_indices.append(idx)

        # Group sentences into initial semantic chunks
        chunks = []
        current_chunk_sentences = []
        for idx, sentence in enumerate(sentences):
            current_chunk_sentences.append(sentence)
            if idx in split_indices:
                chunks.append(" ".join(current_chunk_sentences))
                current_chunk_sentences = []
        if current_chunk_sentences:
            chunks.append(" ".join(current_chunk_sentences))

        # Enforce max chunk size using recursive character splitter fallback
        final_chunks = []
        fallback_chunker = RecursiveTextChunker(
            chunk_size=self._max_chunk_size, chunk_overlap=0
        )
        for chunk in chunks:
            if len(chunk) > self._max_chunk_size:
                final_chunks.extend(fallback_chunker.chunk(chunk))
            else:
                final_chunks.append(chunk)

        return [c.strip() for c in final_chunks if c.strip()]

    @staticmethod
    def _percentile(data: list[float], percentile: float) -> float:
        """Calculate percentile using linear interpolation (pure Python)."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (percentile / 100.0)
        f = int(k)
        c = min(f + 1, len(sorted_data) - 1)
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


# ── Embedding ────────────────────────────────────────────────


class SentenceTransformerEmbedder:
    """Embedding model backed by sentence-transformers.

    The model is loaded lazily on first ``encode()`` call to keep
    import time fast and allow the web server to start without
    loading ML models.
    """

    def __init__(self, model_name: str, dim: int) -> None:
        self._model_name = model_name
        self._dim = dim
        self._model: object | None = None

    @property
    def dimension(self) -> int:
        return self._dim

    def _load(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            logger.info("embedding_model_loaded", model=self._model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts into normalized embeddings."""
        self._load()
        embeddings = self._model.encode(  # type: ignore[union-attr]
            texts, normalize_embeddings=True, show_progress_bar=False
        )
        return embeddings.tolist()  # type: ignore[no-any-return]


# ── Pipeline ─────────────────────────────────────────────────


class IngestionPipeline:
    """End-to-end pipeline: extract text → chunk → embed.

    Usage::

        pipeline = IngestionPipeline(embedder, chunker)
        chunks = pipeline.process(file_bytes, "application/pdf")
    """

    def __init__(
        self,
        embedder: Embedder,
        chunker: RecursiveTextChunker | SemanticTextChunker | None = None,
    ) -> None:
        self._embedder = embedder
        self._chunker = chunker or RecursiveTextChunker()

    def process(
        self,
        content: bytes,
        mime_type: str | None,
    ) -> list[ChunkData]:
        """Process raw file bytes into embedded chunks.

        Args:
            content: Raw file bytes.
            mime_type: MIME type of the file.

        Returns:
            List of ChunkData ready for DB insertion.
        """
        text = extract_text(content, mime_type)
        raw_chunks = self._chunker.chunk(text)

        if not raw_chunks:
            logger.warning("no_chunks_produced", mime_type=mime_type)
            return []

        logger.info("chunking_complete", chunk_count=len(raw_chunks))

        # Batch embed all chunks
        embeddings = self._embedder.encode(raw_chunks)

        results: list[ChunkData] = []
        for idx, (chunk_text, embedding) in enumerate(zip(raw_chunks, embeddings)):
            results.append(
                ChunkData(
                    content=chunk_text,
                    embedding=embedding,
                    chunk_index=idx,
                )
            )

        logger.info("embedding_complete", chunk_count=len(results))
        return results
