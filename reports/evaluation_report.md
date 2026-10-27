# Evaluation & Configuration Comparison Report

- Run batch: `fe5a812f` (2026-10-27T09:42:51+00:00 -> 2026-10-27T09:43:03+00:00)
- Generator: `extractive-v1` · embedder `all-MiniLM-L6-v2` · reranker `ms-marco-MiniLM-L-6-v2`
- Evaluation set: `demo/eval/eval_set.json` (40 cases; 3 skipped because a capability is not configured)

## Configurations

- **A** (vector only): `A|vector-only|emb:all-MiniLM-L6-v2|chunk:800/120`
- **B** (hybrid + rerank): `B|hybrid(vector+bm25,rrf)+rerank:ms-marco-MiniLM-L-6-v2|emb:all-MiniLM-L6-v2|chunk:800/120`
- **C** (hybrid, no rerank): `C|hybrid(vector+bm25,rrf)-no-rerank|emb:all-MiniLM-L6-v2|chunk:800/120`

## Summary

| Metric | A | B | C |
|---|---|---|---|
| Expected behaviour pass rate | 0.9189 | 0.9189 | 0.9189 |
| Retrieval hit rate (expected docs found) | 0.9259 | 0.9259 | 0.9259 |
| Hit@1 (expected doc ranked first) | 0.8519 | 0.9259 | 0.8519 |
| MRR@5 | 0.8765 | 0.9259 | 0.8889 |
| Expected section retrieved | 1.0 | 1.0 | 1.0 |
| Answer criteria met (must-include terms) | 0.8571 | 0.8571 | 0.8571 |
| Average grounding score | 0.9792 | 0.981 | 0.9792 |
| Citations valid (answered cases only) | 1.0 | 1.0 | 1.0 |
| Outcome = Success | 0.0 | 0.0 | 0.0 |
| Median latency (ms) | 17.51 | 239.49 | 22.02 |
| Max latency (ms) | 25.28 | 362.29 | 43.36 |
| Total LLM tokens | 0 | 0 | 0 |
| Estimated cost (USD) | 0.0 | 0.0 | 0.0 |

## By scenario (behaviour passed / cases)

| Scenario | A | B | C |
|---|---|---|---|
| Chart from a table | 1/1 | 1/1 | 1/1 |
| Combined question | 2/2 | 2/2 | 2/2 |
| Conflicting documents | 2/2 | 2/2 | 2/2 |
| Direct factual question | 2/2 | 2/2 | 2/2 |
| Embedded prompt injection | 1/1 | 1/1 | 1/1 |
| Exact ID or acronym | 9/9 | 9/9 | 9/9 |
| Fact inside a table | 1/1 | 1/1 | 1/1 |
| Insufficient evidence | 3/3 | 3/3 | 3/3 |
| Multi-turn follow-up | 4/4 | 4/4 | 4/4 |
| Paraphrase (semantic) | 0/2 | 0/2 | 0/2 |
| Personal data masking (user role) | 1/1 | 1/1 | 1/1 |
| Prompt injection in the question | 2/2 | 2/2 | 2/2 |
| Regression question | 1/1 | 1/1 | 1/1 |
| Similar policies | 2/2 | 2/2 | 2/2 |
| Structured-data question | 2/3 | 2/3 | 2/3 |
| Tool failure | 1/1 | 1/1 | 1/1 |

## Per-case results

