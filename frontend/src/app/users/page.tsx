'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { RequireAuth, usePageTitle } from '@/lib/auth';
import { kis, num, type Role, type UserSummary } from '@/lib/kis';

export default function UsersPage() {
  return (
    <RequireAuth role="admin">
      <Users />
    </RequireAuth>
  );
}

function Users() {
  usePageTitle('Users');
  const [rows, setRows] = useState<UserSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [form, setForm] = useState<{ username: string; password: string; role: Role }>({ username: '', password: '', role: 'user' });
  const [notice, setNotice] = useState('');

  const load = useCallback(
    () =>
      kis
        .usersSummary()
        .then(setRows)
        .catch((e) => setError(e instanceof Error ? e.message : 'Could not load users'))
        .finally(() => setLoading(false)),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    try {
      const u = await kis.createUser(form.username.trim(), form.password, form.role);
      setNotice(`Created ${u.username} (${u.role}).`);
      setForm({ username: '', password: '', role: 'user' });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the user');
    }
  };

  return (
    <div className="animate-fade-in stack">
      <div>
        <h1 className="page-title">Users</h1>
        <p className="text-secondary" style={{ fontSize: '0.9rem' }}>Activity per user, token use and unusual activity in the last 24 hours. Passwords are never shown or returned by the API.</p>
      </div>
      {error && <div className="banner banner-danger" role="alert">{error}</div>}
      {notice && <div className="banner banner-success" role="status">{notice}</div>}

      <div className="glass-panel panel">
        <h2 className="section-title">All users</h2>
        {loading ? <p className="muted animate-pulse">Loading…</p> : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>User</th><th>Role</th><th>Queries</th><th>Sessions</th><th>Tokens (in / out)</th><th className="hide-sm">Cost</th><th className="hide-sm">Outcomes ✓ / ~ / ✗</th><th>Last active</th><th>Flags</th></tr>
              </thead>
              <tbody>
                {rows.map((u) => (
                  <tr key={u.id}>
                    <td><Link className="text-accent" href={`/users/${u.id}`}>{u.username}</Link>{!u.is_active && <span className="badge badge-muted"> inactive</span>}</td>
                    <td><span className={`badge ${u.role === 'admin' ? 'badge-info' : 'badge-muted'}`}>{u.role}</span></td>
                    <td>{u.queries}</td>
                    <td>{u.sessions}</td>
                    <td className="nowrap">{num(u.input_tokens)} / {num(u.output_tokens)}</td>
                    <td className="hide-sm">${u.cost_usd.toFixed(4)}</td>
                    <td className="hide-sm">{u.outcomes.success} / {u.outcomes.partial} / {u.outcomes.failed}</td>
                    <td className="nowrap">{u.last_active ? new Date(u.last_active).toLocaleString() : '—'}</td>
                    <td>
                      {u.anomalies.length ? u.anomalies.map((a) => <span key={a} className="badge badge-danger" style={{ marginRight: 4 }}>{a}</span>) : <span className="muted">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <form className="glass-panel panel stack" onSubmit={create} style={{ maxWidth: 560 }}>
        <h2 className="section-title">Create a user</h2>
        <div className="advanced-grid">
          <label className="field"><span>Username</span><input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required minLength={3} maxLength={64} autoComplete="off" /></label>
          <label className="field"><span>Password (min 6)</span><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={6} maxLength={128} autoComplete="new-password" /></label>
          <label className="field"><span>Role</span>
            <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              <option value="user">User (assistant only)</option><option value="admin">Admin</option>
            </select>
          </label>
        </div>
        <button type="submit" className="btn btn-primary" style={{ alignSelf: 'flex-start' }}>Create user</button>
      </form>
    </div>
  );
}
