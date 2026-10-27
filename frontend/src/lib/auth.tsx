'use client';

/**
 * Sign-in state for local demo mode (username + password, JWT).
 *
 * The role decides which UI is shown, but it is never the security boundary:
 * every admin endpoint is checked by the backend, which returns 403 to users.
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { kis, type Role, type UserInfo } from '@/lib/kis';

interface AuthState {
  user: UserInfo | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<Role>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

const PUBLIC_PATHS = ['/login'];

export function homeFor(role: Role | undefined): string {
  return role === 'admin' ? '/observability' : '/assistant';
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    const check = token
      ? kis.me().then(setUser).catch(() => localStorage.removeItem('access_token'))
      : Promise.resolve();
    check.finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await kis.login(username, password);
    localStorage.setItem('access_token', res.access_token);
    const me = await kis.me();
    setUser(me);
    return me.role;
  }, []);

  const router = useRouter();
  const logout = useCallback(() => {
    localStorage.removeItem('access_token');
    sessionStorage.clear(); // drop saved chats on this device
    setUser(null);
    router.replace('/login');
  }, [router]);

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

/**
 * Client-side guard: no token -> /login; a user on an admin page -> /assistant.
 * This only keeps the UI tidy; the API enforces the same rules server-side.
 */
export function RequireAuth({ role, children }: { role?: Role; children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const allowed = !!user && (!role || user.role === role);

  useEffect(() => {
    if (loading || PUBLIC_PATHS.includes(pathname)) return;
    if (!user) router.replace('/login');
    else if (role && user.role !== role) router.replace(homeFor(user.role));
  }, [loading, user, role, router, pathname]);

  if (loading || !allowed) {
    return <p className="muted animate-pulse" style={{ padding: '2rem' }}>Checking your sign-in…</p>;
  }
  return <>{children}</>;
}

export function usePageTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · Knowledge Assistant`;
  }, [title]);
}
