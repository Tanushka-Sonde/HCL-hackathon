'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { RequireAuth, usePageTitle } from '@/lib/auth';
import { kis, ms, pct, type QueryEvent } from '@/lib/kis';

type Kind = 'pct' | 'num' | 'ms' | 'score';
const ROWS: [string, string, Kind, boolean][] = [
  // key, label, format, higher is better
  ['behavior_pass_rate', 'Expected behaviour pass', 'pct', true],
  ['retrieval_hit_rate', 'Retrieval hit (expected docs in top k)', 'pct', true],
  ['hit_at_1', 'Hit@1 (expected doc ranked first)', 'pct', true],
  ['mrr_at_5', 'MRR@5', 'score', true],
  ['answer_criteria_rate', 'Answer criteria met', 'pct', true],
  ['avg_grounding', 'Average grounding', 'pct', true],
  ['citation_valid_rate', 'Citations valid (answered cases)', 'pct', true],
  ['judge_avg', 'LLM judge (1–5, model-graded)', 'score', true],
  ['success_rate', 'Outcome = Success', 'pct', true],
  ['p50_latency_ms', 'Median latency', 'ms', false],
  ['total_tokens', 'LLM tokens', 'num', false],
  ['estimated_cost_usd', 'Estimated cost (USD)', 'num', false],
];

function fmt(v: unknown, kind: Kind) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (kind === 'pct') return pct(n);
  if (kind === 'ms') return ms(n);
  if (kind === 'score') return n.toFixed(2);
  return n.toLocaleString();
}

export default function EvaluationPage() {
  return (
    <RequireAuth role="admin">
      <Evaluation />
    </RequireAuth>
  );
}

function Evaluation() {
  usePageTitle('Evaluation');
  const [state, setState] = useState<QueryEvent>({ status: 'idle' });

  const refresh = useCallback(() => kis.evalStatus().then(setState).catch(() => undefined), []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (state.status !== 'running') return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [state.status, refresh]);

  const start = async () => {
    try {
      await kis.startEval(['A', 'B', 'C']);
      setState({ status: 'running' });
    } catch (err) {
      setState({ status: 'failed', error: err instanceof Error ? err.message : 'failed to start' });
    }
  };

  const result = state.result;
  const cfgs: string[] = result ? Object.keys(result.configs) : [];
  const cases: QueryEvent[] = result ? result.configs[cfgs[0]].cases : [];

  return (
    <div className="animate-fade-in stack">
      <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
        <div>
          <h1 className="page-title">Evaluation: configuration comparison</h1>
          <p className="text-secondary" style={{ fontSize: '0.9rem' }}>
            A = vector only · B = hybrid (vector + BM25, RRF) + rerank · C = hybrid without rerank. Same fixed case set for each; every case is logged as a query you can open.
          </p>
        </div>
        <button className="btn btn-primary" onClick={start} disabled={state.status === 'running'}>
          {state.status === 'running' ? 'Running…' : 'Run evaluation set'}
        </button>
      </div>

      {state.status === 'running' && <div className="banner banner-info animate-pulse">Running the evaluation… this takes a few minutes with an LLM (rate-limit pauses between cases).</div>}
      {state.status === 'failed' && <div className="banner banner-danger" role="alert">Evaluation failed: {state.error}</div>}
      {state.status === 'idle' && !result && <div className="glass-panel panel"><p className="text-secondary">No evaluation has run since the server started. Run it to compare the configurations.</p></div>}

      {result && (
        <>
          <div className="glass-panel panel">
            <h2 className="section-title">Summary</h2>
            <p className="muted" style={{ fontSize: '0.82rem', marginBottom: '0.6rem' }}>
              {result.case_count ?? cases.length} cases · generator <span className="mono">{result.llm}</span> · finished {result.finished_at}
            </p>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr><th>Metric</th>{cfgs.map((c) => <th key={c}>Config {c}</th>)}{cfgs.includes('A') && cfgs.includes('B') && <th>B − A</th>}</tr>
                </thead>
                <tbody>
                  {ROWS.map(([key, label, kind, higherBetter]) => {
                    const a = result.configs.A?.summary[key];
                    const b = result.configs.B?.summary[key];
                    if (cfgs.every((c) => result.configs[c].summary[key] === undefined)) return null;
                    const delta = a !== null && a !== undefined && b !== null && b !== undefined ? Number(b) - Number(a) : null;
                    const good = delta !== null && delta !== 0 && delta > 0 === higherBetter;
                    return (
                      <tr key={key}>
                        <td>{label}</td>
                        {cfgs.map((c) => <td key={c}>{fmt(result.configs[c].summary[key], kind)}</td>)}
                        {cfgs.includes('A') && cfgs.includes('B') && (
                          <td style={{ color: delta === null || delta === 0 ? undefined : good ? 'var(--success)' : 'var(--danger)' }}>
                            {delta === null ? '—' : `${delta > 0 ? '+' : ''}${kind === 'pct' ? `${Math.round(delta * 100)} pts` : kind === 'ms' ? `${Math.round(delta)} ms` : delta.toFixed(2)}`}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {result.recommendation && (
              <div className="banner banner-info" style={{ marginTop: '0.8rem' }}>
                <strong>Recommendation: {result.recommendation.config}.</strong> {result.recommendation.why}
              </div>
            )}
          </div>

          <div className="glass-panel panel">
            <h2 className="section-title">Per case</h2>
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Case</th><th>Scenario</th>{cfgs.map((c) => <th key={c}>Config {c}</th>)}</tr></thead>
                <tbody>
                  {cases.map((row, i) => (
                    <tr key={row.case_id}>
                      <td className="mono">{row.case_id}</td>
                      <td>{row.scenario}</td>
                      {cfgs.map((c) => {
                        const r = result.configs[c].cases[i];
                        return (
                          <td key={c}>
                            <Link className="text-accent" href={`/observability/${r.query_id}`}>
                              {r.behavior_ok ? '✓ pass' : '✗ fail'}
                            </Link>
                            <div className="muted" style={{ fontSize: '0.75rem' }}>
                              {r.outcome}{r.rank ? ` · rank ${r.rank}` : r.retrieval_hit === false ? ' · miss' : ''}
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
