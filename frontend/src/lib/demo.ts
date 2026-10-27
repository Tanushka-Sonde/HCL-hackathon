/**
 * Local demo mode.
 * When enabled (default for the hackathon build), the UI talks to the
 * self-contained knowledge service and skips Google sign-in and organizations.
 * Set NEXT_PUBLIC_DEMO_MODE=false to restore the production auth flow.
 */

export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE !== 'false';

export const DEMO_TENANT = {
  org_id: 'demo',
  user_id: 'demo-user',
  role: 'admin',
  organization: {
    id: 'demo',
    name: 'Demo Workspace',
    slug: 'demo',
    created_at: '2026-01-01T00:00:00Z',
  },
};
