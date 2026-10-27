'use client';

import React, { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { useTenant } from './TenantProvider';
import Link from 'next/link';
import { fetchApi } from '@/lib/api';
import { DEMO_MODE } from '@/lib/demo';

// Pages where the header should NOT appear
const PUBLIC_PATHS = ['/login', '/'];

const DEMO_NAV = [
  { href: '/assistant', label: 'Assistant' },
  { href: '/knowledge', label: 'Knowledge Base' },
  { href: '/observability', label: 'Observability' },
];

function DemoHeader() {
  const pathname = usePathname();
  return (
    <header className="app-header">
      <Link href="/" className="brand">
        <span className="brand-mark">◆</span> Enterprise Knowledge Assistant
      </Link>
      <nav className="app-nav">
        {DEMO_NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`nav-link ${pathname.startsWith(item.href) ? 'active' : ''}`}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <span className="badge badge-warn" title="No sign-in. SQLite store, synthetic data only.">
        Local demo mode
      </span>
    </header>
  );
}

export function Header() {
  if (DEMO_MODE) return <DemoHeader />;
  return <AuthHeader />;
}

function AuthHeader() {
  const router = useRouter();
  const pathname = usePathname();
  const { memberships, activeTenant, switchTenant, isLoading } = useTenant();
  const [pendingInvitesCount, setPendingInvitesCount] = useState(0);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    const hasToken = !!localStorage.getItem('access_token');
    setIsAuthenticated(hasToken);

    if (hasToken) {
      fetchApi('/organizations/invites/pending')
        .then((invites: any[]) => setPendingInvitesCount(invites.length))
        .catch(console.error);
    }
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('active_tenant_id');
    window.location.href = '/login';
  };

  // Don't render header on public pages or while loading
  if (isLoading) return null;
  if (!isAuthenticated) return null;
  if (PUBLIC_PATHS.includes(pathname)) return null;

  return (
    <header className="glass-panel" style={{ display: 'flex', justifyContent: 'space-between', padding: '1rem 2rem', marginBottom: '2rem', borderRadius: 0, borderTop: 0, borderLeft: 0, borderRight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '2rem' }}>
        <h2 style={{ margin: 0, cursor: 'pointer' }} onClick={() => router.push('/dashboard')}>AI Research</h2>
        
        {memberships.length > 0 && (
          <select 
            value={activeTenant?.org_id || ''}
            onChange={(e) => {
              if (e.target.value === 'create_new_org') {
                router.push('/organizations/create');
              } else {
                switchTenant(e.target.value);
              }
            }}
            className="input"
            style={{ width: 'auto', padding: '0.5rem' }}
          >
            {memberships.map((m) => (
              <option key={m.org_id} value={m.org_id}>
                {m.organization.name} ({m.role})
              </option>
            ))}
            <option disabled>──────────</option>
            <option value="create_new_org">+ Create Organization</option>
          </select>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
        <button 
          className="btn btn-secondary" 
          onClick={() => router.push('/invites')}
          style={{ position: 'relative' }}
        >
          Inbox
          {pendingInvitesCount > 0 && (
            <span style={{ 
              position: 'absolute', top: -5, right: -5, 
              background: 'var(--danger)', color: 'white', 
              borderRadius: '50%', width: 20, height: 20, 
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '0.75rem'
            }}>
              {pendingInvitesCount}
            </span>
          )}
        </button>
        <button className="btn btn-secondary" onClick={handleLogout}>Logout</button>
      </div>
    </header>
  );
}
