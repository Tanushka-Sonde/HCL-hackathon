'use client';

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { RequireAuth, usePageTitle } from '@/lib/auth';
import { kis, type ChunkRow, type DocumentInfo, type KisConfig } from '@/lib/kis';

const ACCEPT = '.pdf,.docx,.txt,.md,.png,.jpg,.jpeg';

type Notice = { kind: 'ok' | 'error' | 'warn'; text: string };

export default function KnowledgePage() {
  return (
    <RequireAuth role="admin">
      <Knowledge />
    </RequireAuth>
  );
}

function Knowledge() {
  usePageTitle('Knowledge Base');
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [config, setConfig] = useState<KisConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [meta, setMeta] = useState({ category: '', version: '', status: '', effective_date: '' });
  const [notices, setNotices] = useState<Notice[]>([]);
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const [chunks, setChunks] = useState<ChunkRow[]>([]);

  const load = useCallback(
    () =>
      Promise.all([kis.documents(), kis.config()])
        .then(([d, c]) => {
          setDocs(d);
          setConfig(c);
        })
        .catch((err) => setNotices([{ kind: 'error', text: `Could not reach the backend: ${err instanceof Error ? err.message : err}` }]))
        .finally(() => setLoading(false)),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  // Success messages fade after a few seconds; errors stay until replaced.
  useEffect(() => {
    if (!notices.length || notices.some((n) => n.kind !== 'ok')) return;
    const t = setTimeout(() => setNotices([]), 6000);
    return () => clearTimeout(t);
  }, [notices]);

  const loadDemo = async () => {
    setBusy(true);
    setNotices([]);
    try {
      const res = await kis.ingestDemo();
      const fresh = res.ingested.filter((i) => !i.duplicate).length;
      const out: Notice[] = [{ kind: 'ok', text: `Demo corpus: ${fresh} new, ${res.ingested.length - fresh} already indexed.` }];
      for (const e of res.errors) out.push({ kind: 'error', text: `${e.filename}: ${e.error}` });
      for (const i of res.ingested) for (const w of i.warnings) out.push({ kind: 'warn', text: `${i.document.filename}: ${w}` });
      setNotices(out);
      await load();
    } catch (err) {
      setNotices([{ kind: 'error', text: err instanceof Error ? err.message : 'Failed to load demo corpus' }]);
    } finally {
      setBusy(false);
    }
  };

  const upload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setNotices([]);
    try {
      const res = await kis.upload(file, meta);
      const out: Notice[] = [
        {
          kind: 'ok',
          text: res.duplicate
            ? `${file.name} has the same content as ${res.document.filename}, which is already indexed.`
            : `Indexed ${res.document.filename} as ${res.document.doc_id}: ${res.document.chunk_count} chunks.`,
        },
      ];
      if (res.skipped_pages.length) out.push({ kind: 'warn', text: `Skipped pages: ${res.skipped_pages.join(', ')}.` });
      for (const w of res.warnings) out.push({ kind: 'warn', text: w });
      setNotices(out);
      setFile(null);
      await load();
    } catch (err) {
      setNotices([{ kind: 'error', text: `Rejected: ${err instanceof Error ? err.message : 'upload failed'}` }]);
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
      setNotices([{ kind: 'error', text: err instanceof Error ? err.message : 'Delete failed' }]);
    }
  };

  const toggleChunks = async (doc: DocumentInfo) => {
    if (openDoc === doc.id) return setOpenDoc(null);
    setOpenDoc(doc.id);
    setChunks([]);
    setChunks(await kis.chunks(doc.id).catch(() => []));
  };

  // Versions of one document sit together, newest first.
  const grouped = useMemo(() => {
    const byId = new Map<string, DocumentInfo[]>();
    for (const d of docs) byId.set(d.doc_id, [...(byId.get(d.doc_id) || []), d]);
    return [...byId.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .flatMap(([, list]) => list.sort((a, b) => (b.version || '').localeCompare(a.version || '', undefined, { numeric: true })));
  }, [docs]);

  const statusBadge = (s: string | null) => (s === 'effective' ? 'badge-success' : s === 'superseded' ? 'badge-warn' : 'badge-muted');
  const limit = config?.max_upload_mb ?? 20;

  return (
    <div className="animate-fade-in stack">
      <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
        <div>
          <h1 className="page-title">Knowledge Base</h1>
          <p className="text-secondary" style={{ fontSize: '0.9rem' }}>Approved documents. Page, section, version and status are kept for citations.</p>
        </div>
        <button className="btn btn-primary" onClick={loadDemo} disabled={busy}>{busy ? 'Working…' : 'Load demo corpus'}</button>
      </div>

      {notices.map((n, i) => (
        <div key={i} className={`banner ${n.kind === 'ok' ? 'banner-success' : n.kind === 'warn' ? 'banner-warn' : 'banner-danger'}`} role={n.kind === 'error' ? 'alert' : 'status'}>{n.text}</div>
      ))}

      <div className="detail-grid">
        <form onSubmit={upload} className="glass-panel panel stack" style={{ gap: '0.8rem' }}>
          <h2 className="section-title">Upload a document</h2>
          <label
            className={`drop-zone ${dragging ? 'dragging' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); setFile(e.dataTransfer.files?.[0] || null); }}
          >
            <input type="file" accept={ACCEPT} className="visually-hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            {file ? (
              <span><strong>{file.name}</strong> · {(file.size / 1_048_576).toFixed(2)} MB</span>
            ) : (
              <span>Drop a file here or <span className="text-accent">browse</span></span>
            )}
            <span className="muted" style={{ fontSize: '0.8rem' }}>PDF, DOCX, TXT, MD, PNG or JPG · up to {limit} MB</span>
          </label>
          <div className="advanced-grid">
            <label className="field"><span>Category</span><input value={meta.category} onChange={(e) => setMeta({ ...meta, category: e.target.value })} placeholder="from file header" maxLength={50} /></label>
            <label className="field"><span>Version</span><input value={meta.version} onChange={(e) => setMeta({ ...meta, version: e.target.value })} placeholder="e.g. 2.0" maxLength={20} /></label>
            <label className="field"><span>Status</span>
              <select className="select" value={meta.status} onChange={(e) => setMeta({ ...meta, status: e.target.value })}>
                <option value="">From file header</option><option value="effective">Effective</option><option value="superseded">Superseded</option><option value="draft">Draft</option>
              </select>
            </label>
            <label className="field"><span>Effective date</span><input type="date" value={meta.effective_date} onChange={(e) => setMeta({ ...meta, effective_date: e.target.value })} /></label>
          </div>
          <p className="muted" style={{ fontSize: '0.8rem' }}>
            Scanned pages, photos and handwriting are read by the vision model{config && !config.vision_enabled ? ' (not configured: set GROQ_API_KEY)' : ''}. Renamed or corrupted files are rejected.
          </p>
          <button type="submit" className="btn btn-primary" disabled={!file || busy}>Upload &amp; index</button>
        </form>

        <div className="glass-panel panel">
          <h2 className="section-title">Active pipeline</h2>
          {config ? (
            <dl className="kv">
              <dt>Embeddings</dt><dd className="mono">{config.embedder}</dd>
              <dt>Reranker</dt><dd className="mono">{config.reranker}</dd>
              <dt>Generator</dt><dd className="mono">{config.llm_model}</dd>
              <dt>Vision</dt><dd className="mono">{config.vision_enabled ? config.vision_model : 'off'}</dd>
              <dt>Prompt template</dt><dd className="mono">{config.prompt_template_version}</dd>
              <dt>Indexed chunks</dt><dd>{config.indexed_chunks}</dd>
              <dt>SQL templates</dt><dd className="mono">{config.sql_templates.join(', ')}</dd>
            </dl>
          ) : <p className="muted">{loading ? 'Loading…' : 'Unavailable'}</p>}
        </div>
      </div>

      <div className="glass-panel panel">
        <h2 className="section-title">Indexed documents ({docs.length})</h2>
        {loading ? <p className="muted animate-pulse">Loading documents…</p> : docs.length === 0 ? (
          <p className="text-secondary">No documents yet. Click <strong>Load demo corpus</strong> to index the synthetic policies, reports and records.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>Doc ID</th><th>Title</th><th>Version</th><th>Status</th><th className="hide-sm">Category</th><th className="hide-sm">File</th><th>Chunks</th><th className="hide-sm">Vision tokens</th><th><span className="visually-hidden">Actions</span></th></tr>
              </thead>
              <tbody>
                {grouped.map((d) => (
                  <Fragment key={d.id}>
                    <tr>
                      <td className="mono nowrap">{d.doc_id}</td>
                      <td>{d.title}</td>
                      <td>{d.version ? `v${d.version}` : '—'}</td>
                      <td><span className={`badge ${statusBadge(d.status)}`}>{d.status || 'unknown'}</span></td>
                      <td className="hide-sm">{d.category || '—'}</td>
                      <td className="hide-sm mono" title={d.mime_type}>{d.filename}<div className="muted">{(d.size_bytes / 1024).toFixed(1)} KB{d.pages ? ` · ${d.pages} p.` : ''}</div></td>
                      <td>
                        <button className="btn btn-secondary btn-sm" onClick={() => toggleChunks(d)} aria-expanded={openDoc === d.id}>{d.chunk_count} {openDoc === d.id ? '▲' : '▼'}</button>
                      </td>
                      <td className="hide-sm">{d.vision_input_tokens + d.vision_output_tokens || '—'}</td>
                      <td><button className="btn btn-secondary btn-sm" onClick={() => remove(d)} aria-label={`Remove ${d.filename}`}>Remove</button></td>
                    </tr>
                    {openDoc === d.id && (
                      <tr>
                        <td colSpan={9}>
                          {chunks.length === 0 ? <p className="muted animate-pulse">Loading chunks…</p> : (
                            <div className="stack" style={{ gap: '0.5rem' }}>
                              {chunks.map((c) => (
                                <div key={c.id} className="evidence-box">
                                  <div className="row-wrap" style={{ marginBottom: '0.3rem' }}>
                                    <strong>#{c.chunk_index}</strong>
                                    <span className="badge badge-muted">{c.content_type}</span>
                                    <span className="muted">{c.page ? `page ${c.page}` : ''}{c.section ? ` · ${c.section}` : ''} · {c.source_method}</span>
                                  </div>
                                  {c.content.length > 600 ? `${c.content.slice(0, 600)}…` : c.content}
                                </div>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
