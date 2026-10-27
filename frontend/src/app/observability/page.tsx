'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { OutcomeBadge } from '@/components/kis/Badges';
import { SERIES_COLORS } from '@/components/kis/ChartView';
import { RequireAuth, usePageTitle } from '@/lib/auth';
import { kis, ms, num, pct, REASONS, type Anomaly, type Filters, type Metrics, type QuerySummary, type UserInfo } from '@/lib/kis';

function Kpi({ label, value, sub, tone, hero }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string; hero?: boolean }) {
  return (
    <div className={`glass-panel kpi ${hero ? 'kpi-hero' : ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={tone ? { color: tone } : undefined}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

const SEVERITY_CLASS = { high: 'badge-danger', medium: 'badge-warn', low: 'badge-muted' } as const;
const tooltipStyle = { background: '#1a1d24', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 8 };

export default function ObservabilityPage() {
  return (
    <RequireAuth role="admin">
      <Observability />
    </RequireAuth>
  );
}

function Observability() {
  usePageTitle('Observability');
  const [filters, setFilters] = useState<Filters>({ include_eval: true });
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [rows, setRows] = useState<QuerySummary[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [auto, setAuto] = useState(false);

  const load = useCallback(
    () =>
      Promise.all([kis.metrics(filters), kis.queries(filters, 100), kis.anomalies(24)])
        .then(([m, q, a]) => {
          setMetrics(m);
          setRows(q);
          setAnomalies(a);
          setError('');
        })
        .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load metrics'))
        .finally(() => setLoading(false)),
    [filters],
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    kis.users().then(setUsers).catch(() => setUsers([]));
  }, []);

  useEffect(() => {
    if (!auto) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [auto, load]);

  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }));
  const m = metrics;
  const total = m?.total_queries || 0;

  const latencyData = m
    ? (['retrieval', 'tool', 'llm', 'total'] as const).map((k) => ({ stage: k === 'llm' ? 'LLM' : k[0].toUpperCase() + k.slice(1), p50: m.latency_ms[k].p50 ?? 0, p95: m.latency_ms[k].p95 ?? 0 }))
    : [];
  const configData = m
    ? Object.entries(m.by_config).map(([c, v]) => ({ config: c === 'A' ? 'A · vector' : 'B · hybrid', success: Math.round((v.success_rate || 0) * 100), latency: v.p50_total_ms ?? 0 }))
    : [];

  return (
    <div className="animate-fade-in stack">
      <div>
        <h1 className="page-title">AI Observability</h1>
        <p className="text-secondary" style={{ fontSize: '0.9rem' }}>
          Every number is computed from logged query events. An HTTP 200 is not counted as a success unless the answer is grounded and cited.
        </p>
      </div>

      <div className="glass-panel panel filter-bar">
        <label className="field"><span>Configuration</span>
          <select className="select" value={filters.config_id || ''} onChange={(e) => set({ config_id: e.target.value || undefined })}>
            <option value="">All</option><option value="A">A · vector only</option><option value="B">B · hybrid + rerank</option>
          </select>
        </label>
        <label className="field"><span>Outcome</span>
          <select className="select" value={filters.outcome || ''} onChange={(e) => set({ outcome: e.target.value || undefined })}>
            <option value="">All</option><option value="success">Success</option><option value="partial">Partial / Fallback</option><option value="failed">Failed</option>
          </select>
        </label>
        <label className="field"><span>Time window</span>
          <select className="select" value={filters.since_hours || ''} onChange={(e) => set({ since_hours: e.target.value || undefined })}>
            <option value="">All time</option><option value="1">Last hour</option><option value="24">Last 24 h</option><option value="168">Last 7 days</option>
          </select>
        </label>
        <label className="field"><span>User</span>
          <select className="select" value={filters.user_id || ''} onChange={(e) => set({ user_id: e.target.value || undefined })}>
            <option value="">All users</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
          </select>
        </label>
        <label className="toggle"><input type="checkbox" checked={filters.include_eval !== false} onChange={(e) => set({ include_eval: e.target.checked })} /> Include evaluation runs</label>
        <label className="toggle"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto-refresh (5 s)</label>
        <button className="btn btn-secondary btn-sm" onClick={load}>Refresh</button>
      </div>

      {error && <div className="banner banner-danger" role="alert">{error}</div>}
      {m?.window_note && <div className="banner banner-info">{m.window_note}</div>}
      {loading && <p className="muted animate-pulse">Loading metrics…</p>}

      {anomalies.length > 0 && (
        <div className="glass-panel panel">
          <h2 className="section-title">Unusual activity (last 24 h)</h2>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Severity</th><th>User</th><th>Rule</th><th>Count</th><th>Window</th><th>Last seen</th><th>Examples</th></tr></thead>
              <tbody>
                {anomalies.map((a, i) => (
                  <tr key={i}>
                    <td><span className={`badge ${SEVERITY_CLASS[a.severity]}`}>{a.severity}</span></td>
                    <td>{a.user_id ? <Link className="text-accent" href={`/users/${a.user_id}`}>{a.username}</Link> : a.username}</td>
                    <td className="mono">{a.rule}{a.detail && <div className="muted">{a.detail}</div>}</td>
                    <td>{num(a.count)}</td>
                    <td>{a.window}</td>
                    <td className="nowrap">{new Date(a.last_seen).toLocaleString()}</td>
                    <td>{a.example_query_ids.slice(0, 3).map((q) => <Link key={q} className="text-accent mono" href={`/observability/${q}`} style={{ marginRight: 6 }}>{q.slice(0, 8)}</Link>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {m && total === 0 && !loading && (
        <div className="glass-panel panel text-center">
          <p className="text-secondary">No query events match these filters yet. Ask something in the Assistant, or run the evaluation set on the Evaluation page.</p>
        </div>
      )}

      {m && total > 0 && (
        <>
          <div className="kpi-grid kpi-grid-hero">
            <Kpi hero label="Success rate" value={pct(m.outcomes.success.rate)} sub={`${m.outcomes.success.count} of ${total} queries`} tone="var(--success)" />
            <Kpi hero label="Grounding rate" value={pct(m.grounding_rate.rate)} sub={`${m.grounding_rate.count}/${m.grounding_rate.of} answers fully supported`} />
            <Kpi hero label="Citation support" value={pct(m.citation_support.rate)} sub={`${m.citation_support.count}/${m.citation_support.of} answers with valid citations`} />
            <Kpi hero label="Median latency" value={ms(m.latency_ms.total.p50)} sub={`p95 ${ms(m.latency_ms.total.p95)}`} />
          </div>
          <div className="kpi-grid">
            <Kpi label="Total queries" value={total} sub={`HTTP 200: ${m.execution.http_ok} · stage errors: ${m.execution.stage_errors}`} />
            <Kpi label="Partial / fallback" value={m.outcomes.partial.count} sub={pct(m.outcomes.partial.rate)} tone="var(--warning)" />
            <Kpi label="Failed" value={m.outcomes.failed.count} sub={pct(m.outcomes.failed.rate)} tone="var(--danger)" />
            <Kpi label="Retrieval success" value={pct(m.retrieval_success.rate)} sub={`${m.retrieval_success.count}/${m.retrieval_success.of} found relevant evidence (self-reported)`} />
            {m.eval_retrieval && m.eval_retrieval.n > 0 && (
              <Kpi label="Measured retrieval (eval)" value={pct(m.eval_retrieval.hit_rate)} sub={`MRR ${m.eval_retrieval.mrr?.toFixed(2) ?? '—'} over ${m.eval_retrieval.n} eval cases`} />
            )}
            <Kpi label="Tool success" value={m.tool_success.of ? pct(m.tool_success.rate) : '—'} sub={m.tool_success.of ? `${m.tool_success.count}/${m.tool_success.of} SQL calls` : 'No tool calls yet'} />
            <Kpi label="Safety events" value={m.safety_events.queries_with_events} sub={`injection ${m.safety_events.query_injection} · in documents ${m.safety_events.embedded_injection} · masked ${m.safety_events.pii_masked}`} />
            <Kpi
              label="Usage & cost"
              value={m.usage.input_tokens + m.usage.output_tokens ? `$${m.usage.estimated_cost_usd.toFixed(4)}` : '—'}
              sub={m.usage.input_tokens + m.usage.output_tokens ? `${num(m.usage.input_tokens)} in / ${num(m.usage.output_tokens)} out tokens (estimated cost)` : 'No LLM calls yet'}
            />
            <Kpi
              label="User feedback"
              value={m.feedback.helpful + m.feedback.not_helpful ? `${m.feedback.helpful} 👍 / ${m.feedback.not_helpful} 👎` : '—'}
              sub={m.feedback.rate_helpful === null ? 'No ratings yet' : `${pct(m.feedback.rate_helpful)} helpful`}
            />
          </div>

          <div className="detail-grid">
            <div className="glass-panel panel stack" style={{ gap: '0.7rem' }}>
              <h2 className="section-title">Outcomes and reasons</h2>
              <div className="outcome-bar" role="img" aria-label={`Success ${pct(m.outcomes.success.rate)}, partial ${pct(m.outcomes.partial.rate)}, failed ${pct(m.outcomes.failed.rate)}`}>
                <div style={{ width: `${(m.outcomes.success.rate || 0) * 100}%`, background: 'var(--success)' }} />
                <div style={{ width: `${(m.outcomes.partial.rate || 0) * 100}%`, background: 'var(--warning)' }} />
                <div style={{ width: `${(m.outcomes.failed.rate || 0) * 100}%`, background: 'var(--danger)' }} />
              </div>
              <div className="row-wrap" style={{ fontSize: '0.8rem' }}>
                {Object.entries({ ...m.reason_codes, ...m.flags }).map(([code, n]) => (
                  <span key={code} className="badge badge-muted mono" title={REASONS[code] || code}>{code} · {n}</span>
                ))}
              </div>
            </div>
            <div className="glass-panel panel">
              <h2 className="section-title">Stage latency (ms)</h2>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={latencyData}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="stage" stroke="#a0a6b5" tick={{ fontSize: 12 }} />
                  <YAxis stroke="#a0a6b5" tick={{ fontSize: 12 }} width={48} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="p50" fill={SERIES_COLORS[0]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  <Bar dataKey="p95" fill={SERIES_COLORS[2]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            {configData.length > 0 && (
              <div className="glass-panel panel">
                <h2 className="section-title">By configuration</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={configData}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                    <XAxis dataKey="config" stroke="#a0a6b5" tick={{ fontSize: 12 }} />
                    <YAxis yAxisId="l" stroke="#a0a6b5" tick={{ fontSize: 12 }} width={40} unit="%" />
                    <YAxis yAxisId="r" orientation="right" stroke="#a0a6b5" tick={{ fontSize: 12 }} width={48} unit="ms" />
                    <Tooltip contentStyle={tooltipStyle} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar yAxisId="l" dataKey="success" name="Success %" fill={SERIES_COLORS[1]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                    <Bar yAxisId="r" dataKey="latency" name="p50 latency (ms)" fill={SERIES_COLORS[0]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </>
      )}

      <div className="glass-panel panel">
        <h2 className="section-title">Recent queries ({rows.length})</h2>
        {rows.length === 0 ? <p className="muted">No queries yet.</p> : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Time</th><th>Question</th><th>Outcome</th><th>Latency</th><th>Grounding</th><th>Feedback</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.query_id}>
                    <td className="mono nowrap">{new Date(r.timestamp).toLocaleTimeString()}</td>
                    <td style={{ minWidth: 240 }}>
                      <Link className="text-accent" href={`/observability/${r.query_id}`}>{r.query}</Link>
                      <div className="muted" style={{ fontSize: '0.78rem' }}>
                        {r.username || 'system'} · config {r.config_id}{r.eval_run_id ? ' · eval' : ''}{r.safety_events ? ` · ⚠ ${r.safety_events} safety` : ''}
                      </div>
                    </td>
                    <td><OutcomeBadge outcome={r.outcome} /><div className="muted mono" style={{ fontSize: '0.72rem' }}>{r.reason_codes.filter((c) => c !== 'OK').join(', ')}</div></td>
                    <td className="mono">{ms(r.total_ms)}</td>
                    <td>{pct(r.grounding_score)}</td>
                    <td>{r.feedback ? (r.feedback.helpful ? '👍' : '👎') : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
