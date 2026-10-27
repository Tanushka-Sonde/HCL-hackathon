/**
 * Typed client for the Knowledge Intelligence Service (/api/v1/kis).
 * Built on the shared fetchApi wrapper.
 */

import { fetchApi } from '@/lib/api';

export type Outcome = 'success' | 'partial' | 'failed';
export type ConfigId = 'A' | 'B';

export interface Evidence {
  source_id: string;
  chunk_id: string;
  document_id: string;
  filename: string;
  doc_id: string;
  title: string;
  category: string | null;
  version: string | null;
  status: string | null;
  page: number | null;
  section: string | null;
  content: string;
  vector_score: number | null;
  vector_rank: number | null;
  bm25_score: number | null;
  bm25_rank: number | null;
  fused_score: number | null;
  fused_rank: number | null;
  rerank_score: number | null;
  relevance: number;
  injection_flag: boolean;
}

export interface ToolCall {
  source_id: string;
  name: string;
  template: string;
  params: Record<string, unknown>;
  status: 'success' | 'error' | 'skipped';
  row_count: number;
  latency_ms: number;
  result_summary: string;
  rows: Record<string, unknown>[];
  error: string | null;
  simulated_failure: boolean;
}

export interface Citation {
  source_id: string;
  valid: boolean;
  target: string | null;
  page: number | null;
  section: string | null;
}

export interface QueryResponse {
  query_id: string;
  session_id: string;
  answer: string;
  outcome: Outcome;
  reason_codes: string[];
  flags: string[];
  confidence: 'high' | 'medium' | 'low';
  route: 'docs' | 'sql_tool' | 'both';
  citations: Citation[];
  evidence: Evidence[];
  tool_calls: ToolCall[];
  conflicts: string[];
  safety: {
    query_injection: string[];
    injection_blocked: boolean;
    chunk_injections: { chunk_id: string; filename: string; patterns: string[]; removed_text: string[]; action: string }[];
    pii_redactions: Record<string, number>;
    fallback: boolean;
    events: number;
  };
  grounding_score: number | null;
  latency_ms: number;
  llm_mode: 'groq' | 'extractive';
}

export interface DocumentInfo {
  id: string;
  filename: string;
  doc_id: string;
  title: string;
  category: string | null;
  version: string | null;
  status: string | null;
  effective_date: string | null;
  mime_type: string;
  size_bytes: number;
  pages: number | null;
  chunk_count: number;
  created_at: string;
}

export interface Rate { count: number; of: number; rate: number | null }
export interface Latency { p50: number | null; p95: number | null; n: number }

export interface Metrics {
  total_queries: number;
  execution: { http_ok: number; stage_errors: number };
  outcomes: Record<Outcome, { count: number; rate: number | null }>;
  reason_codes: Record<string, number>;
  flags: Record<string, number>;
  retrieval_success: Rate;
  grounding_rate: Rate;
  citation_support: Rate;
  tool_success: Rate;
  safety_events: { queries_with_events: number; query_injection: number; embedded_injection: number; pii_redaction: number };
  latency_ms: { retrieval: Latency; tool: Latency; llm: Latency; total: Latency };
  usage: { input_tokens: number; output_tokens: number; estimated_cost_usd: number; avg_cost_per_query_usd: number | null };
  feedback: { helpful: number; not_helpful: number; rate_helpful: number | null };
  by_config: Record<string, { total: number; success_rate: number | null; p50_total_ms: number | null }>;
}

export interface QuerySummary {
  query_id: string;
  timestamp: string;
  session_id: string;
  config_id: ConfigId;
  query: string;
  route: string;
  outcome: Outcome;
  reason_codes: string[];
  flags: string[];
  total_ms: number;
  sources: string[];
  citations: number;
  citations_valid: boolean;
  grounding_score: number | null;
  tool_status: string | null;
  safety_events: number;
  feedback: { helpful: boolean; comment: string | null } | null;
  eval_run_id: string | null;
}

// The full drill-down event is large and mostly rendered generically.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type QueryEvent = Record<string, any>;

export interface KisConfig {
  mode: string;
  app_version: string;
  embedder: string;
  reranker: string;
  llm_provider: string;
  llm_model: string;
  prompt_template_version: string;
  indexed_chunks: number;
  configs: Record<ConfigId, string>;
  sql_templates: string[];
}

export interface Filters {
  config_id?: string;
  outcome?: string;
  since_hours?: string;
  include_eval?: boolean;
}

function qs(filters: Filters & { limit?: number }): string {
  const p = new URLSearchParams();
  if (filters.config_id) p.set('config_id', filters.config_id);
  if (filters.outcome) p.set('outcome', filters.outcome);
  if (filters.since_hours) p.set('since_hours', filters.since_hours);
  if (filters.include_eval === false) p.set('include_eval', 'false');
  if (filters.limit) p.set('limit', String(filters.limit));
  const s = p.toString();
  return s ? `?${s}` : '';
}

export const kis = {
  config: (): Promise<KisConfig> => fetchApi('/kis/config'),
  documents: (): Promise<DocumentInfo[]> => fetchApi('/kis/documents'),
  deleteDocument: (id: string) => fetchApi(`/kis/documents/${id}`, { method: 'DELETE' }),
  ingestDemo: (): Promise<{ ingested: { document: DocumentInfo; duplicate: boolean }[]; errors: { filename: string; error: string }[] }> =>
    fetchApi('/kis/ingest/demo', { method: 'POST' }),
  upload: (file: File): Promise<{ document: DocumentInfo; duplicate: boolean }> => {
    const form = new FormData();
    form.append('file', file);
    return fetchApi('/kis/ingest', { method: 'POST', body: form });
  },
  query: (body: { query: string; session_id?: string; config_id: ConfigId; top_k?: number; status?: string }): Promise<QueryResponse> =>
    fetchApi('/kis/query', { method: 'POST', body: JSON.stringify(body) }),
  feedback: (query_id: string, helpful: boolean, comment?: string) =>
    fetchApi('/kis/feedback', { method: 'POST', body: JSON.stringify({ query_id, helpful, comment: comment || null }) }),
  metrics: (f: Filters): Promise<Metrics> => fetchApi(`/kis/metrics${qs(f)}`),
  queries: (f: Filters, limit = 50): Promise<QuerySummary[]> => fetchApi(`/kis/queries${qs({ ...f, limit })}`),
  query_event: (id: string): Promise<QueryEvent> => fetchApi(`/kis/queries/${id}`),
  startEval: (configs: ConfigId[] = ['A', 'B']) =>
    fetchApi('/kis/eval/run', { method: 'POST', body: JSON.stringify({ configs }) }),
  evalStatus: (): Promise<QueryEvent> => fetchApi('/kis/eval/status'),
};

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);
export const ms = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v)} ms`);
