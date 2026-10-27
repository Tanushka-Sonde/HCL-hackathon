"""Embedding and reranking models with offline-safe fallbacks.

Primary: ``SentenceTransformerEmbedder`` (all-MiniLM-L6-v2) from the existing
ingestion pipeline, and a sentence-transformers cross-encoder reranker.
Fallback: a deterministic feature-hashing embedder and a lexical reranker,
used when the models are not installed or cannot be downloaded. The active
choice is reported in the query event's configuration ID.
"""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING

import numpy as np

from src.core.logging import get_logger
from src.knowledge.text import content_tokens

if TYPE_CHECKING:
    from src.core.config import Settings

logger = get_logger(__name__)


class HashingEmbedder:
    """Deterministic bag-of-words embedder via signed feature hashing.

    Not semantic: it only captures shared vocabulary. Used so the demo runs
    fully offline when the transformer model is unavailable.
    """

    name = "hashing-384"

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = np.zeros(self._dim, dtype=np.float32)
            for tok in content_tokens(text):
                digest = hashlib.md5(tok.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "little") % self._dim
                sign = 1.0 if digest[4] & 1 else -1.0
                vec[idx] += sign
            norm = float(np.linalg.norm(vec))
            if norm > 0:
                vec /= norm
            vectors.append(vec.tolist())
        return vectors


def build_embedder(settings: Settings) -> tuple[object, str, bool]:
    """Return (embedder, name, is_semantic), falling back to hashing."""
    if settings.kis_embedder == "sentence-transformers":
        try:
            from src.ingestion.pipeline import SentenceTransformerEmbedder

            embedder = SentenceTransformerEmbedder(
                model_name=settings.embedding_model_name,
                dim=settings.embedding_dimension,
            )
            embedder.encode(["warm-up"])  # load now so failures fall back here
            name = settings.embedding_model_name.split("/")[-1]
            logger.info("kis_embedder_loaded", embedder=name)
            return embedder, name, True
        except Exception as exc:
            logger.warning("kis_embedder_fallback", error=str(exc)[:200])
    embedder = HashingEmbedder(settings.embedding_dimension)
    return embedder, embedder.name, False


class LexicalReranker:
    """Documented scoring strategy used when no cross-encoder is available.

    score = 0.7 * query-term coverage + 0.3 * exact-ID bonus, where coverage is
    the fraction of distinct query content tokens present in the passage and
    the ID bonus rewards passages containing hyphenated identifiers from the
    query (policy IDs, ticket IDs, project codes).
    """

    name = "lexical-coverage"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q_tokens = set(content_tokens(query))
        ids = {t for t in q_tokens if "-" in t}
        scores = []
        for passage in passages:
            p_tokens = set(content_tokens(passage))
            coverage = len(q_tokens & p_tokens) / len(q_tokens) if q_tokens else 0.0
            id_bonus = (len(ids & p_tokens) / len(ids)) if ids else coverage
            scores.append(round(0.7 * coverage + 0.3 * id_bonus, 6))
        return scores


class CrossEncoderReranker:
    """sentence-transformers cross-encoder; scores mapped to [0, 1] by sigmoid."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model_name)
        self.name = model_name.split("/")[-1]

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        logits = self._model.predict([(query, p) for p in passages])
        return [round(1.0 / (1.0 + math.exp(-float(x))), 6) for x in logits]


def build_reranker(settings: Settings) -> object:
    if settings.kis_reranker == "cross-encoder":
        try:
            reranker = CrossEncoderReranker(settings.kis_reranker_model)
            reranker.score("warm-up", ["warm-up"])
            logger.info("kis_reranker_loaded", reranker=reranker.name)
            return reranker
        except Exception as exc:
            logger.warning("kis_reranker_fallback", error=str(exc)[:200])
    return LexicalReranker()
