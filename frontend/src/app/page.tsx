import Link from 'next/link';

const FEATURES = [
  { title: 'Grounded answers', body: 'Answers come only from retrieved evidence. Every sentence cites a document page or section, or a SQL tool result.' },
  { title: 'Hybrid retrieval', body: 'Vector search plus BM25 keyword search, fused with Reciprocal Rank Fusion, then reranked. Exact IDs like ACR-2291 still match.' },
  { title: 'Safe by default', body: 'Gives an honest answer when evidence is missing, surfaces conflicting versions, and strips prompt injections from retrieved text.' },
  { title: 'Per-query observability', body: 'Every query is logged with stage timings, scores, citations, grounding, safety events, cost and feedback.' },
];

export default function Home() {
  return (
    <div className="animate-fade-in" style={{ paddingTop: '3rem' }}>
      <div className="text-center" style={{ marginBottom: '3rem' }}>
        <h1 className="hero-title">Enterprise Knowledge Intelligence Assistant</h1>
        <p className="text-secondary" style={{ fontSize: '1.15rem', maxWidth: 680, margin: '0 auto' }}>
          Ask questions about approved policies, SOPs and manuals, and about structured business data.
          Every answer comes with verifiable citations and a full audit trail.
        </p>
      </div>

      <div className="flex justify-center gap-4" style={{ flexWrap: 'wrap', marginBottom: '3rem' }}>
        <Link href="/assistant" className="btn btn-primary btn-lg">Ask the assistant</Link>
        <Link href="/knowledge" className="btn btn-secondary btn-lg">Knowledge base</Link>
        <Link href="/observability" className="btn btn-secondary btn-lg">Observability dashboard</Link>
      </div>

      <div className="feature-grid">
        {FEATURES.map((f) => (
          <div key={f.title} className="glass-panel" style={{ padding: '1.5rem' }}>
            <h3 style={{ marginBottom: '0.5rem', fontSize: '1.1rem' }}>{f.title}</h3>
            <p className="text-secondary" style={{ fontSize: '0.95rem' }}>{f.body}</p>
          </div>
        ))}
      </div>

      <p className="text-secondary text-center" style={{ marginTop: '2.5rem', fontSize: '0.85rem' }}>
        Demo build: all documents, people and figures are synthetic (fictional company &quot;Orion Synthetic Industries&quot;).
      </p>
    </div>
  );
}
