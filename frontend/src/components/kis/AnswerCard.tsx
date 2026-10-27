'use client';

import Link from 'next/link';
import { useState } from 'react';
import { kis, ms, type QueryResponse } from '@/lib/kis';
import { OutcomeBadge, ReasonBadges } from './Badges';

const TAG_RE = /\[((?:S|T)\d+)\]/g;

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
        className={`chip ${validIds.has(id) ? '' : 'invalid'}`}
        style={{ padding: '0 0.4rem', margin: '0 0.15rem', fontSize: '0.75rem' }}
        onClick={() => onCite(id)}
        title={validIds.has(id) ? 'Show source' : 'Citation does not map to returned evidence'}
      >
        {id}
      </button>,
    );
    last = idx + match[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}

export function AnswerCard({ resp }: { resp: QueryResponse }) {
  const [openSource, setOpenSource] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [feedback, setFeedback] = useState<boolean | null>(null);
  const [comment, setComment] = useState('');
  const [fbState, setFbState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  const validIds = new Set(resp.citations.filter((c) => c.valid).map((c) => c.source_id));
  const citedIds = new Set(resp.citations.map((c) => c.source_id));
  const evidence = showAll ? resp.evidence : resp.evidence.filter((e) => citedIds.has(e.source_id));
  const tool = resp.tool_calls[0];

  const sendFeedback = async (helpful: boolean) => {
    setFeedback(helpful);
    setFbState('saving');
    try {
      await kis.feedback(resp.query_id, helpful, comment);
      setFbState('saved');
    } catch {
      setFbState('error');
    }
  };

  return (
    <div className="glass-panel chat-msg stack" style={{ gap: '0.8rem' }}>
      <div className="row-wrap">
        <OutcomeBadge outcome={resp.outcome} />
        <span className={`badge ${resp.confidence === 'high' ? 'badge-success' : resp.confidence === 'medium' ? 'badge-info' : 'badge-muted'}`}>
          Confidence: {resp.confidence}
        </span>
        <ReasonBadges reasons={resp.reason_codes} flags={resp.flags} />
        <span className="badge badge-muted">route: {resp.route}</span>
        <span className="badge badge-muted">{resp.llm_mode === 'groq' ? 'LLM: Groq' : 'Extractive (no LLM)'}</span>
        <span className="muted" style={{ fontSize: '0.8rem', marginLeft: 'auto' }}>{ms(resp.latency_ms)}</span>
      </div>

      {resp.conflicts.length > 0 && (
        <div className="banner banner-warn">
          <strong>Conflicting sources.</strong> {resp.conflicts.join(' ')}
        </div>
      )}
      {resp.safety.chunk_injections.length > 0 && (
        <div className="banner banner-danger">
          <strong>Embedded instruction ignored.</strong> A retrieved document contained text that tried to instruct the assistant.
          It was removed from the evidence and logged as a safety event.
        </div>
      )}
      {resp.safety.injection_blocked && (
        <div className="banner banner-danger"><strong>Request blocked:</strong> prompt-injection pattern detected in the question.</div>
      )}

      <div className="answer-text">{renderAnswer(resp.answer, setOpenSource, validIds)}</div>

      {openSource && (() => {
        const ev = resp.evidence.find((e) => e.source_id === openSource);
        const tc = resp.tool_calls.find((t) => t.source_id === openSource);
        return (
          <div className="evidence-box">
            <div className="row-wrap" style={{ marginBottom: '0.4rem' }}>
              <strong>{openSource}</strong>
              {ev && <span>{ev.filename} · {ev.doc_id} v{ev.version} ({ev.status}){ev.page ? ` · page ${ev.page}` : ''}{ev.section ? ` · ${ev.section}` : ''}</span>}
              {tc && <span>SQL tool · template <span className="mono">{tc.template}</span> · params <span className="mono">{JSON.stringify(tc.params)}</span></span>}
              {!ev && !tc && <span style={{ color: 'var(--danger)' }}>Not found in returned evidence (invalid citation)</span>}
              <button className="btn btn-secondary btn-sm" style={{ marginLeft: 'auto' }} onClick={() => setOpenSource(null)}>Close</button>
            </div>
            {ev?.content}
            {tc && <pre className="mono">{JSON.stringify(tc.rows, null, 2)}</pre>}
          </div>
        );
      })()}

      {tool && (
        <div className={`banner ${tool.status === 'success' ? 'banner-info' : tool.status === 'error' ? 'banner-danger' : 'banner-warn'}`}>
          <strong>Data tool [{tool.source_id}]</strong> <span className="mono">{tool.name}.{tool.template}</span>{' '}
          {JSON.stringify(tool.params)} → {tool.status}
          {tool.status === 'success' && ` · ${tool.row_count} row(s) · ${ms(tool.latency_ms)}`}
          {tool.error && <> · <span className="mono">{tool.error}</span></>}
          {tool.simulated_failure && <> · <em>simulated failure (demo)</em></>}
        </div>
      )}

      {resp.evidence.length > 0 && (
        <div className="stack" style={{ gap: '0.5rem' }}>
          <div className="row-wrap">
            <span className="text-secondary" style={{ fontSize: '0.85rem' }}>
              Sources {showAll ? `(all ${resp.evidence.length} retrieved)` : '(cited)'}
            </span>
            <button className="btn btn-secondary btn-sm" onClick={() => setShowAll(!showAll)}>
              {showAll ? 'Show cited only' : `Show all ${resp.evidence.length} retrieved`}
            </button>
          </div>
          <div className="row-wrap">
            {evidence.map((e) => (
              <button
                key={e.source_id}
                className={`chip ${openSource === e.source_id ? 'active' : ''}`}
                onClick={() => setOpenSource(openSource === e.source_id ? null : e.source_id)}
                title={`relevance ${e.relevance.toFixed(2)}`}
              >
                <strong>{e.source_id}</strong> {e.doc_id} v{e.version}{e.page ? ` p.${e.page}` : ''}{e.section ? ` · ${e.section}` : ''}
                {e.injection_flag && ' ⚠'}
              </button>
            ))}
            {evidence.length === 0 && <span className="muted" style={{ fontSize: '0.85rem' }}>No document sources cited.</span>}
          </div>
        </div>
      )}

      <div className="row-wrap" style={{ borderTop: '1px solid var(--glass-border)', paddingTop: '0.7rem' }}>
        <span className="text-secondary" style={{ fontSize: '0.85rem' }}>Was this helpful?</span>
        <button className={`btn btn-sm ${feedback === true ? 'btn-primary' : 'btn-secondary'}`} onClick={() => sendFeedback(true)} disabled={fbState === 'saving'}>👍 Helpful</button>
        <button className={`btn btn-sm ${feedback === false ? 'btn-primary' : 'btn-secondary'}`} onClick={() => sendFeedback(false)} disabled={fbState === 'saving'}>👎 Not helpful</button>
        <input
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Optional reviewer comment (sent with your rating)"
          maxLength={1000}
          style={{ flex: 1, minWidth: 180, padding: '0.35rem 0.7rem', fontSize: '0.85rem' }}
        />
        {fbState === 'saved' && <span className="badge badge-success">Feedback recorded</span>}
        {fbState === 'error' && <span className="badge badge-danger">Could not save</span>}
        <Link href={`/observability/${resp.query_id}`} className="btn btn-secondary btn-sm" style={{ textDecoration: 'none' }}>
          View trace →
        </Link>
      </div>
    </div>
  );
}
