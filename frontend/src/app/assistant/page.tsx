'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AnswerCard } from '@/components/kis/AnswerCard';
import { kis, type ConfigId, type QueryResponse } from '@/lib/kis';

type Message =
  | { role: 'user'; text: string }
  | { role: 'assistant'; resp: QueryResponse }
  | { role: 'error'; text: string };

const EXAMPLES = [
  'What is the standard document retention period for business records?',
  'Who must approve ACR-3310?',
  'What is the PDA for international travel?',
  'What is the remaining budget of PRJ-1002 and does a USD 20,000 purchase on it need CFO approval?',
  'What are the deployment steps for Project Atlas?',
  'What is the parental leave entitlement?',
  'Show the vendor invoices for PRJ-1001.',
];

function newSessionId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function AssistantPage() {
  const [sessionId, setSessionId] = useState(newSessionId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [config, setConfig] = useState<ConfigId>('B');
  const [loading, setLoading] = useState(false);
  const [docCount, setDocCount] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    kis.documents().then((d) => setDocCount(d.length)).catch(() => setDocCount(null));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const ask = async (text: string) => {
    const q = text.trim();
    if (!q || loading) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', text: q }]);
    setLoading(true);
    try {
      const resp = await kis.query({ query: q, session_id: sessionId, config_id: config });
      setMessages((m) => [...m, { role: 'assistant', resp }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Request failed';
      setMessages((m) => [...m, { role: 'error', text: `${msg}. Is the backend running on port 8000?` }]);
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setMessages([]);
    setSessionId(newSessionId());
  };

  return (
    <div className="animate-fade-in stack" style={{ maxWidth: 920, margin: '0 auto' }}>
      <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: '1.9rem', marginBottom: '0.25rem' }}>Knowledge Assistant</h1>
          <p className="text-secondary" style={{ fontSize: '0.9rem' }}>
            Answers come only from indexed documents and the approved SQL tool. Follow-up questions use the last 3 turns.
          </p>
        </div>
        <div className="row-wrap">
          <label className="text-secondary" style={{ fontSize: '0.85rem' }} htmlFor="cfg">Pipeline</label>
          <select id="cfg" className="select" value={config} onChange={(e) => setConfig(e.target.value as ConfigId)}>
            <option value="B">B · Hybrid + rerank</option>
            <option value="A">A · Vector only</option>
          </select>
          <button className="btn btn-secondary btn-sm" onClick={reset}>New conversation</button>
        </div>
      </div>

      {docCount === 0 && (
        <div className="banner banner-warn">
          No documents are indexed yet. <Link href="/knowledge" className="text-accent">Load the demo corpus</Link> first.
        </div>
      )}

      {messages.length === 0 && (
        <div className="glass-panel panel">
          <p className="text-secondary" style={{ marginBottom: '0.8rem' }}>Try one of the demo scenarios:</p>
          <div className="row-wrap">
            {EXAMPLES.map((ex) => (
              <button key={ex} className="chip" onClick={() => ask(ex)}>{ex}</button>
            ))}
          </div>
        </div>
      )}

      <div className="stack">
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="chat-msg chat-user">{m.text}</div>
          ) : m.role === 'assistant' ? (
            <AnswerCard key={m.resp.query_id} resp={m.resp} />
          ) : (
            <div key={i} className="banner banner-danger">{m.text}</div>
          ),
        )}
        {loading && (
          <div className="glass-panel chat-msg">
            <span className="animate-pulse text-secondary">Retrieving evidence, running tools and checking citations…</span>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
        className="flex gap-2"
        style={{ position: 'sticky', bottom: '1rem' }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about policies, SOPs, manuals, or project data (e.g. PRJ-1002)…"
          maxLength={2000}
          style={{ padding: '0.9rem 1.1rem', borderRadius: 12 }}
        />
        <button type="submit" className="btn btn-primary" disabled={loading || !input.trim()} style={{ borderRadius: 12, whiteSpace: 'nowrap' }}>
          {loading ? 'Thinking…' : 'Ask'}
        </button>
      </form>
    </div>
  );
}
