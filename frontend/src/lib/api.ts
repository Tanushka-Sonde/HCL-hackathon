/**
 * Core API Client
 * Wraps fetch to automatically inject JWT tokens and handle 401s.
 */

export const API_BASE_URL = '/api/v1';

/** A useful message when the backend gives no error text of its own. */
function describeFailure(status: number, detail?: unknown): string {
  if (status === 404) {
    // Usually an outdated backend process, or BACKEND_URL pointing elsewhere.
    return 'The backend does not have this endpoint. Restart the API with the current code (uvicorn src.main:app --port 8000) and check BACKEND_URL.';
  }
  if (status >= 500) {
    return 'The backend is not reachable or failed. Check that the API is running (default http://127.0.0.1:8000) and see its log.';
  }
  if (typeof detail === 'string') return detail;
  return `API request failed (HTTP ${status})`;
}

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

  // An expired or invalid token signs the user out. A failed login attempt is
  // also a 401, but it must reach the form so the error can be shown.
  if (response.status === 401 && !endpoint.endsWith('/auth/login')) {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('access_token');
      if (window.location.pathname !== '/login') window.location.href = '/login';
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
      throw new Error(data.error?.message || describeFailure(response.status, data.detail));
    }
    return data;
  }

  if (!response.ok) {
    throw new Error(describeFailure(response.status));
  }

  return response;
}
