'use client';

import React, { useState } from 'react';
import { fetchApi } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { useTenant } from '@/components/TenantProvider';

export default function CreateOrganizationPage() {
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { refreshMemberships, switchTenant } = useTenant();

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const org = await fetchApi('/organizations', {
        method: 'POST',
        body: JSON.stringify({ name, slug }),
      });
      
      // Refresh memberships to get the new role
      await refreshMemberships();
      
      // Switch to the newly created tenant
      switchTenant(org.id);
      
      // switchTenant triggers a window.reload(), but we can also push router just in case
      router.push('/dashboard');
    } catch (err: any) {
      alert(err.message || 'Failed to create organization');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '600px' }}>
      <button className="btn btn-secondary" style={{ marginBottom: '2rem' }} onClick={() => router.push('/dashboard')}>
        &larr; Back to Dashboard
      </button>

      <div className="glass-panel" style={{ padding: '3rem' }}>
        <h1 style={{ marginBottom: '0.5rem' }}>Create Organization</h1>
        <p className="text-secondary" style={{ marginBottom: '2rem' }}>
          Start a new workspace for your team.
        </p>

        <form onSubmit={handleCreate} className="flex flex-col gap-4">
          <div>
            <label className="text-secondary" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>Organization Name</label>
            <input 
              type="text" 
              className="input" 
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Acme Corp"
              required
            />
          </div>
          <div>
            <label className="text-secondary" style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem' }}>URL Slug</label>
            <input 
              type="text" 
              className="input" 
              value={slug}
              onChange={e => setSlug(e.target.value)}
              placeholder="e.g. acme-corp"
              required
            />
          </div>

          <button 
            type="submit" 
            className="btn btn-primary" 
            disabled={!name || !slug || loading} 
            style={{ marginTop: '1rem', padding: '1rem', fontSize: '1.1rem' }}
          >
            {loading ? 'Creating...' : 'Create Organization'}
          </button>
        </form>
      </div>
    </div>
  );
}
