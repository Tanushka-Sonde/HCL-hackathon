'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { OutcomeBadge } from '@/components/kis/Badges';
import { RequireAuth, usePageTitle } from '@/lib/auth';
import { kis, num, type SessionRow, type Turn, type UserSummary } from '@/lib/kis';

export default function UserDetailPage() {
  return (
    <RequireAuth role="admin">
      <UserDetail />
    </RequireAuth>
  );
}

function UserDetail() {
  const params = useParams<{ id: string }>();
  const [user, setUser] = useState<UserSummary | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState('');
  usePageTitle(user ? `User · ${user.username}` : 'User');

  useEffect(() => {
    if (!params?.id) return;
    Promise.all([kis.usersSummary(), kis.userSessions(params.id)])
      .then(([all, s]) => {
        setUser(all.find((u) => u.id === params.id) || null);
        setSessions(s);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load the user'));
  }, [params?.id]);

  const show = async (sid: string) => {
    if (open === sid) return setOpen(null);
    setOpen(sid);
    setTurns([]);
    setTurns(await kis.transcript(sid).catch(() => []));
  };

  return (
    <div className="animate-fade-in stack">
      <Link href="/users" className="text-accent" style={{ fontSize: '0.9rem' }}>← All users</Link>
      {error && <div className="banner banner-danger" role="alert">{error}</div>}
      {user && (
        <>
          <div className="row-wrap">
            <h1 className="page-title" style={{ margin: 0 }}>{user.username}</h1>
            <span className={`badge ${user.role === 'admin' ? 'badge-info' : 'badge-muted'}`}>{user.role}</span>
            {user.anomalies.map((a) => <span key={a} className="badge badge-danger">{a}</span>)}
          </div>
          <div className="kpi-grid">
            <div className="glass-panel kpi"><div className="kpi-label">Queries</div><div className="kpi-value">{user.queries}</div><div className="kpi-sub">{user.outcomes.success} success · {user.outcomes.partial} partial · {user.outcomes.failed} failed</div></div>
            <div className="glass-panel kpi"><div className="kpi-label">Sessions</div><div className="kpi-value">{user.sessions}</div></div>
            <div className="glass-panel kpi"><div className="kpi-label">Tokens</div><div className="kpi-value">{num(user.input_tokens + user.output_tokens)}</div><div className="kpi-sub">{num(user.input_tokens)} in / {num(user.output_tokens)} out · ${user.cost_usd.toFixed(4)}</div></div>
            <div className="glass-panel kpi"><div className="kpi-label">Safety events</div><div className="kpi-value">{user.safety_events}</div></div>
          </div>
        </>
      )}

      <div className="glass-panel panel">
        <h2 className="section-title">Sessions ({sessions.length})</h2>
        {sessions.length === 0 ? <p className="muted">No sessions.</p> : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>First question</th><th>Started</th><th>Last active</th><th>Queries</th><th>Tokens in / out</th><th>Cost</th></tr></thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.session_id}>
                    <td>
                      <button className="link-button" onClick={() => show(s.session_id)} aria-expanded={open === s.session_id}>{s.title}</button>
                      {open === s.session_id && (
                        <div className="stack transcript">
                          {turns.length === 0 && <p className="muted animate-pulse">Loading transcript…</p>}
                          {turns.map((t) => (
                            <div key={t.query_id} className="evidence-box">
                              <div className="row-wrap" style={{ marginBottom: '0.3rem' }}>
                                <OutcomeBadge outcome={t.outcome} />
                                <span className="muted" style={{ fontSize: '0.8rem' }}>{new Date(t.timestamp).toLocaleTimeString()} · {t.input_tokens} in / {t.output_tokens} out</span>
                                <Link className="text-accent" href={`/observability/${t.query_id}`} style={{ marginLeft: 'auto', fontSize: '0.8rem' }}>trace →</Link>
                              </div>
                              <p><strong>Q:</strong> {t.query}</p>
                              <p style={{ whiteSpace: 'pre-wrap' }}><strong>A:</strong> {t.answer}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="nowrap">{new Date(s.created_at).toLocaleString()}</td>
                    <td className="nowrap">{new Date(s.last_active_at).toLocaleString()}</td>
                    <td>{s.query_count}</td>
                    <td className="nowrap">{num(s.input_tokens)} / {num(s.output_tokens)}</td>
                    <td>${s.cost_usd.toFixed(4)}</td>
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
