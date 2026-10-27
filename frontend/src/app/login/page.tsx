'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { fetchApi } from '@/lib/api';
import { GoogleLogin } from '@react-oauth/google';

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

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
    } catch (err: any) {
      setError(err.message || 'Google Login failed');
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
