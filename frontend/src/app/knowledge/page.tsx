'use client';

import { useCallback, useEffect, useState } from 'react';
import { kis, type DocumentInfo, type KisConfig } from '@/lib/kis';

const ACCEPT = '.pdf,.docx,.txt,.md';

export default function KnowledgePage() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [config, setConfig] = useState<KisConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  const load = useCallback(
    () =>
      Promise.all([kis.documents(), kis.config()])
        .then(([d, c]) => {
          setDocs(d);
          setConfig(c);
        })
        .catch((err) => {
          setMessage({ kind: 'error', text: `Could not reach the backend: ${err instanceof Error ? err.message : err}` });
        })
        .finally(() => setLoading(false)),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  const loadDemo = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await kis.ingestDemo();
      const fresh = res.ingested.filter((i) => !i.duplicate).length;
      const errs = res.errors.map((e) => `${e.filename}: ${e.error}`).join('; ');
      setMessage({
        kind: res.errors.length ? 'error' : 'ok',
        text: `Demo corpus: ${fresh} new, ${res.ingested.length - fresh} already indexed.${errs ? ` Errors: ${errs}` : ''}`,
      });
      await load();
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Failed to load demo corpus' });
    } finally {
      setBusy(false);
    }
  };

  const upload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await kis.upload(file);
      setMessage({
        kind: 'ok',
        text: res.duplicate
          ? `${file.name} has identical content to an already indexed document (${res.document.filename}).`
          : `Indexed ${res.document.filename}: ${res.document.chunk_count} chunks.`,
      });
      setFile(null);
      await load();
    } catch (err) {
      setMessage({ kind: 'error', text: `Rejected: ${err instanceof Error ? err.message : 'upload failed'}` });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (doc: DocumentInfo) => {
    if (!confirm(`Remove ${doc.filename} from the index?`)) return;
    try {
      await kis.deleteDocument(doc.id);
      await load();
    } catch (err) {
      setMessage({ kind: 'error', text: err instanceof Error ? err.message : 'Delete failed' });
    }
  };

  const statusBadge = (s: string | null) =>
    s === 'effective' ? 'badge-success' : s === 'superseded' ? 'badge-warn' : 'badge-muted';

  return (
    <div className="animate-fade-in stack">
      <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: '1.9rem', marginBottom: '0.25rem' }}>Knowledge Base</h1>
          <p className="text-secondary" style={{ fontSize: '0.9rem' }}>
            Approved documents: PDF, DOCX, TXT and MD, up to 10 MB. Page, section and version metadata is kept for citations.
          </p>
        </div>
        <button className="btn btn-primary" onClick={loadDemo} disabled={busy}>
          {busy ? 'Working…' : 'Load demo corpus'}
        </button>
      </div>

      {message && <div className={`banner ${message.kind === 'ok' ? 'banner-info' : 'banner-danger'}`}>{message.text}</div>}

      <div className="detail-grid">
        <form onSubmit={upload} className="glass-panel panel stack" style={{ gap: '0.8rem' }}>
          <h2 className="section-title">Upload a document</h2>
          <input type="file" accept={ACCEPT} onChange={(e) => setFile(e.target.files?.[0] || null)} />
          <p className="muted" style={{ fontSize: '0.8rem' }}>
            Validation rejects unsupported types, empty or corrupted files, and scanned PDFs with no text layer. OCR is not enabled in
            this demo build. Try the files in <span className="mono">demo/samples/</span>.
          </p>
          <button type="submit" className="btn btn-primary" disabled={!file || busy}>Upload &amp; index</button>
        </form>

        <div className="glass-panel panel">
          <h2 className="section-title">Active pipeline</h2>
          {config ? (
            <dl className="kv">
              <dt>Embeddings</dt><dd className="mono">{config.embedder}</dd>
              <dt>Reranker</dt><dd className="mono">{config.reranker}</dd>
              <dt>Generator</dt><dd className="mono">{config.llm_model} ({config.llm_provider})</dd>
              <dt>Prompt template</dt><dd className="mono">{config.prompt_template_version}</dd>
              <dt>Indexed chunks</dt><dd>{config.indexed_chunks}</dd>
              <dt>SQL templates</dt><dd className="mono">{config.sql_templates.join(', ')}</dd>
            </dl>
          ) : (
            <p className="muted">{loading ? 'Loading…' : 'Unavailable'}</p>
          )}
        </div>
      </div>

      <div className="glass-panel panel">
        <h2 className="section-title">Indexed documents ({docs.length})</h2>
        {loading ? (
          <p className="muted animate-pulse">Loading documents…</p>
        ) : docs.length === 0 ? (
          <p className="text-secondary">No documents yet. Click <strong>Load demo corpus</strong> to index the synthetic policies, SOPs and manuals.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Doc ID</th><th>Title</th><th>Category</th><th>Version</th><th>Status</th>
                  <th>Effective</th><th>File</th><th>Pages</th><th>Chunks</th><th></th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.id}>
                    <td className="mono">{d.doc_id}</td>
                    <td>{d.title}</td>
                    <td>{d.category || '—'}</td>
                    <td>{d.version || '—'}</td>
                    <td><span className={`badge ${statusBadge(d.status)}`}>{d.status || 'unknown'}</span></td>
                    <td>{d.effective_date || '—'}</td>
                    <td className="mono" title={d.mime_type}>{d.filename}<div className="muted">{(d.size_bytes / 1024).toFixed(1)} KB</div></td>
                    <td>{d.pages ?? '—'}</td>
                    <td>{d.chunk_count}</td>
                    <td><button className="btn btn-secondary btn-sm" onClick={() => remove(d)}>Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
