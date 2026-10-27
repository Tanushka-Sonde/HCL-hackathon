# Evaluation & Configuration Comparison Report

- Run batch: `ff6d7920` (2026-10-27T10:20:41+00:00 -> 2026-10-27T10:34:06+00:00)
- Generator: `openai/gpt-oss-120b` · embedder `all-MiniLM-L6-v2` · reranker `ms-marco-MiniLM-L-6-v2`
- Evaluation set: `demo/eval/eval_set.json` (41 cases; 0 skipped because a capability is not configured)

## Configurations

- **A** (vector only): `A|vector-only|emb:all-MiniLM-L6-v2|chunk:800/120`
- **B** (hybrid + rerank): `B|hybrid(vector+bm25,rrf)+rerank:ms-marco-MiniLM-L-6-v2|emb:all-MiniLM-L6-v2|chunk:800/120`

## Summary

| Metric | A | B |
|---|---|---|
| Expected behaviour pass rate | 0.9268 | 0.9268 |
| Retrieval hit rate (expected docs found) | 0.931 | 0.931 |
| Hit@1 (expected doc ranked first) | 0.8621 | 0.931 |
| MRR@5 | 0.8966 | 0.931 |
| Expected section retrieved | 1.0 | 1.0 |
| Answer criteria met (must-include terms) | 0.7812 | 0.8125 |
| Average grounding score | 1.0 | 1.0 |
| Citations valid (answered cases only) | 1.0 | 1.0 |
| Outcome = Success | 0.7561 | 0.7561 |
| Median latency (ms) | 705.83 | 916.97 |
| Max latency (ms) | 2332.85 | 2444.7 |
| Total LLM tokens | 24718 | 26289 |
| Estimated cost (USD) | 0.001307 | 0.00139 |

## By scenario (behaviour passed / cases)

| Scenario | A | B |
|---|---|---|
| Chart from a table | 1/1 | 1/1 |
| Combined question | 2/2 | 2/2 |
| Conflicting documents | 2/2 | 2/2 |
| Direct factual question | 2/2 | 2/2 |
| Embedded prompt injection | 1/1 | 1/1 |
| Exact ID or acronym | 9/9 | 9/9 |
| Fact inside a table | 1/1 | 1/1 |
| Handwritten note (OCR) | 1/1 | 1/1 |
| Insufficient evidence | 3/3 | 3/3 |
| Multi-turn follow-up | 4/4 | 4/4 |
| Paraphrase (semantic) | 0/2 | 0/2 |
| Personal data masking (user role) | 1/1 | 1/1 |
| Prompt injection in the question | 2/2 | 2/2 |
| Regression question | 1/1 | 1/1 |
| Scanned document (OCR) | 1/1 | 1/1 |
| Similar policies | 2/2 | 2/2 |
| Structured-data question | 2/3 | 2/3 |
| Table arithmetic | 2/2 | 2/2 |
| Tool failure | 1/1 | 1/1 |

## Per-case results

