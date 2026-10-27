/**
 * Typed client for the Knowledge Intelligence Service (/api/v1/kis).
 * Built on the shared fetchApi wrapper, which adds the bearer token.
 */

import { API_BASE_URL, fetchApi } from '@/lib/api';

export type Outcome = 'success' | 'partial' | 'failed';
export type ConfigId = 'A' | 'B';
export type Role = 'admin' | 'user';

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
  content_type: 'text' | 'table' | 'chart' | 'ocr' | 'image';
  source_method: string;
  asset_id: string | null;
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

export interface ChartSpec {
  chart_type: 'line' | 'bar';
  title: string;
  x_label: string;
  y_label: string;
  labels: string[];
  series: { name: string; values: number[] }[];
}

export type Visual =
  | { kind: 'retrieved_chart'; asset_url: string; source_id: string; doc: string; page: number | null; title: string }
  | { kind: 'generated_chart'; spec: ChartSpec; source_ids: string[] };

export interface Calculation {
  expr: string;
  result: string | null;
  error: string | null;
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
    pii_masked: Record<string, number>;
    fallback: boolean;
    events: number;
  };
  grounding_score: number | null;
  calculations: Calculation[];
  visuals: Visual[];
  usage: {
    input_tokens: number;
    output_tokens: number;
    estimated_input_tokens: number;
    budget: { max_input: number; max_output: number };
  };
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
  uploaded_by: string | null;
  vision_input_tokens: number;
  vision_output_tokens: number;
}

export interface IngestResult {
  document: DocumentInfo;
  duplicate: boolean;
  skipped_pages: number[];
  warnings: string[];
}

export interface ChunkRow {
  id: string;
  chunk_index: number;
  page: number | null;
  section: string | null;
  content: string;
  content_type: string;
  source_method: string;
  asset_id: string | null;
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
  safety_events: { queries_with_events: number; query_injection: number; embedded_injection: number; pii_masked: number };
  latency_ms: { retrieval: Latency; tool: Latency; llm: Latency; total: Latency };
  usage: { input_tokens: number; output_tokens: number; estimated_cost_usd: number; avg_cost_per_query_usd: number | null };
  feedback: { helpful: number; not_helpful: number; rate_helpful: number | null };
  by_config: Record<string, { total: number; success_rate: number | null; p50_total_ms: number | null }>;
  eval_retrieval?: { n: number; hit_rate: number | null; mrr: number | null };
  window_note?: string;
}

export interface QuerySummary {
  query_id: string;
  timestamp: string;
  session_id: string;
  user_id: string | null;
  username: string | null;
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
  vision_model: string | null;
  vision_enabled: boolean;
  max_upload_mb: number;
  allowed_types: string[];
}

export interface UserInfo {
  id: string;
  username: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface UserSummary extends UserInfo {
  queries: number;
  sessions: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  outcomes: Record<Outcome, number>;
  safety_events: number;
  last_active: string | null;
  anomalies: string[];
}

export interface SessionRow {
  session_id: string;
  user_id: string;
  created_at: string;
  last_active_at: string;
  query_count: number;
  title: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface Turn {
  query_id: string;
  timestamp: string;
  username: string | null;
  query: string;
  answer: string;
  outcome: Outcome;
  reason_codes: string[];
  citations: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  feedback: { helpful: boolean; comment: string | null } | null;
}

export interface Anomaly {
  user_id: string | null;
  username: string | null;
  rule: string;
  severity: 'high' | 'medium' | 'low';
  count: number;
  window: string;
  first_seen: string;
  last_seen: string;
  example_query_ids: string[];
  detail?: string;
}

export interface Filters {
  config_id?: string;
  outcome?: string;
  since_hours?: string;
  include_eval?: boolean;
  user_id?: string;
}

export interface QueryOptions {
  query: string;
  session_id?: string;
  config_id?: ConfigId;
  category?: string;
  status?: string;
  doc_id?: string;
  max_input_tokens?: number;
  max_output_tokens?: number;
}

function qs(filters: Filters & { limit?: number }): string {
  const p = new URLSearchParams();
  if (filters.config_id) p.set('config_id', filters.config_id);
  if (filters.outcome) p.set('outcome', filters.outcome);
  if (filters.since_hours) p.set('since_hours', filters.since_hours);
  if (filters.include_eval === false) p.set('include_eval', 'false');
  if (filters.user_id) p.set('user_id', filters.user_id);
  if (filters.limit) p.set('limit', String(filters.limit));
  const s = p.toString();
  return s ? `?${s}` : '';
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });
const clean = <T extends object>(o: T) =>
  Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== '')) as Partial<T>;