| Case | Scenario | A behaviour / rank | B behaviour / rank | C behaviour / rank |
|---|---|---|---|---|
| direct-01 | Direct factual question | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| direct-02 | Direct factual question | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| exact-id-01 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| exact-id-02 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| acronym-01 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| multiturn-01 | Multi-turn follow-up | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| structured-01 | Structured-data question | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| structured-02 | Structured-data question | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| combined-01 | Combined question | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| insufficient-01 | Insufficient evidence | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| insufficient-02 | Insufficient evidence | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| conflict-01 | Conflicting documents | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| injection-01 | Embedded prompt injection | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| injection-02 | Prompt injection in the question | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| toolfail-01 | Tool failure | pass / - (failed) | pass / - (failed) | pass / - (failed) |
| regression-01 | Regression question | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| exact-id-03 | Exact ID or acronym | pass / #3 (partial) | pass / #1 (partial) | pass / #2 (partial) |
| exact-id-04 | Exact ID or acronym | pass / #3 (partial) | pass / #1 (partial) | pass / #2 (partial) |
| exact-id-05 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| acronym-02 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| acronym-03 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| acronym-04 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| paraphrase-01 | Paraphrase (semantic) | FAIL / miss (partial) | FAIL / miss (partial) | FAIL / miss (partial) |
| paraphrase-02 | Paraphrase (semantic) | FAIL / miss (partial) | FAIL / miss (partial) | FAIL / miss (partial) |
| table-01 | Fact inside a table | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| distractor-01 | Similar policies | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| distractor-02 | Similar policies | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| multiturn-02 | Multi-turn follow-up | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| multiturn-03 | Multi-turn follow-up | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| multiturn-04 | Multi-turn follow-up | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| structured-03 | Structured-data question | FAIL / - (partial) | FAIL / - (partial) | FAIL / - (partial) |
| combined-02 | Combined question | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| insufficient-03 | Insufficient evidence | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| conflict-02 | Conflicting documents | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| injection-03 | Prompt injection in the question | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| pii-01 | Personal data masking (user role) | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| chart-01 | Chart from a table | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| calc-01 | Table arithmetic | skipped (no LLM configured) | skipped (no LLM configured) | skipped (no LLM configured) |
| ocr-01 | Scanned document (OCR) | skipped (vision not configured) | skipped (vision not configured) | skipped (vision not configured) |
| handwriting-01 | Handwritten note (OCR) | skipped (vision not configured) | skipped (vision not configured) | skipped (vision not configured) |

## Observed failure cases (automatic list)

- [A] **paraphrase-01** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `27bc8c13-dfcb-49d4-a0eb-77fcc4a1a806`
- [A] **paraphrase-02** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `12a5a251-e7aa-49cf-aeee-c94c7a974eef`
- [A] **structured-03** (Structured-data question): outcome `partial`, reasons ['LLM_FALLBACK'], rank None - query `af842bf3-ae00-474a-8486-fda53b58bb6b`
- [B] **paraphrase-01** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `4290aa3b-bf5a-4137-9bf1-62b21b301f2a`
- [B] **paraphrase-02** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `05f46d1f-32c7-4b45-baa0-b641eaa1e122`
- [B] **structured-03** (Structured-data question): outcome `partial`, reasons ['LLM_FALLBACK'], rank None - query `c361e1bf-2889-402f-9197-af6d6c260c9f`
- [C] **paraphrase-01** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `72ff7481-d127-46ab-8a24-2c1d02a50db0`
- [C] **paraphrase-02** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `fe532e88-99ec-4b2c-ae0a-71c0539a066c`
- [C] **structured-03** (Structured-data question): outcome `partial`, reasons ['LLM_FALLBACK'], rank None - query `f461957d-d51b-4920-bf14-429eab92387a`

## What changed and recommendation

Configuration B adds BM25 keyword retrieval, Reciprocal Rank Fusion and a reranking stage on top of A's dense vector retrieval. C is B without the reranker, to show what the reranker adds for its latency cost.
- Expected behaviour pass rate: A=0.9189 B=0.9189 (delta +0.0)
- Retrieval hit rate (expected docs found): A=0.9259 B=0.9259 (delta +0.0)
- Hit@1 (expected doc ranked first): A=0.8519 B=0.9259 (delta +0.074)
- MRR@5: A=0.8765 B=0.9259 (delta +0.0494)
- Expected section retrieved: A=1.0 B=1.0 (delta +0.0)
- Answer criteria met (must-include terms): A=0.8571 B=0.8571 (delta +0.0)
- Average grounding score: A=0.9792 B=0.981 (delta +0.0018)
- Citations valid (answered cases only): A=1.0 B=1.0 (delta +0.0)
- Median latency delta (B - A): +222.0 ms

**Recommended configuration: B (hybrid + rerank)**, because it improves quality without regressing any quality metric.
