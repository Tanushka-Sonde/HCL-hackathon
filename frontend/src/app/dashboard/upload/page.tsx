'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { fetchApi } from '@/lib/api';
import { useTenant } from '@/components/TenantProvider';
import { canUploadDocument } from '@/lib/permissions';

export default function UploadPage() {
  const router = useRouter();
  const { activeTenant } = useTenant();
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (activeTenant && !canUploadDocument(activeTenant.role)) {
      alert('You do not have permission to upload documents in this organization.');
      router.push('/dashboard');
    }
  }, [activeTenant, router]);

  if (!activeTenant || !canUploadDocument(activeTenant.role)) return null;

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setError('');
    setUploading(true);

    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const idempotencyKey = `upload-${Date.now()}`;

      await fetchApi('/documents', {
        method: 'POST',
        headers: {
          'Idempotency-Key': idempotencyKey,
        },
        body: formData,
      });

      // Go straight to dashboard — it polls for in-progress documents automatically
      router.push('/dashboard');
    } catch (err: any) {
      setError(err.message || 'Upload failed');
      setUploading(false);
    }
  };

  return (
    <div className="page-container animate-fade-in" style={{ maxWidth: '600px' }}>
      <button className="btn btn-secondary" style={{ marginBottom: '2rem' }} onClick={() => router.push('/dashboard')}>
        &larr; Back to Dashboard
      </button>

      <div className="glass-panel" style={{ padding: '3rem' }}>
        <h1 style={{ marginBottom: '0.5rem' }}>Upload Document</h1>
        <p className="text-secondary" style={{ marginBottom: '2rem' }}>
          Upload PDFs, TXTs, or Markdown files to be chunked, embedded, and indexed.
        </p>

        {error && (
          <div style={{ backgroundColor: 'var(--danger)', color: 'white', padding: '0.75rem', borderRadius: '8px', marginBottom: '1rem' }}>
            {error}
          </div>
        )}

        <form onSubmit={handleUpload} className="flex flex-col gap-4">
          <div 
            style={{ 
              border: '2px dashed var(--border-color)', 
              borderRadius: '12px', 
              padding: '4rem 2rem', 
              textAlign: 'center',
              backgroundColor: 'rgba(0,0,0,0.2)',
              cursor: 'pointer'
            }}
          >
            <input 
              type="file" 
              id="file-upload" 
              style={{ display: 'none' }} 
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              accept=".pdf,.txt,.md"
            />
            <label htmlFor="file-upload" style={{ cursor: 'pointer', display: 'block' }}>
              <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>📄</div>
              {file ? (
                <span className="text-accent">{file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)</span>
              ) : (
                <span className="text-secondary">Click to browse or drag and drop<br/><small>Supports PDF, TXT, MD</small></span>
              )}
            </label>
          </div>

          <button 
            type="submit" 
            className="btn btn-primary" 
            disabled={!file || uploading} 
            style={{ marginTop: '1rem', padding: '1rem', fontSize: '1.1rem' }}
          >
            {uploading ? 'Uploading...' : 'Upload & Ingest'}
          </button>
        </form>
      </div>
    </div>
  );
}
