'use client';

import React, { useEffect, useState } from 'react';
import { fetchApi } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { useTenant } from '@/components/TenantProvider';
import { canManageTeam } from '@/lib/permissions';

interface OrgMember {
  id: string;
  user_id: string;
  role: string;
  email: string;
  created_at: string;
}

export default function TeamSettingsPage() {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('viewer');
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<OrgMember[]>([]);
  const [membersLoading, setMembersLoading] = useState(true);
  const router = useRouter();
  const { activeTenant } = useTenant();

  useEffect(() => {
    if (activeTenant && !canManageTeam(activeTenant.role)) {
      alert('You do not have permission to manage the team.');
      router.push('/dashboard');
    }
  }, [activeTenant, router]);

  useEffect(() => {
    if (activeTenant) {
      loadMembers();
    }
  }, [activeTenant]);

  const loadMembers = async () => {
    try {
      const data = await fetchApi('/organizations/members');
      setMembers(data);
    } catch (err) {
      console.error('Failed to load members', err);
    } finally {
      setMembersLoading(false);
    }
  };

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await fetchApi('/organizations/invites', {
        method: 'POST',
        body: JSON.stringify({ email, role }),
      });
      alert('Invitation sent successfully!');
      setEmail('');
    } catch (err: any) {
      alert(err.message || 'Failed to send invite');
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveMember = async (userId: string) => {
    if (!confirm('Are you sure you want to remove this member?')) return;
    try {
      await fetchApi(`/organizations/members/${userId}`, {
        method: 'DELETE',
      });
      alert('Member removed successfully!');
      loadMembers();
    } catch (err: any) {
      alert(err.message || 'Failed to remove member');
    }
  };

  if (!activeTenant || !canManageTeam(activeTenant.role)) return null;

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'admin': return '#ef4444';
      case 'editor': return '#f59e0b';
      case 'viewer': return '#6366f1';
      default: return 'var(--text-secondary)';
    }
  };

  return (
    <div className="page-container animate-fade-in">
      <button className="btn btn-secondary" style={{ marginBottom: '2rem' }} onClick={() => router.push('/dashboard')}>
        &larr; Back to Dashboard
      </button>

      <h1 style={{ marginBottom: '2rem' }}>Team Settings</h1>

      {/* Members List */}
      <div className="glass-panel" style={{ padding: '2rem', marginBottom: '2rem' }}>
        <h3 style={{ marginBottom: '0.5rem' }}>Team Members</h3>
        <p className="text-secondary" style={{ marginBottom: '1.5rem' }}>
          {members.length} member{members.length !== 1 ? 's' : ''} in {activeTenant.organization.name}
        </p>

        {membersLoading ? (
          <p className="text-secondary">Loading members...</p>
        ) : members.length === 0 ? (
          <p className="text-secondary">No members found.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {members.map((member) => (
              <div
                key={member.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '1rem 1.25rem',
                  backgroundColor: 'rgba(255,255,255,0.03)',
                  borderRadius: '10px',
                  border: '1px solid var(--border-color)',
                }}
              >
                <div>
                  <span style={{ fontWeight: 500 }}>{member.email}</span>
                </div>
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                  <span
                    style={{
                      padding: '0.25rem 0.75rem',
                      borderRadius: '20px',
                      fontSize: '0.8rem',
                      fontWeight: 600,
                      textTransform: 'capitalize',
                      backgroundColor: getRoleBadgeColor(member.role) + '22',
                      color: getRoleBadgeColor(member.role),
                      border: `1px solid ${getRoleBadgeColor(member.role)}44`,
                    }}
                  >
                    {member.role}
                  </span>
                  {member.user_id !== activeTenant.user_id && (
                    <button
                      className="btn btn-secondary"
                      style={{ padding: '0.25rem 0.75rem', fontSize: '0.8rem', borderColor: 'var(--danger)', color: 'var(--danger)' }}
                      onClick={() => handleRemoveMember(member.user_id)}
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Invite Form */}
      <div className="glass-panel" style={{ padding: '2rem' }}>
        <h3>Invite new member</h3>
        <p className="text-secondary" style={{ marginBottom: '1.5rem' }}>Invite someone to join {activeTenant.organization.name}.</p>
        
        <form onSubmit={handleInvite} style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
          <div style={{ flexGrow: 1 }}>
            <label className="text-secondary" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Email Address</label>
            <input 
              type="email" 
              className="input" 
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="colleague@example.com"
              required
            />
          </div>
          <div style={{ width: '200px' }}>
            <label className="text-secondary" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Role</label>
            <select className="input" value={role} onChange={e => setRole(e.target.value)}>
              <option value="viewer">Viewer (Read only)</option>
              <option value="editor">Editor (Upload/Delete)</option>
              <option value="admin">Admin (Manage Team)</option>
            </select>
          </div>
          <div style={{ paddingTop: '1.75rem' }}>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? 'Sending...' : 'Send Invite'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
