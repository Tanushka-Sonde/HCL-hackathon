'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { OutcomeBadge, ReasonBadges } from '@/components/kis/Badges';
import { kis, ms, pct, type Filters, type Metrics, type QueryEvent, type QuerySummary } from '@/lib/kis';

function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="glass-panel kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value" style={tone ? { color: tone } : undefined}>{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

const EVAL_ROWS: [string, string, 'pct' | 'num' | 'ms'][] = [
  ['behavior_pass_rate', 'Expected behaviour pass', 'pct'],
  ['retrieval_hit_rate', 'Retrieval hit (expected docs)', 'pct'],
  ['answer_criteria_rate', 'Answer criteria met', 'pct'],
  ['avg_grounding', 'Avg grounding score', 'pct'],
  ['citation_valid_rate', 'Citations valid', 'pct'],
  ['success_rate', 'Outcome = Success', 'pct'],
  ['p50_latency_ms', 'Median latency', 'ms'],
  ['total_tokens', 'LLM tokens', 'num'],
  ['estimated_cost_usd', 'Est. cost (USD)', 'num'],
];

export default function ObservabilityPage() {
  const router = useRouter();
  const [filters, setFilters] = useState<Filters>({ include_eval: true });
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [rows, setRows] = useState<QuerySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [evalState, setEvalState] = useState<QueryEvent>({ status: 'idle' });

  const load = useCallback(
    () =>
      Promise.all([kis.metrics(filters), kis.queries(filters, 100)])
        .then(([m, q]) => {
          setMetrics(m);
          setRows(q);
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
    kis.evalStatus().then(setEvalState).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (evalState.status !== 'running') return;
    const t = setInterval(async () => {
      const s = await kis.evalStatus().catch(() => null);
      if (s) {
        setEvalState(s);
        if (s.status !== 'running') load();
      }
    }, 3000);
    return () => clearInterval(t);
  }, [evalState.status, load]);

  const startEval = async () => {
    try {
      await kis.startEval(['A', 'B']);
      setEvalState({ status: 'running' });
    } catch (err) {
      setEvalState({ status: 'failed', error: err instanceof Error ? err.message : 'failed to start' });
    }
  };

  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }));
  const m = metrics;
  const total = m?.total_queries || 0;

  return (
    <div className="animate-fade-in stack">
      <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: '1.9rem', marginBottom: '0.25rem' }}>AI Observability &amp; Evaluation</h1>
          <p className="text-secondary" style={{ fontSize: '0.9rem' }}>
            Every KPI is computed from logged query events. HTTP 200 is counted separately from AI-quality outcome.
          </p>
        </div>
        <div className="row-wrap">
          <select className="select" value={filters.config_id || ''} onChange={(e) => set({ config_id: e.target.value || undefined })} aria-label="Configuration">
            <option value="">All configs</option>
            <option value="A">Config A (vector)</option>
            <option value="B">Config B (hybrid+rerank)</option>
          </select>
          <select className="select" value={filters.outcome || ''} onChange={(e) => set({ outcome: e.target.value || undefined })} aria-label="Outcome">
            <option value="">All outcomes</option>
            <option value="success">Success</option>
            <option value="partial">Partial / Fallback</option>
            <option value="failed">Failed</option>
          </select>
          <select className="select" value={filters.since_hours || ''} onChange={(e) => set({ since_hours: e.target.value || undefined })} aria-label="Time window">
            <option value="">All time</option>
            <option value="1">Last hour</option>
            <option value="24">Last 24 h</option>
            <option value="168">Last 7 days</option>
          </select>
          <label className="row-wrap text-secondary" style={{ fontSize: '0.85rem', gap: '0.3rem' }}>
            <input type="checkbox" style={{ width: 'auto' }} checked={filters.include_eval !== false} onChange={(e) => set({ include_eval: e.target.checked })} />
            include eval runs
          </label>
          <button className="btn btn-secondary btn-sm" onClick={load}>Refresh</button>
        </div>
      </div>

      {error && <div className="banner banner-danger">{error}. Is the backend running?</div>}
      {loading && <p className="muted animate-pulse">Loading metrics…</p>}

      {m && total === 0 && !loading && (
        <div className="glass-panel panel text-center">
          <p className="text-secondary">No query events match these filters yet. Ask something in the Assistant or run the evaluation below.</p>
        </div>
      )}

      {m && total > 0 && (
        <>
          <div className="kpi-grid">
            <Kpi label="Total queries" value={total} sub={`HTTP 200: ${m.execution.http_ok} · stage errors: ${m.execution.stage_errors}`} />
            <Kpi label="Success" value={m.outcomes.success.count} sub={pct(m.outcomes.success.rate)} tone="var(--success)" />
            <Kpi label="Partial / Fallback" value={m.outcomes.partial.count} sub={pct(m.outcomes.partial.rate)} tone="var(--warning)" />
            <Kpi label="Failed" value={m.outcomes.failed.count} sub={pct(m.outcomes.failed.rate)} tone="var(--danger)" />
            <Kpi label="Retrieval success" value={pct(m.retrieval_success.rate)} sub={`${m.retrieval_success.count}/${m.retrieval_success.of} found relevant evidence`} />
            <Kpi label="Grounding rate" value={pct(m.grounding_rate.rate)} sub={`${m.grounding_rate.count}/${m.grounding_rate.of} answers with claims ≥ threshold`} />
            <Kpi label="Citation support" value={pct(m.citation_support.rate)} sub={`${m.citation_support.count}/${m.citation_support.of} answers with all-valid citations`} />
            <Kpi label="Tool success" value={pct(m.tool_success.rate)} sub={`${m.tool_success.count}/${m.tool_success.of} SQL executions`} />
            <Kpi
              label="Safety events"
              value={m.safety_events.queries_with_events}
              sub={`query inj. ${m.safety_events.query_injection} · doc inj. ${m.safety_events.embedded_injection} · PII ${m.safety_events.pii_redaction}`}
            />
            <Kpi label="Latency total" value={ms(m.latency_ms.total.p50)} sub={`p50 · p95 ${ms(m.latency_ms.total.p95)}`} />
            <Kpi label="Latency stages (p50)" value={ms(m.latency_ms.retrieval.p50)} sub={`retrieval · LLM ${ms(m.latency_ms.llm.p50)} · tool ${ms(m.latency_ms.tool.p50)}`} />
            <Kpi
              label="Usage & cost"
              value={`$${m.usage.estimated_cost_usd.toFixed(4)}`}
              sub={`${m.usage.input_tokens.toLocaleString()} in / ${m.usage.output_tokens.toLocaleString()} out tokens`}
            />
            <Kpi
              label="User feedback"
              value={`${m.feedback.helpful} 👍 / ${m.feedback.not_helpful} 👎`}
              sub={m.feedback.rate_helpful === null ? 'no ratings yet' : `${pct(m.feedback.rate_helpful)} helpful`}
            />
          </div>

          <div className="detail-grid">
            <div className="glass-panel panel stack" style={{ gap: '0.7rem' }}>
              <h2 className="section-title">Outcome distribution</h2>
              <div className="outcome-bar" aria-label="Outcome distribution">
                <div style={{ width: `${(m.outcomes.success.rate || 0) * 100}%`, background: 'var(--success)' }} title="Success" />
                <div style={{ width: `${(m.outcomes.partial.rate || 0) * 100}%`, background: 'var(--warning)' }} title="Partial" />
                <div style={{ width: `${(m.outcomes.failed.rate || 0) * 100}%`, background: 'var(--danger)' }} title="Failed" />
              </div>
              <div className="row-wrap" style={{ fontSize: '0.8rem' }}>
                {Object.entries(m.reason_codes).map(([code, n]) => (
                  <span key={code} className="badge badge-muted mono">{code} · {n}</span>
                ))}
                {Object.entries(m.flags).map(([code, n]) => (
                  <span key={code} className="badge badge-info mono">{code} · {n}</span>
                ))}
              </div>
            </div>
            <div className="glass-panel panel">
              <h2 className="section-title">By configuration</h2>
              <table className="data-table">
                <thead><tr><th>Config</th><th>Queries</th><th>Success rate</th><th>p50 latency</th></tr></thead>
                <tbody>
                  {Object.entries(m.by_config).map(([cfg, v]) => (
                    <tr key={cfg}><td>{cfg === 'A' ? 'A · vector only' : 'B · hybrid + rerank'}</td><td>{v.total}</td><td>{pct(v.success_rate)}</td><td>{ms(v.p50_total_ms)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      <div className="glass-panel panel">
        <div className="row-wrap" style={{ justifyContent: 'space-between', marginBottom: '0.8rem' }}>
          <h2 className="section-title" style={{ margin: 0 }}>Evaluation: configuration A vs B</h2>
          <button className="btn btn-primary btn-sm" onClick={startEval} disabled={evalState.status === 'running'}>
            {evalState.status === 'running' ? 'Running…' : 'Run evaluation set'}
          </button>
        </div>
        <p className="muted" style={{ fontSize: '0.82rem', marginBottom: '0.8rem' }}>
          16 fixed cases (<span className="mono">demo/eval/eval_set.json</span>) covering direct facts, exact IDs, follow-ups, SQL, combined questions,
          insufficient evidence, conflicts, prompt injection and tool failure. The report is written to <span className="mono">reports/evaluation_report.md</span>.
        </p>
        {evalState.status === 'running' && <p className="animate-pulse text-secondary">Running the evaluation… each case is logged as a query event.</p>}
        {evalState.status === 'failed' && <div className="banner banner-danger">Evaluation failed: {evalState.error}</div>}
        {evalState.status === 'completed' && evalState.result && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>Metric</th>{Object.keys(evalState.result.configs).map((c) => <th key={c}>Config {c}</th>)}</tr>
              </thead>
              <tbody>
                {EVAL_ROWS.map(([key, label, kind]) => (
                  <tr key={key}>
                    <td>{label}</td>
                    {Object.entries(evalState.result.configs).map(([c, data]) => {
                      const v = (data as QueryEvent).summary[key];
                      return <td key={c}>{kind === 'pct' ? pct(v) : kind === 'ms' ? ms(v) : v ?? '—'}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: '0.8rem', marginTop: '0.5rem' }}>Finished {evalState.finished_at}. Generator: {evalState.result.llm}.</p>
          </div>
        )}
      </div>

      <div className="glass-panel panel">
        <h2 className="section-title">Recent queries ({rows.length})</h2>
        {rows.length === 0 ? (
          <p className="muted">No queries yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th><th>Question</th><th>Cfg</th><th>Route</th><th>Outcome</th><th>Latency</th>
                  <th>Sources</th><th>Citations</th><th>Grounding</th><th>Tool</th><th>Safety</th><th>Feedback</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.query_id} className="clickable" onClick={() => router.push(`/observability/${r.query_id}`)}>
                    <td className="mono" style={{ whiteSpace: 'nowrap' }}>{new Date(r.timestamp).toLocaleTimeString()}</td>
                    <td style={{ minWidth: 220 }}>
                      {r.query}
                      {r.eval_run_id && <div><span className="badge badge-muted">eval</span></div>}
                    </td>
                    <td>{r.config_id}</td>
                    <td>{r.route}</td>
                    <td>
                      <div className="row-wrap" style={{ gap: '0.25rem' }}>
                        <OutcomeBadge outcome={r.outcome} />
                        <ReasonBadges reasons={r.reason_codes} />
                      </div>
                    </td>
                    <td className="mono">{ms(r.total_ms)}</td>
                    <td style={{ fontSize: '0.78rem' }}>{r.sources.join(', ') || '—'}</td>
                    <td>{r.citations === 0 ? '—' : r.citations_valid ? `✓ ${r.citations}` : `✗ ${r.citations}`}</td>
                    <td>{pct(r.grounding_score)}</td>
                    <td>{r.tool_status || '—'}</td>
                    <td>{r.safety_events ? `⚠ ${r.safety_events}` : '—'}</td>
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
