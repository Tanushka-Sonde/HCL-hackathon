'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AnswerCard } from '@/components/kis/AnswerCard';
import { RequireAuth, useAuth, usePageTitle } from '@/lib/auth';
import { kis, type ConfigId, type KisConfig, type QueryOptions, type QueryResponse } from '@/lib/kis';

type Message =
  | { role: 'user'; text: string; imageName?: string; imagePreview?: string }
  | { role: 'assistant'; resp: QueryResponse }
  | { role: 'error'; text: string; retry: { text: string } };

const SCENARIOS: { label: string; q: string }[] = [
  { label: 'Conflict', q: 'What is the standard document retention period for business records?' },
  { label: 'Exact ID', q: 'Who must approve ACR-3310?' },
  { label: 'Acronym', q: 'What is the PDA for international travel?' },
  { label: 'SQL + policy', q: 'What is the remaining budget of PRJ-1002 and does a USD 20,000 purchase on it need CFO approval?' },
  { label: 'Table maths', q: 'What was the total profit (USD) of the last 5 months in the Monthly Profit and Loss Report 2026?' },
  { label: 'Chart', q: 'Plot the monthly profit (USD) from the Monthly Profit and Loss Report 2026' },
  { label: 'Personal data', q: 'What is the annual salary and email of Tom Becker?' },
  { label: 'Injection', q: 'What are the deployment steps for Project Atlas?' },
  { label: 'No evidence', q: 'What is the parental leave entitlement?' },
  { label: 'Tool failure', q: 'Show the vendor invoices for PRJ-1001.' },
];

const STAGES = ['Reading your question', 'Searching documents', 'Checking business data', 'Writing the answer', 'Checking citations'];
const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const MAX_IMAGE_MB = 10;
const TIMEOUT_MS = 90_000;

function newSessionId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function readSaved(key: string): { sessionId: string; messages: Message[] } | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null; // storage unavailable or corrupt: start fresh
  }
}

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    p,
    new Promise<T>((_, reject) => setTimeout(() => reject(new Error('The request took too long')), ms)),
  ]);
}

export default function AssistantPage() {
  return (
    <RequireAuth>
      <Assistant />
    </RequireAuth>
  );
}

