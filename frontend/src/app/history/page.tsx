'use client';

import { useEffect, useState } from 'react';
import { OutcomeBadge } from '@/components/kis/Badges';
import { RequireAuth, usePageTitle } from '@/lib/auth';
import { kis, num, type SessionRow, type Turn } from '@/lib/kis';

export default function HistoryPage() {
  return (
    <RequireAuth>
      <History />
    </RequireAuth>
  );
}

function History() {
  usePageTitle('My history');
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [usage, setUsage] = useState({ input_tokens: 0, output_tokens: 0, cost_usd: 0 });
  const [open, setOpen] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    kis
      .myHistory()
      .then((h) => {
        setSessions(h.sessions);
        setUsage(h.usage);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load history'))
      .finally(() => setLoading(false));
  }, []);

  const show = async (id: string) => {
    setOpen(id);
    setTurns([]);
    try {
      setTurns((await kis.myHistory(id)).turns);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the conversation');
    }
  };

  return (
    <div className="stack animate-fade-in" style={{ maxWidth: 960, margin: '0 auto' }}>
      <div>
        <h1 className="page-title">My history</h1>
        <p className="text-secondary" style={{ fontSize: '0.9rem' }}>
          Your own conversations. Personal data and salaries stay masked, as they were in your answers.
        </p>
      </div>
      {error && <div className="banner banner-danger" role="alert">{error}</div>}

      <div className="kpi-grid">
        <div className="glass-panel kpi"><div className="kpi-label">Conversations</div><div className="kpi-value">{sessions.length}</div></div>
        <div className="glass-panel kpi"><div className="kpi-label">Questions</div><div className="kpi-value">{sessions.reduce((n, s) => n + s.query_count, 0)}</div></div>
        <div className="glass-panel kpi">
          <div className="kpi-label">Tokens used</div>
          <div className="kpi-value">{num(usage.input_tokens + usage.output_tokens)}</div>
          <div className="kpi-sub">{num(usage.input_tokens)} in / {num(usage.output_tokens)} out</div>
        </div>
      </div>

      <div className="glass-panel panel">
        <h2 className="section-title">Conversations</h2>
        {loading ? <p className="muted animate-pulse">Loading…</p> : sessions.length === 0 ? (
          <p className="text-secondary">No conversations yet. Ask something on the Assistant page.</p>
        ) : (
          <ul className="session-list">
            {sessions.map((s) => (
              <li key={s.session_id}>
                <button className={`session-item ${open === s.session_id ? 'active' : ''}`} onClick={() => show(s.session_id)} aria-expanded={open === s.session_id}>
                  <span className="session-title">{s.title}</span>
                  <span className="muted">{new Date(s.last_active_at).toLocaleString()} · {s.query_count} question{s.query_count === 1 ? '' : 's'} · {num(s.input_tokens + s.output_tokens)} tokens</span>
                </button>
                {open === s.session_id && (
                  <div className="stack transcript">
                    {turns.length === 0 && <p className="muted animate-pulse">Loading conversation…</p>}
                    {turns.map((t) => (
                      <div key={t.query_id} className="stack" style={{ gap: '0.4rem' }}>
                        <div className="chat-msg chat-user">{t.query}</div>
                        <div className="chat-msg glass-panel">
                          <div className="row-wrap" style={{ marginBottom: '0.3rem' }}>
                            <OutcomeBadge outcome={t.outcome} />
                            <span className="muted" style={{ fontSize: '0.8rem' }}>{new Date(t.timestamp).toLocaleTimeString()} · {t.input_tokens} in / {t.output_tokens} out tokens</span>
                          </div>
                          <div className="answer-text">{t.answer}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
