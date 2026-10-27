# Evaluation & Configuration Comparison Report

- Run batch: `20d4dbea` (2026-10-27T06:24:28+00:00 -> 2026-10-27T06:24:31+00:00)
- Generator: `extractive-v1`
- Evaluation set: `demo/eval/eval_set.json`

## Configurations

- **A**: `A|vector-only|emb:all-MiniLM-L6-v2|chunk:800/120`
- **B**: `B|hybrid(vector+bm25,rrf)+rerank:ms-marco-MiniLM-L-6-v2|emb:all-MiniLM-L6-v2|chunk:800/120`

## Summary

| Metric | A | B |
|---|---|---|
| Expected behaviour pass rate | 1.0 | 1.0 |
| Retrieval hit rate (expected docs found) | 1.0 | 1.0 |
| Answer criteria met (must-include terms) | 0.9091 | 0.9091 |
| Average grounding score | 0.9792 | 0.9792 |
| Citations valid | 0.75 | 0.75 |
| Outcome = Success | 0.0 | 0.0 |
| Median latency (ms) | 11.28 | 250.93 |
| Max latency (ms) | 14.12 | 278.39 |
| Total LLM tokens | 0 | 0 |
| Estimated cost (USD) | 0.0 | 0.0 |

## Per-case results

| Case | Scenario | A behaviour / retrieval | B behaviour / retrieval |
|---|---|---|---|
| direct-01 | Direct factual question | pass / hit (partial) | pass / hit (partial) |
| direct-02 | Direct factual question | pass / hit (partial) | pass / hit (partial) |
| exact-id-01 | Exact ID or acronym | pass / hit (partial) | pass / hit (partial) |
| exact-id-02 | Exact ID or acronym | pass / hit (partial) | pass / hit (partial) |
| acronym-01 | Exact ID or acronym | pass / hit (partial) | pass / hit (partial) |
| multiturn-01 | Multi-turn follow-up | pass / hit (partial) | pass / hit (partial) |
| structured-01 | Structured-data question | pass / - (partial) | pass / - (partial) |
| structured-02 | Structured-data question | pass / - (partial) | pass / - (partial) |
| combined-01 | Combined question | pass / hit (partial) | pass / hit (partial) |
| insufficient-01 | Insufficient evidence | pass / - (partial) | pass / - (partial) |
| insufficient-02 | Insufficient evidence | pass / - (partial) | pass / - (partial) |
| conflict-01 | Conflicting documents | pass / hit (partial) | pass / hit (partial) |
| injection-01 | Embedded prompt injection | pass / hit (partial) | pass / hit (partial) |
| injection-02 | Prompt injection in the question | pass / - (partial) | pass / - (partial) |
| toolfail-01 | Tool failure | pass / - (failed) | pass / - (failed) |
| regression-01 | Regression question | pass / hit (partial) | pass / hit (partial) |

## Observed failure cases

- None in this run.

## What changed and recommendation

Configuration B adds BM25 keyword retrieval, Reciprocal Rank Fusion and a reranking stage on top of A's dense vector retrieval.
- Expected behaviour pass rate: A=1.0 B=1.0 (delta +0.0)
- Retrieval hit rate (expected docs found): A=1.0 B=1.0 (delta +0.0)
- Answer criteria met (must-include terms): A=0.9091 B=0.9091 (delta +0.0)
- Average grounding score: A=0.9792 B=0.9792 (delta +0.0)
- Citations valid: A=0.75 B=0.75 (delta +0.0)
- Outcome = Success: A=0.0 B=0.0 (delta +0.0)
- Median latency delta (B - A): +239.7 ms

**Recommended configuration: A (vector only)**, because quality is tied on this small set, so the lower-latency configuration wins; re-run on a larger corpus, where keyword/ID queries are harder for dense-only retrieval, before deciding.