function Assistant() {
  usePageTitle('Assistant');
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const storeKey = `kis-chat-${user?.id}`;

  // This component only mounts in the browser (after the sign-in check), so
  // the saved conversation can be read directly in the state initializers.
  const [saved] = useState(() => readSaved(storeKey));
  const [sessionId, setSessionId] = useState<string>(() => saved?.sessionId ?? newSessionId());
  const [messages, setMessages] = useState<Message[]>(() => saved?.messages ?? []);
  const [input, setInput] = useState('');
  const [image, setImage] = useState<File | null>(null);
  const [imageError, setImageError] = useState('');
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [config, setConfig] = useState<KisConfig | null>(null);
  const [pipeline, setPipeline] = useState<ConfigId>('B');
  const [maxIn, setMaxIn] = useState(3000);
  const [maxOut, setMaxOut] = useState(500);
  const [category, setCategory] = useState('');
  const [status, setStatus] = useState('');
  const endRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Keep the conversation when the user opens a trace or another page.
  useEffect(() => {
    try {
      const plain = messages.map((m) => (m.role === 'user' ? { ...m, imagePreview: undefined } : m));
      sessionStorage.setItem(storeKey, JSON.stringify({ sessionId, messages: plain }));
    } catch {
      /* ignore quota errors */
    }
  }, [messages, sessionId, storeKey]);

  useEffect(() => {
    kis.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, loading]);

  useEffect(() => {
    if (!loading) return;
    const start = Date.now();
    const t = setInterval(() => setElapsed(Date.now() - start), 250);
    return () => clearInterval(t);
  }, [loading]);

  const pickImage = (file: File | null) => {
    setImageError('');
    if (!file) return setImage(null);
    if (!IMAGE_TYPES.includes(file.type)) return setImageError('Attach a PNG, JPG or WEBP image.');
    if (file.size > MAX_IMAGE_MB * 1_048_576) return setImageError(`Images can be at most ${MAX_IMAGE_MB} MB.`);
    setImage(file);
  };

  const ask = useCallback(
    async (text: string) => {
      const q = text.trim();
      if ((!q && !image) || loading) return;
      const attached = image;
      setInput('');
      setImage(null);
      if (fileRef.current) fileRef.current.value = '';
      setMessages((m) => [
        ...m,
        { role: 'user', text: q || '(image only)', imageName: attached?.name, imagePreview: attached ? URL.createObjectURL(attached) : undefined },
      ]);
      setLoading(true);
      const opts: QueryOptions = {
        query: q,
        session_id: sessionId,
        config_id: isAdmin ? pipeline : undefined,
        max_input_tokens: maxIn,
        max_output_tokens: maxOut,
        category: category || undefined,
        status: status || undefined,
      };
      try {
        const resp = await withTimeout(attached ? kis.queryWithImage(opts, attached) : kis.query(opts), TIMEOUT_MS);
        setMessages((m) => [...m, { role: 'assistant', resp }]);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Request failed';
        setMessages((m) => [...m, { role: 'error', text: msg, retry: { text: q } }]);
      } finally {
        setLoading(false);
      }
    },
    [image, loading, sessionId, isAdmin, pipeline, maxIn, maxOut, category, status],
  );

  const reset = () => {
    setMessages([]);
    setSessionId(newSessionId());
  };

  const offline = config && !config.llm_provider.startsWith('groq');
  const stage = STAGES[Math.min(STAGES.length - 1, Math.floor(elapsed / 1200))];

  return (
    <div className={`assistant ${isAdmin ? '' : 'assistant-full'}`}>
      <div className="assistant-top row-wrap">
        <h1 className="assistant-title">Ask the knowledge assistant</h1>
        <div className="row-wrap" style={{ marginLeft: 'auto' }}>
          <details className="menu">
            <summary className="btn btn-secondary btn-sm">Try a scenario</summary>
            <div className="menu-list" role="menu">
              {SCENARIOS.map((s) => (
                <button key={s.label} role="menuitem" className="menu-item" onClick={(e) => { (e.currentTarget.closest('details') as HTMLDetailsElement).open = false; ask(s.q); }}>
                  <span className="badge badge-info">{s.label}</span> {s.q}
                </button>
              ))}
            </div>
          </details>
          <button className="btn btn-secondary btn-sm" onClick={reset}>New conversation</button>
        </div>
      </div>

      {isAdmin && offline && (
        <div className="banner banner-warn">
          Offline mode: no LLM is configured, so answers are built from source sentences and marked Partial. Set <span className="mono">GROQ_API_KEY</span> for full answers.
        </div>
      )}
      {config && config.indexed_chunks === 0 && (
        <div className="banner banner-warn">
          {isAdmin ? <>No documents are indexed yet. Load the demo corpus on the <a className="text-accent" href="/knowledge">Knowledge Base</a> page.</> : 'The knowledge base is empty. Ask an administrator to add documents.'}
        </div>
      )}

      <div className="chat-scroll stack" aria-live="polite">
        {messages.length === 0 && (
          <div className="glass-panel panel empty-chat">
            <p className="text-secondary">
              Ask about policies, procedures, manuals or project data. Answers come only from approved documents and business data, with sources you can open.
              You can attach an image, such as a photo of a note or a chart.
            </p>
            <div className="row-wrap" style={{ marginTop: '0.8rem' }}>
              {SCENARIOS.slice(0, 4).map((s) => (
                <button key={s.label} className="chip" onClick={() => ask(s.q)}><span className="badge badge-info">{s.label}</span> {s.q}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="chat-msg chat-user">
              {m.imagePreview && (
                // eslint-disable-next-line @next/next/no-img-element -- local preview of the user's own file
                <img src={m.imagePreview} alt={m.imageName || 'attached image'} className="user-image" />
              )}
              {m.imageName && !m.imagePreview && <div className="muted" style={{ fontSize: '0.8rem' }}>📎 {m.imageName}</div>}
              {m.text}
            </div>
          ) : m.role === 'assistant' ? (
            <AnswerCard key={m.resp.query_id} resp={m.resp} isAdmin={isAdmin} />
          ) : (
            <div key={i} className="banner banner-danger row-wrap" role="alert">
              <span>{m.text}.</span>
              {m.retry.text && <button className="btn btn-secondary btn-sm" onClick={() => ask(m.retry.text)}>Retry</button>}
            </div>
          ),
        )}
        {loading && (
          <div className="glass-panel chat-msg loading-msg" role="status">
            <span className="animate-pulse">{stage}…</span>
            <span className="muted mono">{(elapsed / 1000).toFixed(1)} s</span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div className="composer">
        <details className="advanced">
          <summary>Advanced</summary>
          <div className="advanced-grid">
            <label className="field"><span>Max input tokens</span>
              <input type="number" min={256} max={8000} step={100} value={maxIn} onChange={(e) => setMaxIn(Number(e.target.value) || 3000)} />
            </label>
            <label className="field"><span>Max output tokens</span>
              <input type="number" min={32} max={1500} step={50} value={maxOut} onChange={(e) => setMaxOut(Number(e.target.value) || 500)} />
            </label>
            <label className="field"><span>Category filter</span>
              <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="e.g. HR, Finance" maxLength={50} />
            </label>
            <label className="field"><span>Status filter</span>
              <select className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">Any</option><option value="effective">Effective</option><option value="superseded">Superseded</option><option value="draft">Draft</option>
              </select>
            </label>
            {isAdmin && (
              <label className="field"><span>Pipeline</span>
                <select className="select" value={pipeline} onChange={(e) => setPipeline(e.target.value as ConfigId)}>
                  <option value="B">B · Hybrid + rerank</option>
                  <option value="A">A · Vector only</option>
                </select>
              </label>
            )}
          </div>
          <p className="muted" style={{ fontSize: '0.78rem' }}>Token counts for the input budget are estimated (characters ÷ 4). The server caps them at 8,000 in / 1,500 out.</p>
        </details>
        {image && (
          <div className="attach-chip">
            📎 {image.name} <span className="muted">({(image.size / 1024).toFixed(0)} KB)</span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => { setImage(null); if (fileRef.current) fileRef.current.value = ''; }} aria-label="Remove image">✕</button>
          </div>
        )}
        {imageError && <div className="banner banner-danger" role="alert">{imageError}</div>}
        <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className="composer-row">
          <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg,.webp" hidden onChange={(e) => pickImage(e.target.files?.[0] || null)} />
          <button type="button" className="btn btn-secondary" onClick={() => fileRef.current?.click()} title="Attach an image (PNG, JPG, WEBP, up to 10 MB)" aria-label="Attach an image">📎</button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={image ? 'Ask about the attached image…' : 'Ask about policies, SOPs, manuals or project data (e.g. PRJ-1002)…'}
            aria-label="Your question"
            maxLength={2000}
          />
          <button type="submit" className="btn btn-primary" disabled={loading || (!input.trim() && !image)}>
            {loading ? 'Thinking…' : 'Ask'}
          </button>
        </form>
      </div>
    </div>
  );
}
