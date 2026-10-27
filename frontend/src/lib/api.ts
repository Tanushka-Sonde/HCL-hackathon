/**
 * Core API Client
 * Wraps fetch to automatically inject JWT tokens and handle 401s.
 */

export const API_BASE_URL = '/api/v1';

export async function fetchApi(endpoint: string, options: RequestInit = {}) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
  
  const activeTenantId = typeof window !== 'undefined' ? localStorage.getItem('active_tenant_id') : null;

  const headers = new Headers(options.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  if (activeTenantId) {
    headers.set('X-Tenant-ID', activeTenantId);
  }
  
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('access_token');
      window.location.href = '/login';
    }
  }

  if (response.status === 403) {
    // We could trigger a toast here if we had a global toast manager
    console.error('Permission denied. Refreshing page may be needed if roles changed.');
  }

  if (response.status === 429) {
    throw new Error('You are making requests too quickly. Please try again shortly.');
  }

  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error?.message || 'API request failed');
    }
    return data;
  }

  if (!response.ok) {
    throw new Error('API request failed');
  }

  return response;
}
