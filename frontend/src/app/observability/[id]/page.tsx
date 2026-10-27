'use client';

import { Fragment, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { OutcomeBadge, ReasonBadges, StatusDot } from '@/components/kis/Badges';
import { AssetImage, ChartView } from '@/components/kis/ChartView';
import { RequireAuth, usePageTitle } from '@/lib/auth';
import { kis, ms, pct, REASONS, type QueryEvent } from '@/lib/kis';

const STAGE_COLORS: Record<string, string> = {
  vision_ms: '#f472b6',
  context_ms: '#a0a6b5',
  retrieval_ms: '#818cf8',
  tool_ms: '#34d399',
  llm_ms: '#fbbf24',
  validation_ms: '#60a5fa',
};

/** Why this query got its outcome, in one sentence. */
function outcomeSummary(event: QueryEvent): string {
  const { status, reason_codes } = event.outcome;
  const reasons = reason_codes.filter((r: string) => r !== 'OK').map((r: string) => REASONS[r] || r);
  const sources = new Set((event.citations || []).filter((c: QueryEvent) => c.valid).map((c: QueryEvent) => c.source_id)).size;
  const base = `${sources} valid source${sources === 1 ? '' : 's'} cited, grounding ${pct(event.grounding.score)}`;
  if (status === 'success') return `Success: ${base}.`;
  return `${status === 'failed' ? 'Failed' : 'Partial'} because: ${reasons.join('; ')}. (${base}.)`;
}

function StageTimeline({ perf }: { perf: QueryEvent }) {
  const stages = Object.keys(STAGE_COLORS).filter((k) => (perf[k] || 0) > 0);
  const total = stages.reduce((n, k) => n + perf[k], 0) || 1;
  return (
    <div>
      <div className="timeline" role="img" aria-label={stages.map((k) => `${k.replace('_ms', '')} ${Math.round(perf[k])} ms`).join(', ')}>
        {stages.map((k) => <div key={k} style={{ width: `${(perf[k] / total) * 100}%`, background: STAGE_COLORS[k] }} title={`${k.replace('_ms', '')}: ${ms(perf[k])}`} />)}
      </div>
      <div className="row-wrap" style={{ fontSize: '0.78rem', marginTop: '0.4rem' }}>
        {stages.map((k) => (
          <span key={k}><span className="legend-dot" style={{ background: STAGE_COLORS[k] }} /> {k.replace('_ms', '')} {ms(perf[k])}</span>
        ))}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="glass-panel panel">
      <h2 className="section-title">{title}</h2>
      {children}
    </section>
  );
}

const fmt = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(4)) : String(v));

export default function QueryDetailPage() {
  return (
    <RequireAuth role="admin">
      <QueryDetail />
    </RequireAuth>
  );
}

