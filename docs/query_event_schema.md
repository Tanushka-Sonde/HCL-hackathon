# Query Event Schema & Status Rules

Every `POST /api/v1/kis/query` (and `/query/multimodal`) writes one event to `data/kis.db` (`query_events.payload`, JSON). Admins can fetch it with `GET /api/v1/kis/queries/{query_id}`. The stored event is always **raw** (unmasked); masking applies only to what a user-role response shows.

Indexed columns next to the payload: `query_id`, `ts`, `session_id`, `config_id`, `outcome`, `total_ms`, `eval_run_id`, `user_id`, `username`, `role`, `input_tokens`, `output_tokens`, `cost_usd`.

## Schema

| Section | Fields | Brief §8.2 category |
|---|---|---|
| `identity` | `query_id`, `timestamp`, `session_id`, `user_id`, `username`, `role`, `app_version`, `config_id` (A/B/C), `config_label` (pipeline + embedder + chunking), `correlation_id` (`X-Request-ID`) | Identity |
| `question` | `original`, `normalized` (with resolved context and image content), `route` (docs / sql_tool / both), `data_signals`, `doc_signals`, `router_notes`, `filters` (category, status, doc_id, version, top_k) | Question |
| `execution` | `http_status`, `stages{context, routing, retrieval, tool, generation, validation}`. Each stage is `ok`, `error`, `skipped`, `fallback`, `not_required` or `empty_index`. | Execution status |
| `outcome` | `status` (success / partial / failed), `reason_codes[]`, `flags[]`, `confidence` | Overall outcome |
| `retrieval[]` | `chunk_id`, `document_id`, `filename`, `doc_id`, `version`, `status`, `page`, `section`, `vector_score`/`vector_rank`, `bm25_score`/`bm25_rank`, `fused_score`/`fused_rank`, `rerank_score`, `coverage` (IDF-weighted), `relevance`, `selected` | Retrieval |
| `evidence[]` | The evidence sent to the model, as source IDs `S1..Sn`, with sanitized content, `content_type` (text/table/chart/ocr/image), `source_method` (text_layer/vision_ocr/docx/plain), `asset_id`, `bbox` and an `injection_flag` | Retrieval |
| `evidence_quality` | `evidence_found`, `top_relevance`, `threshold`, `expected_match` (eval queries only) | Evidence quality |
| `context` | `history_turns_available`, `selected_turns[]` (query_id, query, route), `rewrite` (`method` none/rule/llm, `carried_terms`, `standalone`) | Conversation context |
| `tool_calls[]` | `source_id` (T1), `name`, `template`, `params` (sanitized), `status`, `row_count`, `latency_ms`, `result_summary`, `rows`, `error` (plain message), `error_detail` (raw driver error, never in API responses), `simulated_failure` | Tool calls |
| `generation` | `provider` (groq / extractive), `model`, `prompt_template_version`, `status`, `error`, `prompt` (`system`, `user`: exactly what the model received), `output` (raw answer) | Generation |
| `citations[]` | `source_id`, `valid`, `target`, `page`, `section` | Citations |
| `conflicts[]` | Human-readable version-conflict notes | (FR-09) |
| `calculations[]` | `expr`, `result`, `error` for each `{{calc: …}}` | Generation |
| `visuals[]` | `retrieved_chart` (asset URL, source, doc, page, title) or `generated_chart` (spec, source IDs) | Generation |
| `chart_rejection` | `reason`, offending `values` when a chart was dropped | Generation |
| `grounding` | `score`, `claims`, `supported[]`, `unsupported[{claim, reason}]`, `rule` | Grounding |
| `safety` | `query_injection[]`, `injection_blocked`, `chunk_injections[]`, `pii_detected{question, evidence, answer}` (counts), `pii_masked{}` (what a user response masked), `fallback`, `events` | Safety |
| `masking` | `applied` (true for role user), `counts` by type | Safety |
| `image_input` | `description`, `used_text`, `removed_instructions`, `model`, `latency_ms`, `size_bytes`, `stored_path` (null unless `KIS_STORE_QUERY_IMAGES=true`) | Question |
| `performance` | `vision_ms`, `context_ms`, `retrieval_ms`, `tool_ms`, `llm_ms`, `validation_ms`, `total_ms` | Performance |
| `usage` | `input_tokens`, `output_tokens`, `by_stage{vision_query, context_rewrite, generation}`, `estimated_input_tokens` (chars ÷ 4), `budget{max_input, max_output}`, `evidence_dropped_for_budget{count, source_ids}`, `truncated_source`, `cached_tokens`, `estimated_cost_usd` | Usage |
| `feedback` | `helpful`, `comment`, `created_at` (latest rating, joined at read time) | Feedback |
| `errors[]` | `stage`, `category`, `message` (sanitized), `correlation_id` | Errors |
| `eval` | `run_id`, `case_id`, `scenario`, `expected_docs`, `rank` (1-based, 0 = missed), `judge` (eval runs only) | Evaluation |