export const kis = {
  // Auth
  login: (username: string, password: string): Promise<{ access_token: string; username: string; role: Role }> =>
    fetchApi('/kis/auth/login', json({ username, password })),
  me: (): Promise<UserInfo> => fetchApi('/kis/auth/me'),

  // Assistant
  config: (): Promise<KisConfig> => fetchApi('/kis/config'),
  query: (opts: QueryOptions): Promise<QueryResponse> => fetchApi('/kis/query', json(clean(opts))),
  queryWithImage: (opts: QueryOptions, image: File): Promise<QueryResponse> => {
    const form = new FormData();
    form.append('image', image);
    for (const [k, v] of Object.entries(clean(opts))) form.append(k, String(v));
    return fetchApi('/kis/query/multimodal', { method: 'POST', body: form });
  },
  feedback: (query_id: string, helpful: boolean, comment?: string) =>
    fetchApi('/kis/feedback', json({ query_id, helpful, comment: comment || null })),
  myHistory: (session_id?: string): Promise<{ sessions: SessionRow[]; turns: Turn[]; usage: { input_tokens: number; output_tokens: number; cost_usd: number } }> =>
    fetchApi(`/kis/my/history${session_id ? `?session_id=${encodeURIComponent(session_id)}` : ''}`),

  // Knowledge base (admin)
  documents: (): Promise<DocumentInfo[]> => fetchApi('/kis/documents'),
  chunks: (id: string): Promise<ChunkRow[]> => fetchApi(`/kis/documents/${id}/chunks`),
  deleteDocument: (id: string) => fetchApi(`/kis/documents/${id}`, { method: 'DELETE' }),
  ingestDemo: (): Promise<{ ingested: IngestResult[]; errors: { filename: string; error: string }[] }> =>
    fetchApi('/kis/ingest/demo', { method: 'POST' }),
  upload: (file: File, meta: { category?: string; version?: string; status?: string; effective_date?: string } = {}): Promise<IngestResult> => {
    const form = new FormData();
    form.append('file', file);
    for (const [k, v] of Object.entries(clean(meta))) form.append(k, String(v));
    return fetchApi('/kis/ingest', { method: 'POST', body: form });
  },

  // Observability (admin)
  metrics: (f: Filters): Promise<Metrics> => fetchApi(`/kis/metrics${qs(f)}`),
  queries: (f: Filters, limit = 50): Promise<QuerySummary[]> => fetchApi(`/kis/queries${qs({ ...f, limit })}`),
  query_event: (id: string): Promise<QueryEvent> => fetchApi(`/kis/queries/${id}`),
  anomalies: (since_hours = 24): Promise<Anomaly[]> => fetchApi(`/kis/admin/anomalies?since_hours=${since_hours}`),
  startEval: (configs: ('A' | 'B' | 'C')[] = ['A', 'B', 'C']) => fetchApi('/kis/eval/run', json({ configs })),
  evalStatus: (): Promise<QueryEvent> => fetchApi('/kis/eval/status'),

  // Users (admin)
  users: (): Promise<UserInfo[]> => fetchApi('/kis/admin/users'),
  createUser: (username: string, password: string, role: Role): Promise<UserInfo> =>
    fetchApi('/kis/admin/users', json({ username, password, role })),
  usersSummary: (): Promise<UserSummary[]> => fetchApi('/kis/admin/users/summary'),
  userSessions: (id: string): Promise<SessionRow[]> => fetchApi(`/kis/admin/users/${id}/sessions`),
  transcript: (sessionId: string): Promise<Turn[]> => fetchApi(`/kis/admin/sessions/${encodeURIComponent(sessionId)}`),
};

/** Assets need the bearer token, so they are fetched and shown as blob URLs. */
export async function fetchAssetUrl(assetUrl: string): Promise<string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  const path = assetUrl.startsWith(API_BASE_URL) ? assetUrl : `${API_BASE_URL}${assetUrl}`;
  const res = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`Image unavailable (${res.status})`);
  return URL.createObjectURL(await res.blob());
}

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);
export const ms = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v)} ms`);
export const num = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toLocaleString());

/** Plain-language descriptions of outcome reason codes and flags. */
export const REASONS: Record<string, string> = {
  OK: 'Grounded answer with valid citations',
  STAGE_ERROR: 'A pipeline stage failed',
  TOOL_FAILED: 'The data source failed and no document could answer instead',
  INJECTION_BLOCKED: 'The question tried to change the assistant’s rules',
  INSUFFICIENT_EVIDENCE: 'Not enough evidence in the indexed documents',
  TOOL_FAILED_PARTIAL: 'The data source failed; answered from documents only',
  LLM_FALLBACK: 'Language model unavailable; answer built from source sentences',
  NO_CITATIONS: 'The answer has no citations',
  INVALID_CITATIONS: 'Some citations do not match the sources',
  UNSUPPORTED_CLAIMS: 'Some statements are not fully supported by the sources',
  OUTPUT_TRUNCATED: 'The answer hit the output token limit',
  CONFLICT_SURFACED: 'Sources disagree; the conflict is shown',
  EMBEDDED_INJECTION_REMOVED: 'Instructions hidden in a source were ignored',
  PII_MASKED: 'Personal data or salaries were masked',
  EVIDENCE_TRIMMED_FOR_BUDGET: 'Some evidence was left out to fit the token budget',
  CHART_REJECTED: 'A chart was dropped because its values were not in the sources',
};
