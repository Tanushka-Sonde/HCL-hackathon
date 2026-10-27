'use client';

import { Fragment, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { OutcomeBadge, ReasonBadges, StatusDot } from '@/components/kis/Badges';
import { kis, ms, pct, type QueryEvent } from '@/lib/kis';

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
        <div className="answer-text" style={{ fontSize: '0.95rem' }}>{generation.output}</div>
      </div>

      <div className="detail-grid">
        <Section title="Identity">
          <dl className="kv">
            <dt>Query ID</dt><dd className="mono">{identity.query_id}</dd>
            <dt>Timestamp</dt><dd>{new Date(identity.timestamp).toLocaleString()}</dd>
            <dt>Session ID</dt><dd className="mono">{identity.session_id}</dd>
            <dt>App version</dt><dd>{identity.app_version}</dd>
            <dt>Configuration</dt><dd className="mono">{identity.config_label}</dd>
            <dt>Correlation ID</dt><dd className="mono">{identity.correlation_id}</dd>
          </dl>
        </Section>

        <Section title="Question & routing">
          <dl className="kv">
            <dt>Original</dt><dd>{question.original}</dd>
            <dt>Normalized</dt><dd>{question.normalized}</dd>
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
            <dt>Context</dt><dd>{ms(performance.context_ms)}</dd>
            <dt>Retrieval</dt><dd>{ms(performance.retrieval_ms)}</dd>
            <dt>Tool</dt><dd>{ms(performance.tool_ms)}</dd>
            <dt>LLM</dt><dd>{ms(performance.llm_ms)}</dd>
            <dt>Validation</dt><dd>{ms(performance.validation_ms)}</dd>
            <dt>Tokens in / out</dt><dd>{usage.input_tokens} / {usage.output_tokens}</dd>
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
                    <td>{r.version} <span className="muted">{r.status}</span></td>
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
        </Section>

        <Section title="Safety">
          <dl className="kv">
            <dt>Query injection</dt><dd>{safety.query_injection.length ? safety.query_injection.join(', ') : 'none'}</dd>
            <dt>Blocked</dt><dd>{safety.injection_blocked ? 'yes' : 'no'}</dd>
            <dt>Embedded injection</dt><dd>{safety.chunk_injections.length ? `${safety.chunk_injections.length} chunk(s)` : 'none'}</dd>
            <dt>PII redactions</dt><dd>{Object.keys(safety.pii_redactions).length ? JSON.stringify(safety.pii_redactions) : 'none'}</dd>
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
              <dt>Retried</dt><dd>{e.retried ? 'yes' : 'no'}</dd>
              <dt>Correlation</dt><dd className="mono">{e.correlation_id}</dd>
            </dl>
          ))}
          {event.tool_calls.some((t: QueryEvent) => t.status === 'error') && event.errors.length === 0 && (
            <p className="muted" style={{ fontSize: '0.85rem' }}>The tool failure was handled as a controlled error (see Tool calls).</p>
          )}
        </Section>
      </div>

      <Section title={`Evidence sent to the model (${evidence.length})`}>
        <div className="stack" style={{ gap: '0.6rem' }}>
          {evidence.map((ev) => (
            <div key={ev.source_id} className="evidence-box">
              <div className="row-wrap" style={{ marginBottom: '0.3rem' }}>
                <strong>{ev.source_id}</strong> {ev.filename} · {ev.doc_id} v{ev.version} ({ev.status}){ev.page ? ` · p.${ev.page}` : ''}{ev.section ? ` · ${ev.section}` : ''}
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
