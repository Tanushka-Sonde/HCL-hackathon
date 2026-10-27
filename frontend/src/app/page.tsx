'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { DEMO_MODE } from '@/lib/demo';
import { homeFor, useAuth } from '@/lib/auth';

/** Sends people where they belong: sign-in, the assistant, or the admin console. */
export default function Home() {
  return DEMO_MODE ? <RoleRedirect /> : <LegacyRedirect />;
}

function RoleRedirect() {
  const router = useRouter();
  const { user, loading } = useAuth();
  useEffect(() => {
    if (loading) return;
    router.replace(user ? homeFor(user.role) : '/login');
  }, [loading, user, router]);
  return <p className="muted animate-pulse" style={{ padding: '2rem' }}>Loading…</p>;
}

function LegacyRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace(localStorage.getItem('access_token') ? '/dashboard' : '/login');
  }, [router]);
  return null;
}