function QueryDetail() {
  usePageTitle('Query trace');
  const params = useParams<{ id: string }>();
  const [event, setEvent] = useState<QueryEvent | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!params?.id) return;
    kis.query_event(params.id).then(setEvent).catch((err) => setError(err instanceof Error ? err.message : 'Not found'));
  }, [params?.id]);

  if (error) {
    return (
      <div className="stack">
        <Link href="/observability" className="text-accent">← Back to dashboard</Link>
        <div className="banner banner-danger">{error}</div>
      </div>
    );
  }
  if (!event) return <p className="muted animate-pulse">Loading query trace…</p>;

  const { identity, question, execution, outcome, evidence_quality, context, generation, grounding, safety, performance, usage } = event;
  const retrieval: QueryEvent[] = event.retrieval || [];
  const evidence: QueryEvent[] = event.evidence || [];

  return (
    <div className="animate-fade-in stack">
      <Link href="/observability" className="text-accent" style={{ fontSize: '0.9rem' }}>← Back to dashboard</Link>

      <div className="glass-panel panel stack" style={{ gap: '0.6rem' }}>
        <div className="row-wrap">
          <OutcomeBadge outcome={outcome.status} />
          <ReasonBadges reasons={outcome.reason_codes} flags={outcome.flags} />
          <span className="badge badge-muted">confidence: {outcome.confidence}</span>
          {event.eval && <span className="badge badge-muted">eval {event.eval.run_id} · {event.eval.case_id}</span>}
        </div>
        <h1 style={{ fontSize: '1.4rem', margin: 0 }}>{question.original}</h1>
        <p className={`status-line status-${outcome.status === 'success' ? 'success' : outcome.status === 'failed' ? 'danger' : 'warn'}`}>
          <span className="status-dot" aria-hidden />{outcomeSummary(event)}
        </p>
        <div className="answer-text" style={{ fontSize: '0.95rem' }}>{generation.output}</div>
        <StageTimeline perf={performance} />
        {(event.visuals || []).map((v: QueryEvent, i: number) =>
          v.kind === 'retrieved_chart' ? (
            <div key={i} className="visual-box"><AssetImage url={v.asset_url} alt={v.title} /><p className="muted caption">Retrieved chart [{v.source_id}] · {v.doc} p.{v.page}</p></div>
          ) : (
            <div key={i} className="visual-box"><ChartView spec={v.spec} /><p className="muted caption">Generated from {v.source_ids.join(', ')}</p></div>
          ),
        )}
        {event.chart_rejection && <div className="banner banner-warn">Chart rejected: {event.chart_rejection.reason}{event.chart_rejection.values ? ` (${event.chart_rejection.values.join(', ')})` : ''}</div>}
      </div>

      <div className="detail-grid">
        <Section title="Identity">
          <dl className="kv">
            <dt>Query ID</dt><dd className="mono">{identity.query_id}</dd>
            <dt>Timestamp</dt><dd>{new Date(identity.timestamp).toLocaleString()}</dd>
            <dt>Session ID</dt><dd className="mono">{identity.session_id}</dd>
            <dt>User</dt><dd>{identity.username || '—'} <span className="muted">({identity.role || 'n/a'})</span></dd>
            <dt>App version</dt><dd>{identity.app_version}</dd>
            <dt>Configuration</dt><dd className="mono">{identity.config_label}</dd>
            <dt>Correlation ID</dt><dd className="mono">{identity.correlation_id}</dd>
          </dl>
        </Section>

        <Section title="Question & routing">
          <dl className="kv">
            <dt>Original</dt><dd>{question.original}</dd>
            <dt>Normalized</dt><dd>{question.normalized}</dd>
            {context.rewrite && context.rewrite.method !== 'none' && (<><dt>Follow-up rewrite</dt><dd>{context.rewrite.method}{context.rewrite.carried_terms?.length ? ` · carried: ${context.rewrite.carried_terms.join(', ')}` : ''}</dd></>)}
            <dt>Router decision</dt><dd><span className="badge badge-info">{question.route}</span></dd>
            <dt>Data signals</dt><dd className="mono">{question.data_signals.join(', ') || '—'}</dd>
            <dt>Doc signals</dt><dd className="mono">{question.doc_signals.join(', ') || '—'}</dd>
            {question.router_notes.length > 0 && (<><dt>Router notes</dt><dd>{question.router_notes.join('; ')}</dd></>)}
          </dl>
        </Section>

        <Section title="Execution status">
          <dl className="kv">
            <dt>HTTP status</dt><dd>{execution.http_status}</dd>
            {Object.entries(execution.stages).map(([stage, status]) => (
              <Fragment key={stage}><dt>{stage}</dt><dd><StatusDot status={status as string} /></dd></Fragment>
            ))}
          </dl>
        </Section>

        <Section title="Performance & usage">
          <dl className="kv">
            <dt>End-to-end</dt><dd><strong>{ms(performance.total_ms)}</strong></dd>
            {performance.vision_ms > 0 && (<><dt>Vision (image)</dt><dd>{ms(performance.vision_ms)}</dd></>)}
            <dt>Context</dt><dd>{ms(performance.context_ms)}</dd>
            <dt>Retrieval</dt><dd>{ms(performance.retrieval_ms)}</dd>
            <dt>Tool</dt><dd>{ms(performance.tool_ms)}</dd>
            <dt>LLM</dt><dd>{ms(performance.llm_ms)}</dd>
            <dt>Validation</dt><dd>{ms(performance.validation_ms)}</dd>
            <dt>Tokens in / out</dt><dd>{usage.input_tokens} / {usage.output_tokens}</dd>
            {usage.by_stage && Object.entries(usage.by_stage).filter(([, v]) => (v as QueryEvent).input_tokens || (v as QueryEvent).output_tokens).map(([k, v]) => (
              <Fragment key={k}><dt className="muted">· {k.replace('_', ' ')}</dt><dd>{(v as QueryEvent).input_tokens} / {(v as QueryEvent).output_tokens}</dd></Fragment>
            ))}
            {usage.budget && (<><dt>Budget</dt><dd>{usage.budget.max_input} in (est. used {usage.estimated_input_tokens}) / {usage.budget.max_output} out</dd></>)}
            {usage.evidence_dropped_for_budget?.count > 0 && (<><dt>Dropped for budget</dt><dd className="mono">{usage.evidence_dropped_for_budget.source_ids.join(', ')}</dd></>)}
            {usage.truncated_source && (<><dt>Truncated</dt><dd className="mono">{usage.truncated_source}</dd></>)}
            <dt>Cached tokens</dt><dd>{usage.cached_tokens ?? 'n/a'}</dd>
            <dt>Est. cost</dt><dd>${usage.estimated_cost_usd.toFixed(6)}</dd>
          </dl>
        </Section>
      </div>

      <Section title={`Retrieval candidates (${retrieval.length})`}>
        <p className="muted" style={{ fontSize: '0.8rem', marginBottom: '0.6rem' }}>
          Evidence found: <strong>{evidence_quality.evidence_found ? 'yes' : 'no'}</strong> · top relevance {fmt(evidence_quality.top_relevance)} (threshold {evidence_quality.threshold})
          {evidence_quality.expected_match !== null && evidence_quality.expected_match !== undefined && (
            <> · expected evidence match: <strong>{evidence_quality.expected_match ? 'yes' : 'no'}</strong></>
          )}
        </p>
        {retrieval.length === 0 ? <p className="muted">Retrieval did not run for this query.</p> : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>Sel.</th><th>Document</th><th>Ver.</th><th>Page / section</th><th>Vector (rank)</th><th>BM25 (rank)</th><th>Fused (rank)</th><th>Rerank</th><th>Relevance</th><th>Chunk ID</th></tr>
              </thead>
              <tbody>
                {retrieval.map((r) => (
                  <tr key={r.chunk_id}>
                    <td>{r.selected ? '✓' : ''}</td>
                    <td>{r.filename}<div className="muted mono">{r.doc_id}</div></td>
                    <td>{r.version ? `v${r.version}` : '—'} <span className="muted">{r.status || ''}</span></td>
                    <td>{r.page ? `p.${r.page}` : ''} {r.section || ''}</td>
                    <td className="mono">{fmt(r.vector_score)} ({fmt(r.vector_rank)})</td>
                    <td className="mono">{fmt(r.bm25_score)} ({fmt(r.bm25_rank)})</td>
                    <td className="mono">{fmt(r.fused_score)} ({fmt(r.fused_rank)})</td>
                    <td className="mono">{fmt(r.rerank_score)}</td>
                    <td className="mono">{fmt(r.relevance)}</td>
                    <td className="mono muted">{String(r.chunk_id).slice(0, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <div className="detail-grid">
        <Section title="Citations">
          {event.citations.length === 0 ? <p className="muted">No citations in the answer.</p> : (
            <table className="data-table">
              <thead><tr><th>Tag</th><th>Maps to evidence</th><th>Target</th></tr></thead>
              <tbody>
                {event.citations.map((c: QueryEvent) => (
                  <tr key={c.source_id}>
                    <td className="mono">{c.source_id}</td>
                    <td>{c.valid ? <span className="badge badge-success">valid</span> : <span className="badge badge-danger">invalid</span>}</td>
                    <td>{c.target || '—'}{c.page ? ` · p.${c.page}` : ''}{c.section ? ` · ${c.section}` : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {event.conflicts.length > 0 && <div className="banner banner-warn" style={{ marginTop: '0.8rem' }}>{event.conflicts.join(' ')}</div>}
          {(event.calculations || []).length > 0 && (
            <div style={{ marginTop: '0.8rem' }}>
              <strong style={{ fontSize: '0.85rem' }}>Calculations</strong>
              {event.calculations.map((c: QueryEvent, i: number) => (
                <p key={i} className="mono" style={{ fontSize: '0.82rem' }}>{c.expr} = {c.result ?? `error: ${c.error}`}</p>
              ))}
            </div>
          )}
        </Section>

        <Section title="Grounding">
          <p style={{ marginBottom: '0.5rem' }}>
            Score: <strong>{pct(grounding.score)}</strong> ({grounding.claims} claims) <span className="muted" style={{ fontSize: '0.8rem' }}>· rule: {grounding.rule}</span>
          </p>
          {grounding.supported.map((s: string, i: number) => <p key={`s${i}`} style={{ fontSize: '0.85rem' }}>✓ {s}</p>)}
          {grounding.unsupported.map((u: QueryEvent, i: number) => (
            <p key={`u${i}`} style={{ fontSize: '0.85rem', color: 'var(--warning)' }}>✗ {u.claim} <span className="muted">({u.reason})</span></p>
          ))}
        </Section>

        <Section title="Generation">
          <dl className="kv">
            <dt>Provider</dt><dd>{generation.provider || 'none (skipped)'}</dd>
            <dt>Model</dt><dd className="mono">{generation.model || '—'}</dd>
            <dt>Prompt template</dt><dd className="mono">{generation.prompt_template_version}</dd>
            <dt>Status</dt><dd><StatusDot status={generation.status} /></dd>
            {generation.error && (<><dt>LLM error</dt><dd className="mono">{generation.error}</dd></>)}
          </dl>
          {generation.prompt && (
            <details style={{ marginTop: '0.6rem' }}>
              <summary className="text-accent" style={{ cursor: 'pointer', fontSize: '0.85rem' }}>Prompt sent to the model</summary>
              <pre className="prompt-box">{generation.prompt.system}{'\n\n---\n\n'}{generation.prompt.user}</pre>
            </details>
          )}
        </Section>

        <Section title="Safety">
          <dl className="kv">
            <dt>Query injection</dt><dd>{safety.query_injection.length ? safety.query_injection.join(', ') : 'none'}</dd>
            <dt>Blocked</dt><dd>{safety.injection_blocked ? 'yes' : 'no'}</dd>
            <dt>Embedded injection</dt><dd>{safety.chunk_injections.length ? `${safety.chunk_injections.length} chunk(s)` : 'none'}</dd>
            <dt>Masked for user</dt><dd>{event.masking?.applied ? (Object.keys(event.masking.counts).length ? JSON.stringify(event.masking.counts) : 'nothing to mask') : 'no (admin view)'}</dd>
            <dt>PII detected</dt><dd className="mono">{safety.pii_detected ? Object.entries(safety.pii_detected).filter(([, v]) => Object.keys(v as object).length).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(' · ') || 'none' : (safety.pii_redactions ? JSON.stringify(safety.pii_redactions) : 'none')}</dd>
            <dt>Fallback</dt><dd>{safety.fallback ? 'yes' : 'no'}</dd>
          </dl>
          {safety.chunk_injections.map((ci: QueryEvent) => (
            <div key={ci.chunk_id} className="evidence-box" style={{ marginTop: '0.6rem' }}>
              <strong>{ci.filename}</strong> · patterns {ci.patterns.join(', ')} · {ci.action}
              {ci.removed_text.map((t: string, i: number) => <div key={i} className="muted">removed: “{t}”</div>)}
            </div>
          ))}
        </Section>

        <Section title="Tool calls">
          {event.tool_calls.length === 0 ? <p className="muted">No tool used.</p> : event.tool_calls.map((tc: QueryEvent) => (
            <dl key={tc.source_id} className="kv">
              <dt>Tool</dt><dd className="mono">{tc.name}.{tc.template} [{tc.source_id}]</dd>
              <dt>Sanitized inputs</dt><dd className="mono">{JSON.stringify(tc.params)}</dd>
              <dt>Status</dt><dd><StatusDot status={tc.status} />{tc.simulated_failure && <span className="muted"> (simulated failure)</span>}</dd>
              <dt>Result</dt><dd>{tc.result_summary}</dd>
              <dt>Rows</dt><dd>{tc.row_count}</dd>
              <dt>Latency</dt><dd>{ms(tc.latency_ms)}</dd>
              {tc.error && (<><dt>Error</dt><dd className="mono">{tc.error}</dd></>)}
            </dl>
          ))}
        </Section>

        <Section title="Conversation context">
          <p style={{ fontSize: '0.85rem', marginBottom: '0.4rem' }}>Prior turns available: {context.history_turns_available} · selected: {context.selected_turns.length}</p>
          {context.selected_turns.map((t: QueryEvent) => (
            <p key={t.query_id} style={{ fontSize: '0.85rem' }}>
              ↳ <Link className="text-accent" href={`/observability/${t.query_id}`}>{t.query}</Link>
            </p>
          ))}
        </Section>

        <Section title="Feedback">
          {event.feedback ? (
            <p>{event.feedback.helpful ? '👍 Helpful' : '👎 Not helpful'}{event.feedback.comment && <> — “{event.feedback.comment}”</>}</p>
          ) : <p className="muted">No feedback yet.</p>}
        </Section>

        <Section title="Errors">
          {event.errors.length === 0 ? <p className="muted">No errors.</p> : event.errors.map((e: QueryEvent, i: number) => (
            <dl key={i} className="kv">
              <dt>Stage</dt><dd>{e.stage}</dd>
              <dt>Category</dt><dd className="mono">{e.category}</dd>
              <dt>Message</dt><dd className="mono">{e.message}</dd>
              <dt>Correlation</dt><dd className="mono">{e.correlation_id}</dd>
            </dl>
          ))}
          {event.tool_calls.some((t: QueryEvent) => t.status === 'error') && event.errors.length === 0 && (
            <p className="muted" style={{ fontSize: '0.85rem' }}>The tool failure was handled as a controlled error (see Tool calls).</p>
          )}
        </Section>
      </div>

      {event.image_input && (
        <Section title="Image attached to the question [U1]">
          <dl className="kv">
            <dt>Vision model</dt><dd className="mono">{event.image_input.model}</dd>
            <dt>Size</dt><dd>{(event.image_input.size_bytes / 1024).toFixed(0)} KB · {ms(event.image_input.latency_ms)}</dd>
            <dt>Stored</dt><dd>{event.image_input.stored_path ? <span className="mono">{event.image_input.stored_path}</span> : 'no (description only)'}</dd>
            {event.image_input.removed_instructions?.length > 0 && (<><dt>Instructions removed</dt><dd>{event.image_input.removed_instructions.join(' · ')}</dd></>)}
          </dl>
          <div className="evidence-box" style={{ marginTop: '0.6rem' }}>{event.image_input.description}</div>
        </Section>
      )}

      <Section title={`Evidence sent to the model (${evidence.length})`}>
        <div className="stack" style={{ gap: '0.6rem' }}>
          {evidence.map((ev) => (
            <div key={ev.source_id} className="evidence-box">
              <div className="row-wrap" style={{ marginBottom: '0.3rem' }}>
                <strong>{ev.source_id}</strong> {ev.filename} · {ev.doc_id}{ev.version ? ` v${ev.version}` : ''}{ev.status ? ` (${ev.status})` : ''}{ev.page ? ` · p.${ev.page}` : ''}{ev.section ? ` · ${ev.section}` : ''}
                {ev.content_type && ev.content_type !== 'text' && <span className="badge badge-muted">{ev.content_type}</span>}
                <span className="muted">relevance {fmt(ev.relevance)}</span>
                {ev.injection_flag && <span className="badge badge-danger">instruction removed</span>}
              </div>
              {ev.content}
            </div>
          ))}
          {evidence.length === 0 && <p className="muted">None.</p>}
        </div>
      </Section>
    </div>
  );
}
