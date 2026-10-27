# Query Event Schema & Status Rules

Every `POST /api/v1/kis/query` writes one event to `data/kis.db` (`query_events.payload`, JSON). You can fetch it with `GET /api/v1/kis/queries/{query_id}`.

## Schema

| Section | Fields | Brief §8.2 category |
|---|---|---|
| `identity` | `query_id`, `timestamp`, `session_id`, `app_version`, `config_id` (A/B), `config_label` (pipeline + embedder + chunking), `correlation_id` (`X-Request-ID`) | Identity |
| `question` | `original`, `normalized` (with resolved context), `route` (docs / sql_tool / both), `data_signals`, `doc_signals`, `router_notes`, `filters` | Question |
| `execution` | `http_status`, `stages{context, routing, retrieval, tool, generation, validation}`. Each stage is `ok`, `error`, `skipped`, `fallback`, `not_required` or `empty_index`. | Execution status |
| `outcome` | `status` (success / partial / failed), `reason_codes[]`, `flags[]`, `confidence` | Overall outcome |
| `retrieval[]` | `chunk_id`, `document_id`, `filename`, `doc_id`, `version`, `status`, `page`, `section`, `vector_score`/`vector_rank`, `bm25_score`/`bm25_rank`, `fused_score`/`fused_rank`, `rerank_score`, `coverage`, `relevance`, `selected` | Retrieval |
| `evidence[]` | The evidence sent to the model, as source IDs `S1..Sn`, with sanitized content and an `injection_flag` | Retrieval |
| `evidence_quality` | `evidence_found`, `top_relevance`, `threshold`, `expected_match` (eval queries only) | Evidence quality |
| `context` | `history_turns_available`, `selected_turns[]` (query_id, query, route) | Conversation context |
| `tool_calls[]` | `source_id` (T1), `name`, `template`, `params` (sanitized), `status`, `row_count`, `latency_ms`, `result_summary`, `rows`, `error`, `simulated_failure` | Tool calls |
| `generation` | `provider` (groq / extractive), `model`, `prompt_template_version`, `status`, `error`, `output` | Generation |
| `citations[]` | `source_id`, `valid`, `target`, `page`, `section` | Citations |
| `conflicts[]` | Human-readable version-conflict notes | (FR-09) |
| `grounding` | `score`, `claims`, `supported[]`, `unsupported[{claim, reason}]`, `rule` | Grounding |
| `safety` | `query_injection[]`, `injection_blocked`, `chunk_injections[]`, `pii_redactions{}`, `fallback`, `events` | Safety |
| `performance` | `context_ms`, `retrieval_ms`, `tool_ms`, `llm_ms`, `validation_ms`, `total_ms` | Performance |
| `usage` | `input_tokens`, `output_tokens`, `cached_tokens`, `estimated_cost_usd` | Usage |
| `feedback` | `helpful`, `comment`, `created_at` (latest rating, joined at read time) | Feedback |
| `errors[]` | `stage`, `category`, `message` (sanitized), `retried`, `correlation_id` | Errors |
| `eval` | `run_id`, `case_id`, `scenario`, `expected_docs` (eval runs only) | Evaluation |

## Outcome rules (`src/knowledge/outcome.py`)

The rules are evaluated in order. **HTTP 200 does not imply Success.**

| Outcome | Reason code | Condition |
|---|---|---|
| **Failed** | `STAGE_ERROR` | An unhandled exception in a pipeline stage (retrieval or generation) |
| **Failed** | `TOOL_FAILED` | The question needed the SQL tool, the tool failed, and no document evidence could answer instead |
| Partial / Fallback | `INJECTION_BLOCKED` | The question itself tried to override the assistant's rules |
| Partial / Fallback | `INSUFFICIENT_EVIDENCE` | No evidence ≥ `KIS_MIN_EVIDENCE_SCORE` and no tool rows, or the model declined |
| Partial / Fallback | `TOOL_FAILED_PARTIAL` | The tool failed, but documents still answered |
| Partial / Fallback | `LLM_FALLBACK` | The LLM is unavailable, so the extractive answer was used |
| Partial / Fallback | `NO_CITATIONS` | The answer has no citation tags |
| Partial / Fallback | `INVALID_CITATIONS` | A tag does not map to returned evidence or to a successful tool call |
| Partial / Fallback | `UNSUPPORTED_CLAIMS` | Grounding score < `KIS_GROUNDING_THRESHOLD` (0.7) |
| **Success** | `OK` | Evidence found, all citations valid, grounded, no failed stage |

Several Partial reasons can apply at once.

**Flags** do not change the outcome:
- `CONFLICT_SURFACED`
- `EMBEDDED_INJECTION_REMOVED`
- `PII_REDACTED`

**Grounding rule:** a sentence is a *supported claim* when all three of these hold:
- it cites at least one valid source;
- ≥ 50% of its content tokens appear in the cited sources;
- every number it states appears in the cited sources.

The grounding score is supported claims ÷ total claims.

**Confidence:**

| Confidence | Condition |
|---|---|
| `high` | Success, grounding ≥ 0.9 and top relevance ≥ 0.75 |
| `medium` | Any other Success, or Partial with grounding ≥ 0.7 |
| `low` | Everything else |

## Aggregate KPIs (`GET /kis/metrics`)

| KPI | Definition |
|---|---|
| Total queries | Events in the current filter |
| Execution | HTTP 200 count and events with stage errors |
| Outcomes | Count and rate for success, partial and failed, plus reason-code and flag histograms |
| Retrieval success | Evidence found ÷ queries where retrieval ran |
| Grounding rate | Grounding ≥ threshold ÷ answers with claims |
| Citation support | Answers whose citations are all valid ÷ answered queries (excludes fallback, blocked and error) |
| Tool success | Successful SQL executions ÷ executed tool calls (skipped calls excluded) |
| Safety events | Queries with injection, embedded-injection or PII events |
| Latency | p50 / p95 for retrieval, tool, LLM and total |
| Usage | Token sums and estimated cost |
| Feedback | Helpful and not-helpful counts and rate |
