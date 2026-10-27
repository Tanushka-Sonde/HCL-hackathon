"""Unit tests for Reciprocal Rank Fusion (no DB required)."""

from __future__ import annotations

import uuid

from src.retrieval.service import RRF_K, _reciprocal_rank_fusion


def _make_row(
    chunk_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    content: str = "test",
    chunk_index: int = 0,
    page_number: int | None = None,
    document_filename: str = "doc.txt",
    **extra: object,
) -> dict:
    return {
        "chunk_id": str(chunk_id or uuid.uuid4()),
        "document_id": str(document_id or uuid.uuid4()),
        "content": content,
        "chunk_index": chunk_index,
        "page_number": page_number,
        "document_filename": document_filename,
        **extra,
    }


class TestReciprocalRankFusion:
    def test_empty_inputs(self) -> None:
        results = _reciprocal_rank_fusion([], [], top_k=5)
        assert results == []

    def test_dense_only(self) -> None:
        cid = uuid.uuid4()
        dense = [_make_row(chunk_id=cid, distance=0.1)]
        results = _reciprocal_rank_fusion(dense, [], top_k=5)
        assert len(results) == 1
        assert results[0].chunk_id == cid

    def test_sparse_only(self) -> None:
        cid = uuid.uuid4()
        sparse = [_make_row(chunk_id=cid, rank=0.9)]
        results = _reciprocal_rank_fusion([], sparse, top_k=5)
        assert len(results) == 1
        assert results[0].chunk_id == cid

    def test_overlap_boosts_score(self) -> None:
        """A chunk appearing in BOTH lists should rank higher."""
        shared_id = uuid.uuid4()
        only_dense_id = uuid.uuid4()

        dense = [
            _make_row(chunk_id=shared_id, distance=0.1),
            _make_row(chunk_id=only_dense_id, distance=0.2),
        ]
        sparse = [
            _make_row(chunk_id=shared_id, rank=0.9),
        ]

        results = _reciprocal_rank_fusion(dense, sparse, top_k=5)
        assert results[0].chunk_id == shared_id
        assert results[0].score > results[1].score

    def test_respects_top_k(self) -> None:
        dense = [_make_row() for _ in range(10)]
        sparse = [_make_row() for _ in range(10)]
        results = _reciprocal_rank_fusion(dense, sparse, top_k=3)
        assert len(results) == 3

    def test_scores_use_rrf_formula(self) -> None:
        cid = uuid.uuid4()
        dense = [_make_row(chunk_id=cid)]
        results = _reciprocal_rank_fusion(dense, [], top_k=5)
        expected = round(1.0 / (RRF_K + 1), 6)
        assert results[0].score == expected

    def test_dual_appearance_score(self) -> None:
        cid = uuid.uuid4()
        dense = [_make_row(chunk_id=cid)]
        sparse = [_make_row(chunk_id=cid)]
        results = _reciprocal_rank_fusion(dense, sparse, top_k=5)
        expected = round(1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 1), 6)
        assert results[0].score == expected

    def test_ordering_is_deterministic(self) -> None:
        ids = [uuid.uuid4() for _ in range(5)]
        dense = [_make_row(chunk_id=cid) for cid in ids]
        sparse = list(reversed([_make_row(chunk_id=cid) for cid in ids]))

        r1 = _reciprocal_rank_fusion(dense, sparse, top_k=5)
        r2 = _reciprocal_rank_fusion(dense, sparse, top_k=5)
        assert [r.chunk_id for r in r1] == [r.chunk_id for r in r2]
