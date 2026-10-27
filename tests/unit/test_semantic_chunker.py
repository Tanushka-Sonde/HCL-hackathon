"""Unit tests for the SemanticTextChunker."""

from __future__ import annotations

from src.ingestion.pipeline import SemanticTextChunker


class ContentSensitiveMockEmbedder:
    """Mock embedder that returns distinct unit vectors based on topic."""

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = [0.0] * self._dim
            # Standardize vectors so dot product equals cosine similarity
            if (
                "finance" in text.lower()
                or "revenue" in text.lower()
                or "money" in text.lower()
            ):
                vec[0] = 1.0
            elif (
                "vacation" in text.lower()
                or "beach" in text.lower()
                or "holiday" in text.lower()
            ):
                vec[1] = 1.0
            else:
                vec[2] = 1.0
            results.append(vec)
        return results


class TestSemanticTextChunker:
    def test_semantic_split_on_topic_shift(self) -> None:
        embedder = ContentSensitiveMockEmbedder()
        chunker = SemanticTextChunker(
            embedder=embedder,
            threshold_percentile=60.0,
            max_chunk_size=1000,
            buffer_size=0,
        )

        text = (
            "We had high finance growth. "
            "Our revenue and money increased. "
            "I want a beach vacation. "
            "Let us go on a holiday to the beach."
        )

        chunks = chunker.chunk(text)

        # Should split exactly into 2 chunks on the topic boundary
        assert len(chunks) == 2
        assert "finance" in chunks[0]
        assert "revenue" in chunks[0]
        assert "vacation" in chunks[1]
        assert "holiday" in chunks[1]

    def test_short_text_no_split(self) -> None:
        embedder = ContentSensitiveMockEmbedder()
        chunker = SemanticTextChunker(
            embedder=embedder,
            threshold_percentile=60.0,
            max_chunk_size=1000,
            buffer_size=1,
        )

        chunks = chunker.chunk("Short sentence.")
        assert chunks == ["Short sentence."]

        chunks_empty = chunker.chunk("   ")
        assert chunks_empty == []

    def test_max_chunk_size_fallback(self) -> None:
        embedder = ContentSensitiveMockEmbedder()
        # Set max_chunk_size very low so it triggers the fallback recursive split
        chunker = SemanticTextChunker(
            embedder=embedder,
            threshold_percentile=99.0,  # high percentile means no semantic splits
            max_chunk_size=50,
            buffer_size=1,
        )

        text = (
            "This is a very long paragraph. "
            "It goes on and on and on. "
            "We want to split it by character count fallback "
            "because it exceeds fifty characters."
        )

        chunks = chunker.chunk(text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 50

    def test_percentile_calculation(self) -> None:
        # Check pure Python percentile implementation
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert SemanticTextChunker._percentile(data, 0.0) == 1.0
        assert SemanticTextChunker._percentile(data, 100.0) == 5.0
        assert SemanticTextChunker._percentile(data, 50.0) == 3.0
        assert SemanticTextChunker._percentile([], 50.0) == 0.0