| Case | Scenario | A behaviour / rank | B behaviour / rank |
|---|---|---|---|
| direct-01 | Direct factual question | pass / #1 (success) | pass / #1 (success) |
| direct-02 | Direct factual question | pass / #1 (success) | pass / #1 (success) |
| exact-id-01 | Exact ID or acronym | pass / #1 (success) | pass / #1 (success) |
| exact-id-02 | Exact ID or acronym | pass / #1 (success) | pass / #1 (success) |
| acronym-01 | Exact ID or acronym | pass / #1 (success) | pass / #1 (success) |
| multiturn-01 | Multi-turn follow-up | pass / #1 (success) | pass / #1 (success) |
| structured-01 | Structured-data question | pass / - (success) | pass / - (success) |
| structured-02 | Structured-data question | pass / - (success) | pass / - (success) |
| combined-01 | Combined question | pass / #1 (success) | pass / #1 (success) |
| insufficient-01 | Insufficient evidence | pass / - (partial) | pass / - (partial) |
| insufficient-02 | Insufficient evidence | pass / - (partial) | pass / - (partial) |
| conflict-01 | Conflicting documents | pass / #1 (success) | pass / #1 (success) |
| injection-01 | Embedded prompt injection | pass / #1 (success) | pass / #1 (success) |
| injection-02 | Prompt injection in the question | pass / - (partial) | pass / - (partial) |
| toolfail-01 | Tool failure | pass / - (failed) | pass / - (failed) |
| regression-01 | Regression question | pass / #1 (success) | pass / #1 (success) |
| exact-id-03 | Exact ID or acronym | pass / #2 (success) | pass / #1 (success) |
| exact-id-04 | Exact ID or acronym | pass / #2 (success) | pass / #1 (success) |
| exact-id-05 | Exact ID or acronym | pass / #1 (success) | pass / #1 (success) |
| acronym-02 | Exact ID or acronym | pass / #1 (success) | pass / #1 (success) |
| acronym-03 | Exact ID or acronym | pass / #1 (success) | pass / #1 (success) |
| acronym-04 | Exact ID or acronym | pass / #1 (success) | pass / #1 (success) |
| paraphrase-01 | Paraphrase (semantic) | FAIL / miss (partial) | FAIL / miss (partial) |
| paraphrase-02 | Paraphrase (semantic) | FAIL / miss (partial) | FAIL / miss (partial) |
| table-01 | Fact inside a table | pass / #1 (success) | pass / #1 (success) |
| distractor-01 | Similar policies | pass / #1 (success) | pass / #1 (success) |
| distractor-02 | Similar policies | pass / #1 (success) | pass / #1 (success) |
| multiturn-02 | Multi-turn follow-up | pass / - (partial) | pass / - (partial) |
| multiturn-03 | Multi-turn follow-up | pass / #1 (success) | pass / #1 (success) |
| multiturn-04 | Multi-turn follow-up | pass / #1 (success) | pass / #1 (success) |
| structured-03 | Structured-data question | FAIL / - (partial) | FAIL / - (partial) |
| combined-02 | Combined question | pass / #1 (success) | pass / #1 (success) |
| insufficient-03 | Insufficient evidence | pass / - (partial) | pass / - (partial) |
| conflict-02 | Conflicting documents | pass / #1 (success) | pass / #1 (success) |
| injection-03 | Prompt injection in the question | pass / - (partial) | pass / - (partial) |
| pii-01 | Personal data masking (user role) | pass / #1 (success) | pass / #1 (success) |
| chart-01 | Chart from a table | pass / #1 (success) | pass / #1 (success) |
| calc-01 | Table arithmetic | pass / #1 (success) | pass / #1 (success) |
| ocr-01 | Scanned document (OCR) | pass / - (success) | pass / - (success) |
| handwriting-01 | Handwritten note (OCR) | pass / - (success) | pass / - (success) |
| calc-02 | Table arithmetic | pass / #1 (success) | pass / #1 (success) |

## Observed failure cases (automatic list)

- [A] **paraphrase-01** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `9dbddab3-1ceb-41f7-b845-18bca265330c`
- [A] **paraphrase-02** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `749d1b42-73e2-476b-aaec-72c87432a79a`
- [A] **structured-03** (Structured-data question): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank None - query `fd84784c-3dc3-4267-ba55-94badd0ccf3d`
- [B] **paraphrase-01** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `63531f6b-d4b1-458e-8171-88c87c4564ea`
- [B] **paraphrase-02** (Paraphrase (semantic)): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank 0 - query `819899e3-e5d8-4a90-bd74-d41cec8f440f`
- [B] **structured-03** (Structured-data question): outcome `partial`, reasons ['INSUFFICIENT_EVIDENCE'], rank None - query `3a44b345-25f1-4f2e-9443-e7cb99109839`

## What changed and recommendation

Configuration B adds BM25 keyword retrieval, Reciprocal Rank Fusion and a reranking stage on top of A's dense vector retrieval. C is B without the reranker, to show what the reranker adds for its latency cost.
- Expected behaviour pass rate: A=0.9268 B=0.9268 (delta +0.0)
- Retrieval hit rate (expected docs found): A=0.931 B=0.931 (delta +0.0)
- Hit@1 (expected doc ranked first): A=0.8621 B=0.931 (delta +0.0689)
- MRR@5: A=0.8966 B=0.931 (delta +0.0344)
- Expected section retrieved: A=1.0 B=1.0 (delta +0.0)
- Answer criteria met (must-include terms): A=0.7812 B=0.8125 (delta +0.0313)
- Average grounding score: A=1.0 B=1.0 (delta +0.0)
- Citations valid (answered cases only): A=1.0 B=1.0 (delta +0.0)
- Median latency delta (B - A): +211.1 ms

**Recommended configuration: B (hybrid + rerank)**, because it improves quality without regressing any quality metric.
