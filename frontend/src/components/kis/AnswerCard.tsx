'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { kis, ms, REASONS, type Evidence, type QueryResponse, type ToolCall } from '@/lib/kis';
import { AssetImage, ChartView } from './ChartView';

const TAG_RE = /\[((?:S|T|U)\d+)\]/g;
const CONFLICT_NOTE_RE = /^Note: sources disagree\..*$/m;

const TEMPLATE_LABELS: Record<string, string> = {
  project_budget: 'Project budget lookup',
  project_headcount: 'Project headcount lookup',
  department_spend: 'Department spend lookup',
  list_projects: 'Project list',
  vendor_invoices: 'Vendor invoice lookup',
};

function tokens(text: string): Set<string> {
  return new Set(text.toLowerCase().match(/[a-z0-9][a-z0-9-]{2,}/g) || []);
}

/** Readable source name: title, version and location instead of the file name. */
export function sourceLabel(e: Evidence): string {
  const where = e.page ? `p.${e.page}` : e.section || '';
  return [e.title, e.version ? `v${e.version}` : null, where].filter(Boolean).join(' · ');
}

/** One plain status line instead of a row of internal codes. */
function statusLine(resp: QueryResponse, docCount: number): { tone: string; text: string } {
  const notes: string[] = [];
  if (resp.flags.includes('CONFLICT_SURFACED')) notes.push('version conflict noted');
  if (resp.flags.includes('PII_MASKED')) notes.push('personal data masked');
  if (resp.flags.includes('EMBEDDED_INJECTION_REMOVED')) notes.push('hidden instructions ignored');
  const tail = notes.length ? ` · ${notes.join(' · ')}` : '';
  if (resp.outcome === 'success') {
    const what = docCount ? `${docCount} source${docCount > 1 ? 's' : ''}` : 'business data';
    return { tone: 'success', text: `Verified answer from ${what}${tail}` };
  }
  const main = resp.reason_codes[0];
  return {
    tone: resp.outcome === 'failed' ? 'danger' : 'warn',
    text: `${REASONS[main] || main}${tail}`,
  };
}

