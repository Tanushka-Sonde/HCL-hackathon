'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { fetchApi } from '@/lib/api';
import { useTenant } from '@/components/TenantProvider';

export default function SearchPage() {
  const router = useRouter();
  const { activeTenant } = useTenant();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [hasSearched, setHasSearched] = useState(false);

  if (!activeTenant) {
    return (
      <div className="page-container animate-fade-in text-center" style={{ marginTop: '5rem' }}>
        <h2>No Organization Selected</h2>
        <p className="text-secondary" style={{ marginBottom: '2rem' }}>You need to join or create an organization before searching.</p>
        <button className="btn btn-primary" onClick={() => router.push('/dashboard')}>Go to Dashboard</button>
      </div>
    );
  }

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setError('');
    setLoading(true);
    setHasSearched(true);
    setAnswer(null);
    setResults([]);

    try {
      const res = await fetchApi('/search', {
        method: 'POST',
        body: JSON.stringify({ query, top_k: 5 }),
      });
      setResults(res.results || []);
      setAnswer(res.answer || null);
    } catch (err: any) {
      setError(err.message || 'Search failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container flex flex-col items-center animate-fade-in" style={{ minHeight: '100vh', paddingTop: '4rem' }}>
      
      <div style={{ width: '100%', maxWidth: '800px', marginBottom: '3rem' }}>
        <button className="btn btn-secondary" style={{ marginBottom: '2rem' }} onClick={() => router.push('/dashboard')}>
          &larr; Dashboard
        </button>
        <h1 className="text-center" style={{ fontSize: '3rem', marginBottom: '2rem' }}>Hybrid Search</h1>
        
        <form onSubmit={handleSearch} style={{ display: 'flex', gap: '0.75rem', position: 'relative' }}>
          <input 
            type="text" 
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask a question or search keywords..."
            style={{ 
              flex: 1,
              padding: '0.9rem 1.5rem', 
              fontSize: '1rem', 
              borderRadius: '12px',
              backgroundColor: 'var(--bg-tertiary)',
              border: '1px solid var(--glass-border)'
            }}
          />
          <button 
            type="submit" 
            className="btn btn-primary"
            disabled={loading || !query.trim()}
            style={{ 
              borderRadius: '12px',
              padding: '0.9rem 1.5rem',
              whiteSpace: 'nowrap',
            }}
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </form>
        {error && <p style={{ color: 'var(--danger)', marginTop: '1rem', textAlign: 'center' }}>{error}</p>}
      </div>

      <div style={{ width: '100%', maxWidth: '800px', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        
        {loading && (
          <div className="text-center text-secondary py-8">
            <p className="animate-pulse">Retrieving sources and generating answer...</p>
          </div>
        )}

        {!loading && answer && (
          <div className="glass-panel" style={{ padding: '2rem', display: 'flex', flexDirection: 'column', gap: '1rem', border: '1px solid var(--accent)' }}>
            <h2 className="text-accent" style={{ fontSize: '1.5rem', borderBottom: '1px solid var(--glass-border)', paddingBottom: '0.5rem' }}>AI Answer</h2>
            <p style={{ lineHeight: 1.6, color: 'var(--text-primary)', whiteSpace: 'pre-wrap' }}>
              {answer}
            </p>
          </div>
        )}

        {!loading && results.length > 0 && (
          <div>
            <h3 className="text-secondary" style={{ marginBottom: '1rem', marginTop: '1rem' }}>Sources</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              {results.map((result, idx) => (
                <div key={idx} className="glass-panel" style={{ padding: '2rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                  <div className="flex justify-between items-center" style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem' }}>
                    <span className="text-accent" style={{ fontWeight: 600 }}>Score: {result.score.toFixed(3)}</span>
                    <span className="text-secondary" style={{ fontSize: '0.9rem' }}>
                      {result.source_type === 'web' ? `Web: ${result.title}` : `Doc: ${result.document_filename || result.document_id}`}
                    </span>
                  </div>
                  <p style={{ lineHeight: 1.6, color: 'var(--text-primary)' }}>
                    {result.content}
                  </p>
                  {result.source_type === 'web' && result.url && (
                    <a href={result.url} target="_blank" rel="noopener noreferrer" className="text-accent" style={{ fontSize: '0.9rem' }}>
                      {result.url}
                    </a>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {!loading && results.length === 0 && hasSearched && !error && (
          <p className="text-secondary text-center">No results found for "{query}".</p>
        )}
      </div>

    </div>
  );
}
