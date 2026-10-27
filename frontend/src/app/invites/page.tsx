'use client';

import React, { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { useTenant } from '@/components/TenantProvider';

export default function InvitesPage() {
  const [invites, setInvites] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const { refreshMemberships } = useTenant();

  useEffect(() => {
    loadInvites();
  }, []);

  const loadInvites = async () => {
    try {
      const data = await fetchApi('/organizations/invites/pending');
      setInvites(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleAccept = async (id: string) => {
    try {
      await fetchApi(`/organizations/invites/${id}/accept`, { method: 'POST' });
      await refreshMemberships();
      router.push('/dashboard');
    } catch (err: any) {
      alert(err.message || 'Failed to accept invite');
    }
  };

  return (
    <div className="page-container animate-fade-in">
      <h1 style={{ marginBottom: '2rem' }}>Your Invitations</h1>
      
      {loading ? (
        <p className="text-secondary text-center">Loading invitations...</p>
      ) : invites.length === 0 ? (
        <div className="glass-panel text-center" style={{ padding: '4rem' }}>
          <h3>No pending invitations</h3>
          <p className="text-secondary">You don't have any pending requests to join organizations.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '1rem' }}>
          {invites.map((invite) => (
            <div key={invite.id} className="glass-panel flex justify-between items-center" style={{ padding: '1.5rem' }}>
              <div>
                <h3 style={{ marginBottom: '0.25rem' }}>{invite.organization?.name}</h3>
                <p className="text-secondary" style={{ fontSize: '0.875rem' }}>
                  Invited as <strong style={{ color: 'var(--accent-primary)', textTransform: 'capitalize' }}>{invite.role}</strong>
                </p>
                <p className="text-secondary" style={{ fontSize: '0.75rem', marginTop: '0.5rem' }}>
                  Expires: {new Date(invite.expires_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex gap-4">
                <button className="btn btn-primary" onClick={() => handleAccept(invite.id)}>
                  Accept Invitation
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
