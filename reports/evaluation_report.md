# Evaluation & Configuration Comparison Report

- Run batch: `bb1d4cab` (2026-10-27T09:20:27+00:00 -> 2026-10-27T09:20:29+00:00)
- Generator: `extractive-v1` · embedder `hashing-384` · reranker `lexical-coverage`
- Evaluation set: `demo/eval/eval_set.json` (40 cases; 3 skipped because a capability is not configured)

## Configurations

- **A** (vector only): `A|vector-only|emb:hashing-384|chunk:800/120`
- **B** (hybrid + rerank): `B|hybrid(vector+bm25,rrf)+rerank:lexical-coverage|emb:hashing-384|chunk:800/120`
- **C** (hybrid, no rerank): `C|hybrid(vector+bm25,rrf)-no-rerank|emb:hashing-384|chunk:800/120`

## Summary

| Metric | A | B | C |
|---|---|---|---|
| Expected behaviour pass rate | 0.8649 | 0.8649 | 0.8649 |
| Retrieval hit rate (expected docs found) | 0.8519 | 0.8519 | 0.8519 |
| Hit@1 (expected doc ranked first) | 0.7037 | 0.8519 | 0.7407 |
| MRR@5 | 0.7512 | 0.8519 | 0.7963 |
| Expected section retrieved | 1.0 | 1.0 | 1.0 |
| Answer criteria met (must-include terms) | 0.7857 | 0.7857 | 0.7857 |
| Average grounding score | 0.9923 | 0.9923 | 0.9923 |
| Citations valid (answered cases only) | 1.0 | 1.0 | 1.0 |
| Outcome = Success | 0.0 | 0.0 | 0.0 |
| Median latency (ms) | 6.89 | 6.82 | 6.94 |
| Max latency (ms) | 82.2 | 8.84 | 9.21 |
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
| Exact ID or acronym | 8/9 | 8/9 | 8/9 |
| Fact inside a table | 1/1 | 1/1 | 1/1 |
| Insufficient evidence | 3/3 | 3/3 | 3/3 |
| Multi-turn follow-up | 3/4 | 3/4 | 3/4 |
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
| exact-id-02 | Exact ID or acronym | pass / #3 (partial) | pass / #1 (partial) | pass / #1 (partial) |
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
| exact-id-03 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| exact-id-04 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| exact-id-05 | Exact ID or acronym | pass / #4 (partial) | pass / #1 (partial) | pass / #2 (partial) |
| acronym-02 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| acronym-03 | Exact ID or acronym | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| acronym-04 | Exact ID or acronym | FAIL / miss (partial) | FAIL / miss (partial) | FAIL / miss (partial) |
| paraphrase-01 | Paraphrase (semantic) | FAIL / miss (partial) | FAIL / miss (partial) | FAIL / miss (partial) |
| paraphrase-02 | Paraphrase (semantic) | FAIL / miss (partial) | FAIL / miss (partial) | FAIL / miss (partial) |
| table-01 | Fact inside a table | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| distractor-01 | Similar policies | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| distractor-02 | Similar policies | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| multiturn-02 | Multi-turn follow-up | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| multiturn-03 | Multi-turn follow-up | pass / #2 (partial) | pass / #1 (partial) | pass / #2 (partial) |
| multiturn-04 | Multi-turn follow-up | FAIL / miss (partial) | FAIL / miss (partial) | FAIL / miss (partial) |
| structured-03 | Structured-data question | FAIL / - (partial) | FAIL / - (partial) | FAIL / - (partial) |
| combined-02 | Combined question | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| insufficient-03 | Insufficient evidence | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| conflict-02 | Conflicting documents | pass / #5 (partial) | pass / #1 (partial) | pass / #2 (partial) |
| injection-03 | Prompt injection in the question | pass / - (partial) | pass / - (partial) | pass / - (partial) |
| pii-01 | Personal data masking (user role) | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| chart-01 | Chart from a table | pass / #1 (partial) | pass / #1 (partial) | pass / #1 (partial) |
| calc-01 | Table arithmetic | skipped (no LLM configured) | skipped (no LLM configured) | skipped (no LLM configured) |
| ocr-01 | Scanned document (OCR) | skipped (vision not configured) | skipped (vision not configured) | skipped (vision not configured) |
| handwriting-01 | Handwritten note (OCR) | skipped (vision not configured) | skipped (vision not configured) | skipped (vision not configured) |

## Observed failure cases (automatic list)

- [A] **acronym-04** (Exact ID or acronym): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `730da3e2-fe42-4db0-a2ac-ede9625682b9`
- [A] **paraphrase-01** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `8e817971-3e9b-46d3-8bb8-cfc910015fe8`
- [A] **paraphrase-02** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `5b3d3f51-60b4-496c-845e-8d6cbe0b7213`
- [A] **multiturn-04** (Multi-turn follow-up): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `daac98eb-404b-461f-895f-92994ba94a32`
- [A] **structured-03** (Structured-data question): outcome `partial`, reasons ['LLM_FALLBACK'], rank None - query `dab7298a-3337-4af5-981c-2d510a4e1fb8`
- [B] **acronym-04** (Exact ID or acronym): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `af059ce2-169e-478b-8a1a-3edafdce5315`
- [B] **paraphrase-01** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `39065dca-00a4-43f2-abb6-3a62b90cfb03`
- [B] **paraphrase-02** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `b3521000-029a-47cd-ae4f-97195329bdc1`
- [B] **multiturn-04** (Multi-turn follow-up): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `7df41344-33c2-4cf5-8366-804bc053f855`
- [B] **structured-03** (Structured-data question): outcome `partial`, reasons ['LLM_FALLBACK'], rank None - query `9e30d8a6-0969-45ce-9936-118c89fa41b0`
- [C] **acronym-04** (Exact ID or acronym): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `7ba51ac9-46e9-438c-a61a-3f5d2e7324c6`
- [C] **paraphrase-01** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `e2e0a708-649d-4298-847b-24f2f3fc9845`
- [C] **paraphrase-02** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `54d12ec0-1a15-4c2d-8a67-0ec4d88073d5`
- [C] **multiturn-04** (Multi-turn follow-up): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `8d7cb92f-fd5e-4528-a883-8fd6a9c397a2`
- [C] **structured-03** (Structured-data question): outcome `partial`, reasons ['LLM_FALLBACK'], rank None - query `1148c0f5-65c0-4fa4-b560-87ccb1400d58`

## What changed and recommendation

Configuration B adds BM25 keyword retrieval, Reciprocal Rank Fusion and a reranking stage on top of A's dense vector retrieval. C is B without the reranker, to show what the reranker adds for its latency cost.
- Expected behaviour pass rate: A=0.8649 B=0.8649 (delta +0.0)
- Retrieval hit rate (expected docs found): A=0.8519 B=0.8519 (delta +0.0)
- Hit@1 (expected doc ranked first): A=0.7037 B=0.8519 (delta +0.1482)
- MRR@5: A=0.7512 B=0.8519 (delta +0.1007)
- Expected section retrieved: A=1.0 B=1.0 (delta +0.0)
- Answer criteria met (must-include terms): A=0.7857 B=0.7857 (delta +0.0)
- Average grounding score: A=0.9923 B=0.9923 (delta +0.0)
- Citations valid (answered cases only): A=1.0 B=1.0 (delta +0.0)
- Median latency delta (B - A): -0.1 ms

**Recommended configuration: B (hybrid + rerank)**, because it improves quality without regressing any quality metric.