function renderAnswer(text: string, onCite: (id: string) => void, validIds: Set<string>) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(TAG_RE)) {
    const idx = match.index ?? 0;
    parts.push(text.slice(last, idx));
    const id = match[1];
    parts.push(
      <button
        key={`${id}-${idx}`}
        type="button"
        className={`chip chip-cite ${validIds.has(id) ? '' : 'invalid'}`}
        onClick={() => onCite(id)}
        title={validIds.has(id) ? 'Show the source' : 'This citation does not match a returned source'}
      >
        {id}
      </button>,
    );
    last = idx + match[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}

/** The source text with the sentence that best supports the answer highlighted. */
function HighlightedSource({ content, answer, id }: { content: string; answer: string; id: string }) {
  const claim = answer
    .split(/(?<=[.!?])\s+|\n/)
    .filter((s) => s.includes(`[${id}]`))
    .join(' ');
  const want = tokens(claim);
  const sentences = content.split(/(?<=[.!?])\s+|\n/);
  let best = -1;
  let bestScore = 1;
  sentences.forEach((s, i) => {
    const score = [...tokens(s)].filter((t) => want.has(t)).length;
    if (score > bestScore) {
      best = i;
      bestScore = score;
    }
  });
  return (
    <div className="source-text">
      {sentences.map((s, i) => (
        <span key={i}>{i === best ? <mark>{s}</mark> : s}{' '}</span>
      ))}
    </div>
  );
}

function ToolResult({ tool }: { tool: ToolCall }) {
  const label = TEMPLATE_LABELS[tool.template] || 'Business data lookup';
  const param = Object.values(tool.params).join(', ');
  if (tool.status !== 'success') {
    return (
      <div className={`banner ${tool.status === 'error' ? 'banner-danger' : 'banner-warn'}`}>
        <strong>{label}{param ? ` for ${param}` : ''}:</strong>{' '}
        {tool.status === 'error' ? tool.error || 'The data source could not be queried.' : tool.result_summary}
        {tool.simulated_failure && <span className="muted"> (simulated failure for the demo)</span>}
      </div>
    );
  }
  const cols = tool.rows.length ? Object.keys(tool.rows[0]) : [];
  return (
    <div className="tool-box">
      <div className="tool-head">
        <strong>[{tool.source_id}] {label}{param ? ` for ${param}` : ''}</strong>
        <span className="muted"> · {tool.row_count} row{tool.row_count === 1 ? '' : 's'} · {ms(tool.latency_ms)}</span>
      </div>
      {tool.rows.length > 0 && (
        <div className="table-wrap">
          <table className="data-table compact">
            <thead><tr>{cols.map((c) => <th key={c}>{c.replace(/_/g, ' ')}</th>)}</tr></thead>
            <tbody>
              {tool.rows.slice(0, 8).map((r, i) => (
                <tr key={i}>{cols.map((c) => <td key={c}>{typeof r[c] === 'number' ? (r[c] as number).toLocaleString() : String(r[c] ?? '')}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function AnswerCard({ resp, isAdmin }: { resp: QueryResponse; isAdmin: boolean }) {
  const [openSource, setOpenSource] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [rating, setRating] = useState<boolean | null>(null);
  const [comment, setComment] = useState('');
  const [fbState, setFbState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  const validIds = useMemo(() => new Set(resp.citations.filter((c) => c.valid).map((c) => c.source_id)), [resp]);
  const cited = resp.evidence.filter((e) => validIds.has(e.source_id));
  const shown = showAll ? resp.evidence : cited;
  const answer = resp.conflicts.length ? resp.answer.replace(CONFLICT_NOTE_RE, '').trim() : resp.answer;
  const status = statusLine(resp, new Set(cited.map((e) => e.doc_id)).size);
  const dataOnly = cited.length === 0 && resp.tool_calls.some((t) => validIds.has(t.source_id));

  const sendFeedback = async (helpful: boolean, text = comment) => {
    setRating(helpful);
    setFbState('saving');
    try {
      await kis.feedback(resp.query_id, helpful, text);
      setFbState('saved');
    } catch {
      setFbState('error');
    }
  };

  const openEv = resp.evidence.find((e) => e.source_id === openSource);
  const openTool = resp.tool_calls.find((t) => t.source_id === openSource);

  return (
    <article className="glass-panel chat-msg answer-card stack" aria-label="Assistant answer">
      <div className={`status-line status-${status.tone}`}>
        <span className="status-dot" aria-hidden />
        {status.text}
      </div>

      {resp.conflicts.length > 0 && (
        <div className="banner banner-warn"><strong>Sources disagree.</strong> {resp.conflicts.join(' ')}</div>
      )}

      <div className="answer-text">{renderAnswer(answer, setOpenSource, validIds)}</div>

      {resp.calculations.length > 0 && (
        <div className="calc-box">
          {resp.calculations.map((c, i) => (
            <div key={i} className="mono">
              {c.result ? <>= {c.result} <span className="muted">(calculated: {c.expr})</span></> : <span style={{ color: 'var(--danger)' }}>Could not calculate {c.expr}</span>}
            </div>
          ))}
        </div>
      )}

      {resp.visuals.map((v, i) =>
        v.kind === 'retrieved_chart' ? (
          <div key={i} className="visual-box">
            <AssetImage url={v.asset_url} alt={v.title} />
            <p className="muted caption">Original chart: {v.title} · {v.doc}{v.page ? `, page ${v.page}` : ''} <span className="chip chip-cite">{v.source_id}</span></p>
          </div>
        ) : (
          <div key={i} className="visual-box">
            <ChartView spec={v.spec} />
            <p className="muted caption">Generated from {v.source_ids.map((s) => `[${s}]`).join(' ')}. Every value is checked against the cited source.</p>
          </div>
        ),
      )}

      {openSource && (
        <div className="evidence-box" role="region" aria-label={`Source ${openSource}`}>
          <div className="row-wrap" style={{ marginBottom: '0.5rem' }}>
            <strong>{openSource}</strong>
            {openEv && <span>{sourceLabel(openEv)}{openEv.status ? ` (${openEv.status})` : ''}{openEv.source_method === 'vision_ocr' ? ' · read by OCR' : ''}</span>}
            {openTool && <span>Business database · {TEMPLATE_LABELS[openTool.template] || openTool.template}</span>}
            {openSource === 'U1' && <span>Your attached image</span>}
            {!openEv && !openTool && openSource !== 'U1' && <span style={{ color: 'var(--danger)' }}>Not a returned source (invalid citation)</span>}
            <button className="btn btn-secondary btn-sm" style={{ marginLeft: 'auto' }} onClick={() => setOpenSource(null)}>Close</button>
          </div>
          {openEv && <HighlightedSource content={openEv.content} answer={resp.answer} id={openSource} />}
          {openTool && <ToolResult tool={openTool} />}
        </div>
      )}

      {resp.tool_calls.filter((t) => t.status !== 'skipped').map((t) => <ToolResult key={t.source_id} tool={t} />)}

      {dataOnly ? (
        <p className="muted" style={{ fontSize: '0.85rem' }}>Source: the business database result above.</p>
      ) : resp.evidence.length > 0 && (
        <div className="row-wrap sources-row">
          <span className="text-secondary" style={{ fontSize: '0.85rem' }}>{showAll ? 'All retrieved:' : 'Sources:'}</span>
          {shown.map((e) => (
            <button
              key={e.source_id}
              className={`chip ${openSource === e.source_id ? 'active' : ''}`}
              onClick={() => setOpenSource(openSource === e.source_id ? null : e.source_id)}
            >
              <strong>{e.source_id}</strong> {sourceLabel(e)}
            </button>
          ))}
          {resp.evidence.length > cited.length && (
            <button className="btn btn-secondary btn-sm" onClick={() => setShowAll(!showAll)}>
              {showAll ? 'Cited only' : `All ${resp.evidence.length} retrieved`}
            </button>
          )}
        </div>
      )}

      <details className="details-row">
        <summary>Details</summary>
        <div className="row-wrap" style={{ marginTop: '0.5rem' }}>
          {[...resp.reason_codes, ...resp.flags].filter((c) => c !== 'OK').map((c) => (
            <span key={c} className="badge badge-muted mono" title={REASONS[c] || c}>{c}</span>
          ))}
          <span className="badge badge-muted">route: {resp.route}</span>
          <span className="badge badge-muted">{resp.llm_mode === 'groq' ? 'LLM: Groq' : 'Extractive (no LLM)'}</span>
          <span className="badge badge-muted">{ms(resp.latency_ms)}</span>
          <span className="badge badge-muted" title={`Budget: ${resp.usage.budget?.max_input} in / ${resp.usage.budget?.max_output} out`}>
            {resp.usage.input_tokens} in / {resp.usage.output_tokens} out tokens
          </span>
        </div>
      </details>

      <div className="feedback-row">
        <span className="text-secondary" style={{ fontSize: '0.85rem' }}>Helpful?</span>
        <button className={`btn btn-sm ${rating === true ? 'btn-primary' : 'btn-secondary'}`} aria-pressed={rating === true} onClick={() => sendFeedback(true)} disabled={fbState === 'saving'}>👍 Yes</button>
        <button className={`btn btn-sm ${rating === false ? 'btn-primary' : 'btn-secondary'}`} aria-pressed={rating === false} onClick={() => sendFeedback(false)} disabled={fbState === 'saving'}>👎 No</button>
        {rating !== null && (
          <form className="row-wrap" style={{ flex: 1 }} onSubmit={(e) => { e.preventDefault(); sendFeedback(rating, comment); }}>
            <input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Optional comment"
              aria-label="Feedback comment"
              maxLength={1000}
              style={{ flex: 1, minWidth: 160, padding: '0.35rem 0.7rem', fontSize: '0.85rem' }}
            />
            <button type="submit" className="btn btn-secondary btn-sm" disabled={fbState === 'saving' || !comment.trim()}>Save comment</button>
          </form>
        )}
        {fbState === 'saved' && <span className="badge badge-success">Saved</span>}
        {fbState === 'error' && <span className="badge badge-danger">Could not save</span>}
        {isAdmin && (
          <Link href={`/observability/${resp.query_id}`} target="_blank" className="btn btn-secondary btn-sm" style={{ textDecoration: 'none', marginLeft: 'auto' }}>
            View trace ↗
          </Link>
        )}
      </div>
    </article>
  );
}