## Outcome rules (`src/knowledge/outcome.py`)

The rules are evaluated in order. **HTTP 200 does not imply Success.**

| Outcome | Reason code | Condition |
|---|---|---|
| **Failed** | `STAGE_ERROR` | An unhandled exception in a pipeline stage (retrieval or generation) |
| **Failed** | `TOOL_FAILED` | The question needed the SQL tool, the tool failed, and no document evidence could answer instead |
| Partial / Fallback | `INJECTION_BLOCKED` | The question itself tried to override the assistant's rules |
| Partial / Fallback | `INSUFFICIENT_EVIDENCE` | No evidence ≥ `KIS_MIN_EVIDENCE_SCORE`, no tool rows and no attached image, or the model declined |
| Partial / Fallback | `TOOL_FAILED_PARTIAL` | The tool failed, but documents still answered |
| Partial / Fallback | `LLM_FALLBACK` | The LLM is unavailable, so the extractive answer was used |
| Partial / Fallback | `NO_CITATIONS` | The answer has no citation tags |
| Partial / Fallback | `INVALID_CITATIONS` | A tag does not map to returned evidence, a successful tool call, or the attached image |
| Partial / Fallback | `UNSUPPORTED_CLAIMS` | Grounding score < `KIS_GROUNDING_THRESHOLD` (0.7) |
| Partial / Fallback | `OUTPUT_TRUNCATED` | The model stopped at the output token limit |
| **Success** | `OK` | Evidence found, all citations valid, grounded, no failed stage |

Several Partial reasons can apply at once.

**Flags** do not change the outcome:
- `CONFLICT_SURFACED`
- `EMBEDDED_INJECTION_REMOVED` (in a document or in an attached image)
- `PII_MASKED` (a user-role response had personal data or salaries masked; replaces `PII_REDACTED`)
- `EVIDENCE_TRIMMED_FOR_BUDGET`
- `CHART_REJECTED`

**Grounding rule:** a sentence is a *supported claim* when all three of these hold:
- it cites at least one valid source, either directly or through a citation later in the same paragraph ("Fact one. Fact two [S1]." covers both; a tag never reaches across a paragraph break);
- ≥ 50% of its content tokens appear in the cited sources;
- every number it states appears in the cited sources, or is the result of a `{{calc: …}}` whose operands all appear there, or was stated by the user in the question.

The grounding score is supported claims ÷ total claims. Citations and grounding are computed on the raw answer before masking, so users and admins get the same scores.

**Confidence:**

| Confidence | Condition |
|---|---|
| `high` | Success, grounding ≥ 0.9 and top relevance ≥ 0.75 |
| `medium` | Any other Success, or Partial with grounding ≥ 0.7 |
| `low` | Everything else |

## Aggregate KPIs (`GET /kis/metrics`)

| KPI | Definition |
|---|---|
| Total queries | Events in the current filter (config, outcome, time window, user, eval runs) |
| Execution | HTTP 200 count and events with stage errors |
| Outcomes | Count and rate for success, partial and failed, plus reason-code and flag histograms |
| Retrieval success | Evidence found ÷ queries where retrieval ran (self-reported by the relevance threshold) |
| Measured retrieval | Eval cases only: expected document retrieved, and MRR@5 |
| Grounding rate | Grounding ≥ threshold ÷ answers with claims |
| Citation support | Answers whose citations are all valid ÷ answered queries (excludes fallback, blocked and error) |
| Tool success | Successful SQL executions ÷ executed tool calls (skipped calls excluded) |
| Safety events | Queries with injection, embedded-injection or masking events |
| Latency | p50 / p95 for retrieval, tool, LLM and total |
| Usage | Token sums and estimated cost |
| Feedback | Helpful and not-helpful counts and rate |

With more than 5,000 stored events and no time filter, metrics default to the last 7 days (`window_note`).
