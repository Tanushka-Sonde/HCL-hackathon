"""Unit tests for the ingestion pipeline (no DB, no ML model required)."""

from __future__ import annotations

import pytest

from src.ingestion.pipeline import (
    ChunkData,
    IngestionPipeline,
    RecursiveTextChunker,
    extract_text,
)

# ── Mock Embedder ────────────────────────────────────────────


class MockEmbedder:
    """Returns fixed-dimension zero vectors for testing."""

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dim for _ in texts]


# ── Text Extraction ──────────────────────────────────────────


class TestExtractText:
    def test_plain_text(self) -> None:
        text = extract_text(b"Hello, world!", "text/plain")
        assert text == "Hello, world!"

    def test_markdown(self) -> None:
        text = extract_text(b"# Title\nBody", "text/markdown")
        assert "Title" in text

    def test_none_mime_type_treated_as_text(self) -> None:
        text = extract_text(b"plain content", None)
        assert text == "plain content"

    def test_unsupported_type_raises(self) -> None:
        from src.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="Unsupported"):
            extract_text(b"data", "application/zip")

    def test_utf8_with_bom(self) -> None:
        bom = b"\xef\xbb\xbf"
        text = extract_text(bom + b"Hello", "text/plain")
        assert "Hello" in text


# ── RecursiveTextChunker ─────────────────────────────────────


class TestRecursiveTextChunker:
    def test_short_text_returns_single_chunk(self) -> None:
        chunker = RecursiveTextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.chunk("Short text.")
        assert len(chunks) == 1
        assert chunks[0] == "Short text."

    def test_empty_text_returns_empty(self) -> None:
        chunker = RecursiveTextChunker(chunk_size=100, chunk_overlap=10)
        assert chunker.chunk("") == []
        assert chunker.chunk("   ") == []

    def test_splits_on_paragraphs(self) -> None:
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunker = RecursiveTextChunker(chunk_size=30, chunk_overlap=0)
        chunks = chunker.chunk(text)
        assert len(chunks) >= 2

    def test_chunks_are_smaller_than_input(self) -> None:
        # Generate a long text
        text = " ".join(["word"] * 500)
        chunker = RecursiveTextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.chunk(text)
        assert len(chunks) > 1
        # Each chunk should be much smaller than the full text
        for c in chunks:
            assert len(c) < len(text)

    def test_overlap_greater_than_size_raises(self) -> None:
        with pytest.raises(ValueError, match="less than"):
            RecursiveTextChunker(chunk_size=10, chunk_overlap=10)

    def test_no_overlap(self) -> None:
        text = "A" * 200
        chunker = RecursiveTextChunker(chunk_size=100, chunk_overlap=0)
        chunks = chunker.chunk(text)
        assert len(chunks) == 2

    def test_preserves_content(self) -> None:
        """All original content should appear in at least one chunk."""
        words = [f"word{i}" for i in range(50)]
        text = " ".join(words)
        chunker = RecursiveTextChunker(chunk_size=100, chunk_overlap=20)
        chunks = chunker.chunk(text)
        combined = " ".join(chunks)
        for word in words:
            assert word in combined


# ── IngestionPipeline ────────────────────────────────────────


class TestIngestionPipeline:
    def test_process_produces_chunks(self) -> None:
        embedder = MockEmbedder(dim=384)
        pipeline = IngestionPipeline(embedder)
        chunks = pipeline.process(b"This is a test document.", "text/plain")
        assert len(chunks) >= 1
        assert isinstance(chunks[0], ChunkData)

    def test_chunk_has_embedding(self) -> None:
        embedder = MockEmbedder(dim=384)
        pipeline = IngestionPipeline(embedder)
        chunks = pipeline.process(b"Some content here.", "text/plain")
        assert len(chunks[0].embedding) == 384

    def test_chunk_indexes_are_sequential(self) -> None:
        embedder = MockEmbedder(dim=384)
        chunker = RecursiveTextChunker(chunk_size=20, chunk_overlap=0)
        pipeline = IngestionPipeline(embedder, chunker)
        text = "First part. Second part. Third part."
        chunks = pipeline.process(text.encode(), "text/plain")
        indexes = [c.chunk_index for c in chunks]
        assert indexes == list(range(len(chunks)))

    def test_empty_file_returns_no_chunks(self) -> None:
        embedder = MockEmbedder(dim=384)
        pipeline = IngestionPipeline(embedder)
        chunks = pipeline.process(b"", "text/plain")
        assert chunks == []

    def test_unsupported_mime_raises(self) -> None:
        from src.core.exceptions import ValidationError

        embedder = MockEmbedder(dim=384)
        pipeline = IngestionPipeline(embedder)
        with pytest.raises(ValidationError):
            pipeline.process(b"data", "application/zip")
