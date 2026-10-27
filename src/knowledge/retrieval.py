"""Hybrid retrieval over the in-process index (FR-04, FR-05).

Configuration A: dense vector retrieval only.
Configuration B: dense + BM25 keyword retrieval, fused with Reciprocal Rank
Fusion (the same ``_reciprocal_rank_fusion`` used by the PostgreSQL path),
then reranked (cross-encoder, or the documented lexical scorer).

Every candidate keeps its raw vector score, BM25 score, fused rank and
rerank score so the observability drill-down can show why it was chosen.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.knowledge.text import content_tokens, keyword_tokens
from src.retrieval.service import _reciprocal_rank_fusion


class BM25Index:
    """Okapi BM25 over tokenized chunk text (k1=1.5, b=0.75)."""

    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._tfs = [Counter(d) for d in docs]
        self._lens = [len(d) for d in docs]
        self._avgdl = (sum(self._lens) / len(docs)) if docs else 0.0
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self._idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def scores(self, query_tokens: list[str]) -> list[float]:
        result = []
        for tf, length in zip(self._tfs, self._lens, strict=False):
            score = 0.0
            for term in set(query_tokens):
                freq = tf.get(term, 0)
                if not freq:
                    continue
                denom = freq + self._k1 * (
                    1 - self._b + self._b * length / (self._avgdl or 1.0)
                )
                score += self._idf.get(term, 0.0) * freq * (self._k1 + 1) / denom
            result.append(score)
        return result


@dataclass
class Candidate:
    """A chunk considered during retrieval, with all scores."""

    chunk: dict[str, Any]
    vector_score: float | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    fused_score: float | None = None
    fused_rank: int | None = None
    rerank_score: float | None = None
    coverage: float = 0.0
    relevance: float = 0.0
    selected: bool = False


@dataclass
class RetrievalResult:
    candidates: list[Candidate] = field(default_factory=list)
    selected: list[Candidate] = field(default_factory=list)
    top_relevance: float = 0.0
    evidence_found: bool = False


class KnowledgeIndex:
    """In-memory vector + BM25 index rebuilt from the store after ingestion."""

    def __init__(self, embedder: Any, is_semantic: bool) -> None:
        self._embedder = embedder
        self._is_semantic = is_semantic
        self._state: tuple[list[dict[str, Any]], np.ndarray, BM25Index] = (
            [],
            np.zeros((0, 1), dtype=np.float32),
            BM25Index([]),
        )

    def rebuild(self, chunks: list[dict[str, Any]]) -> None:
        # Build everything first, then swap in one assignment, so a concurrent
        # search never sees chunks, matrix and BM25 from different versions.
        matrix = (
            np.asarray([c["embedding"] for c in chunks], dtype=np.float32)
            if chunks
            else np.zeros((0, 1), dtype=np.float32)
        )
        bm25 = BM25Index([keyword_tokens(c["index_text"]) for c in chunks])
        self._state = (chunks, matrix, bm25)

    @property
    def chunks(self) -> list[dict[str, Any]]:
        return self._state[0]

    def __len__(self) -> int:
        return len(self.chunks)

    def search(
        self,
        query: str,
        *,
        config_id: str,
        reranker: Any,
        top_k: int,
        min_relevance: float,
        category: str | None = None,
        status: str | None = None,
        doc_id: str | None = None,
        version: str | None = None,
        candidate_pool: int = 20,
    ) -> RetrievalResult:
        """Run configuration A or B and return scored candidates."""
        chunks, matrix, bm25 = self._state  # one consistent snapshot
        allowed = [
            i
            for i, c in enumerate(chunks)
            if (not category or (c.get("category") or "").lower() == category.lower())
            and (not status or (c.get("status") or "").lower() == status.lower())
            and (not doc_id or (c.get("doc_id") or "").lower() == doc_id.lower())
            and (not version or (c.get("version") or "") == version)
        ]
        if not allowed:
            return RetrievalResult()

        # Dense retrieval
        q_vec = np.asarray(self._embedder.encode([query])[0], dtype=np.float32)
        sims = matrix[allowed] @ q_vec
        dense_order = np.argsort(-sims)[:candidate_pool]
        dense = [(allowed[j], float(sims[j])) for j in dense_order]

        cands: dict[int, Candidate] = {}
        for rank, (idx, score) in enumerate(dense, start=1):
            cands[idx] = Candidate(
                chunks[idx], vector_score=round(score, 6), vector_rank=rank
            )

        if config_id == "A":
            ordered = [idx for idx, _ in dense]
        else:
            # Sparse retrieval (BM25)
            bm25_all = bm25.scores(keyword_tokens(query))
            sparse = sorted(
                ((i, bm25_all[i]) for i in allowed if bm25_all[i] > 0),
                key=lambda x: x[1],
                reverse=True,
            )[:candidate_pool]
            for rank, (idx, score) in enumerate(sparse, start=1):
                cand = cands.setdefault(idx, Candidate(chunks[idx]))
                cand.bm25_score = round(score, 6)
                cand.bm25_rank = rank

            # Reciprocal Rank Fusion (shared with the PostgreSQL retrieval path)
            fused = _reciprocal_rank_fusion(
                [_rrf_row(chunks[i]) for i, _ in dense],
                [_rrf_row(chunks[i]) for i, _ in sparse],
                top_k=candidate_pool,
            )
            id_to_idx = {c["chunk_id"]: i for i, c in enumerate(chunks)}
            ordered = []
            for rank, item in enumerate(fused, start=1):
                idx = id_to_idx[str(item.chunk_id)]
                cands[idx].fused_score = item.score
                cands[idx].fused_rank = rank
                ordered.append(idx)

        # Relevance signals used for the insufficient-evidence decision
        q_tokens = set(content_tokens(query))
        for idx in ordered:
            cand = cands[idx]
            p_tokens = set(content_tokens(cand.chunk["index_text"]))
            cand.coverage = (
                round(len(q_tokens & p_tokens) / len(q_tokens), 6) if q_tokens else 0.0
            )

        if config_id == "B":
            pool = ordered[: max(top_k * 2, 10)]
            scores = reranker.score(query, [cands[i].chunk["index_text"] for i in pool])
            for idx, score in zip(pool, scores, strict=False):
                cands[idx].rerank_score = score
            ordered = sorted(
                pool, key=lambda i: cands[i].rerank_score or 0.0, reverse=True
            )

        uses_cross_encoder = (
            config_id == "B" and getattr(reranker, "name", "") != "lexical-coverage"
        )
        for idx in ordered:
            cand = cands[idx]
            signals = [cand.coverage]
            if uses_cross_encoder and cand.rerank_score is not None:
                signals.append(cand.rerank_score)
            if self._is_semantic and cand.vector_score is not None:
                signals.append(cand.vector_score)
            cand.relevance = round(max(signals), 6)

        selected = [cands[i] for i in ordered[:top_k]]
        for cand in selected:
            cand.selected = True
        top_rel = max((c.relevance for c in selected), default=0.0)

        all_cands = sorted(
            cands.values(),
            key=lambda c: (
                not c.selected,
                -(c.rerank_score or 0.0) if config_id == "B" else 0.0,
                c.fused_rank or c.vector_rank or 999,
            ),
        )
        return RetrievalResult(
            candidates=all_cands,
            selected=selected,
            top_relevance=top_rel,
            evidence_found=top_rel >= min_relevance,
        )


def _rrf_row(c: dict[str, Any]) -> dict[str, Any]:
    """Row shape expected by ``_reciprocal_rank_fusion``."""
    return {
        "chunk_id": uuid.UUID(c["chunk_id"]),
        "document_id": uuid.UUID(c["document_id"]),
        "content": c["content"],
        "chunk_index": c["chunk_index"],
        "page_number": c.get("page"),
        "document_filename": c["document_filename"],
    }
