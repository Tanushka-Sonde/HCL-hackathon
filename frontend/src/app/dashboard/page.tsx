'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { fetchApi } from '@/lib/api';
import { useRouter } from 'next/navigation';
import { useTenant } from '@/components/TenantProvider';
import { canUploadDocument, canDeleteDocument, canManageTeam } from '@/lib/permissions';

type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed';

interface DocumentItem {
  id: string;
  filename: string;
  status: DocumentStatus;
  chunk_count: number;
  size_bytes: number;
}

export default function DashboardPage() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const { activeTenant } = useTenant();
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      const data = await fetchApi('/documents');
      setDocuments(data.items || []);
      return data.items || [];
    } catch (err) {
      console.error(err);
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const startPollingIfNeeded = useCallback((docs: DocumentItem[]) => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    const hasInProgress = docs.some(d => d.status === 'pending' || d.status === 'processing');
    if (hasInProgress) {
      pollTimerRef.current = setInterval(async () => {
        const freshDocs = await loadDocuments();
        const stillInProgress = freshDocs.some((d: DocumentItem) => d.status === 'pending' || d.status === 'processing');
        if (!stillInProgress && pollTimerRef.current) {
          clearInterval(pollTimerRef.current);
          pollTimerRef.current = null;
        }
      }, 3000);
    }
  }, [loadDocuments]);

  useEffect(() => {
    if (!activeTenant) return;

    loadDocuments().then((docs: DocumentItem[]) => {
      startPollingIfNeeded(docs);
    });

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [activeTenant, loadDocuments, startPollingIfNeeded]);

  // If no tenant is selected, show onboarding
  if (!activeTenant) {
    return (
      <div className="page-container animate-fade-in text-center" style={{ marginTop: '5rem' }}>
        <h2>Welcome to AI Research</h2>
        <p className="text-secondary" style={{ marginBottom: '2rem' }}>You aren't a member of any organization yet.</p>
        <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem' }}>
          <button className="btn btn-primary" onClick={() => router.push('/organizations/create')}>Create New Organization</button>
          <button className="btn btn-secondary" onClick={() => router.push('/invites')}>Check Invitations</button>
        </div>
      </div>
    );
  }

  const role = activeTenant.role;

  const deleteDocument = async (id: string) => {
    if (!confirm('Are you sure you want to delete this document?')) return;
    try {
      await fetchApi(`/documents/${id}`, { method: 'DELETE' });
      setDocuments(documents.filter(d => d.id !== id));
    } catch (err) {
      alert('Failed to delete document');
    }
  };

  const getStatusColor = (status: DocumentStatus) => {
    switch (status) {
      case 'ready': return 'var(--success)';
      case 'failed': return 'var(--danger)';
      case 'pending':
      case 'processing': return 'var(--accent-primary)';
      default: return 'var(--text-secondary)';
    }
  };

  const getStatusLabel = (status: DocumentStatus) => {
    switch (status) {
      case 'pending': return 'Queued';
      case 'processing': return 'Processing...';
      case 'ready': return 'Ready';
      case 'failed': return 'Failed';
      default: return status;
    }
  };

  return (
    <div className="page-container animate-fade-in">
      <div className="flex justify-between items-center" style={{ marginBottom: '2rem' }}>
        <div>
          <h1>{activeTenant.organization.name}</h1>
          <p className="text-secondary">Role: <span style={{ textTransform: 'capitalize', color: 'var(--accent-primary)' }}>{role}</span></p>
        </div>
        <div className="flex gap-4">
          {canManageTeam(role) && (
            <button className="btn btn-secondary" onClick={() => router.push('/dashboard/settings/team')}>
              Team Settings
            </button>
          )}
          <button className="btn btn-secondary" onClick={() => router.push('/search')}>
            🔍 Search
          </button>
          {canUploadDocument(role) && (
            <button className="btn btn-primary" onClick={() => router.push('/dashboard/upload')}>
              + Upload Document
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <p className="text-secondary text-center" style={{ padding: '3rem' }}>Loading documents...</p>
      ) : documents.length === 0 ? (
        <div className="glass-panel text-center" style={{ padding: '4rem' }}>
          <h3 style={{ marginBottom: '1rem' }}>No documents found</h3>
          <p className="text-secondary" style={{ marginBottom: '2rem' }}>You haven't uploaded any research material yet.</p>
          {canUploadDocument(role) && (
            <button className="btn btn-primary" onClick={() => router.push('/dashboard/upload')}>
              Upload your first document
            </button>
          )}
        </div>
      ) : (
        <div style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
          {documents.map((doc) => (
            <div key={doc.id} className="glass-panel" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column' }}>
              <h3 style={{ fontSize: '1.1rem', marginBottom: '0.5rem', wordBreak: 'break-all' }}>{doc.filename}</h3>
              <div className="text-secondary" style={{ fontSize: '0.85rem', marginBottom: '1rem', flexGrow: 1 }}>
                <p>
                  Status:{' '}
                  <span style={{ color: getStatusColor(doc.status), fontWeight: 600 }}>
                    {getStatusLabel(doc.status)}
                  </span>
                </p>
                <p>Chunks: {doc.chunk_count || 0}</p>
                <p>Size: {(doc.size_bytes / 1024).toFixed(1)} KB</p>
              </div>

              {/* Progress bar for in-progress documents */}
              {(doc.status === 'pending' || doc.status === 'processing') && (
                <div style={{ marginBottom: '1rem' }}>
                  <div style={{
                    width: '100%',
                    height: '6px',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                    borderRadius: '3px',
                    overflow: 'hidden',
                  }}>
                    <div style={{
                      height: '100%',
                      width: '40%',
                      borderRadius: '3px',
                      background: 'linear-gradient(90deg, var(--accent-primary), #8b5cf6)',
                      animation: 'progress-slide 1.5s ease-in-out infinite alternate',
                    }} />
                  </div>
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.4rem' }}>
                    {doc.status === 'pending' ? 'Waiting in queue...' : 'Chunking & embedding in progress...'}
                  </p>
                </div>
              )}

              {canDeleteDocument(role) && doc.status !== 'processing' && doc.status !== 'pending' && (
                <button 
                  className="btn btn-secondary" 
                  style={{ width: '100%', borderColor: 'var(--danger)', color: 'var(--danger)' }}
                  onClick={() => deleteDocument(doc.id)}
                >
                  Delete
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <style jsx>{`
        @keyframes progress-slide {
          0% { margin-left: 0%; }
          100% { margin-left: 60%; }
        }
      `}</style>
    </div>
  );
}
