'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { fetchApi } from '@/lib/api';
import { GoogleLogin } from '@react-oauth/google';
import { DEMO_MODE } from '@/lib/demo';
import { homeFor, useAuth, usePageTitle } from '@/lib/auth';

export default function LoginPage() {
  return DEMO_MODE ? <PasswordLogin /> : <GoogleLoginPage />;
}

/** One form for everyone: the account decides whether you are an admin. */
function PasswordLogin() {
  usePageTitle('Sign in');
  const router = useRouter();
  const { user, loading, login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace(homeFor(user.role));
  }, [loading, user, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const role = await login(username.trim(), password);
      router.replace(homeFor(role));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap animate-fade-in">
      <form className="glass-panel login-card stack" onSubmit={submit} aria-labelledby="login-title">
        <div>
          <h1 id="login-title" className="login-title"><span className="brand-mark" aria-hidden>◆</span> Knowledge Assistant</h1>
          <p className="text-secondary" style={{ fontSize: '0.92rem' }}>Sign in with your account.</p>
        </div>
        {error && <div className="banner banner-danger" role="alert">{error}</div>}
        <label className="field">
          <span>Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required maxLength={64} />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required maxLength={128} />
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy || !username || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="muted" style={{ fontSize: '0.8rem' }}>
          Demo accounts: <span className="mono">admin / admin123</span> (administrator), <span className="mono">alice / user123</span> (user).
        </p>
      </form>
    </div>
  );
}

function GoogleLoginPage() {
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const handleGoogleSuccess = async (credentialResponse: any) => {
    setError('');
    setLoading(true);

    try {
      const res = await fetchApi('/auth/google-login', {
        method: 'POST',
        body: JSON.stringify({ credential: credentialResponse.credential }),
      });

      localStorage.setItem('access_token', res.access_token);
      if (res.refresh_token) {
        localStorage.setItem('refresh_token', res.refresh_token);
      }
      // Use window.location to ensure TenantProvider re-initializes with the new token
      window.location.href = '/dashboard';
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Google Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container flex items-center justify-center animate-fade-in" style={{ minHeight: '100vh' }}>
      <div className="glass-panel" style={{ padding: '3rem', width: '100%', maxWidth: '400px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <h1 className="text-center" style={{ marginBottom: '0.5rem' }}>Welcome</h1>
        <p className="text-center text-secondary" style={{ marginBottom: '2rem' }}>Sign in to your AI Research Platform</p>

        {error && (
          <div style={{ backgroundColor: 'var(--danger)', color: 'white', padding: '0.75rem', borderRadius: '8px', marginBottom: '1rem', fontSize: '0.9rem', width: '100%' }}>
            {error}
          </div>
        )}

        {loading ? (
          <p className="text-secondary">Signing in...</p>
        ) : (
          <GoogleLogin
            onSuccess={handleGoogleSuccess}
            onError={() => {
              setError('Google Login was unsuccessful or aborted.');
            }}
            useOneTap
          />
        )}
      </div>
    </div>
  );
}
