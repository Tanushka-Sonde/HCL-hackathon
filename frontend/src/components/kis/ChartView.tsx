'use client';

import { useEffect, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { fetchAssetUrl, type ChartSpec } from '@/lib/kis';

// Distinguishable on the dark theme; series order is stable across charts.
export const SERIES_COLORS = ['#818cf8', '#34d399', '#fbbf24', '#f472b6'];

const compact = (v: number) =>
  Math.abs(v) >= 1_000_000 ? `${(v / 1_000_000).toFixed(1)}M` : Math.abs(v) >= 1000 ? `${Math.round(v / 1000)}k` : String(v);

/** A line or bar chart drawn from a validated spec (values come from sources). */
export function ChartView({ spec, height = 260 }: { spec: ChartSpec; height?: number }) {
  const data = spec.labels.map((label, i) => {
    const row: Record<string, string | number> = { label };
    for (const s of spec.series) row[s.name] = s.values[i];
    return row;
  });
  const common = (
    <>
      <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
      <XAxis dataKey="label" stroke="#a0a6b5" tick={{ fontSize: 12 }} />
      <YAxis stroke="#a0a6b5" tick={{ fontSize: 12 }} tickFormatter={compact} width={52} />
      <Tooltip
        contentStyle={{ background: '#1a1d24', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 8 }}
        formatter={(v) => (typeof v === 'number' ? v.toLocaleString() : String(v))}
      />
      {spec.series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
    </>
  );
  return (
    <figure className="chart-figure">
      {spec.title && <figcaption className="chart-title">{spec.title}</figcaption>}
      <ResponsiveContainer width="100%" height={height}>
        {spec.chart_type === 'line' ? (
          <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            {common}
            {spec.series.map((s, i) => (
              <Line key={s.name} type="monotone" dataKey={s.name} stroke={SERIES_COLORS[i % 4]} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            ))}
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            {common}
            {spec.series.map((s, i) => (
              <Bar key={s.name} dataKey={s.name} fill={SERIES_COLORS[i % 4]} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </figure>
  );
}

/** An authenticated image (chart, scanned page) loaded as a blob URL. */
export function AssetImage({ url, alt }: { url: string; alt: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let revoke: string | null = null;
    fetchAssetUrl(url)
      .then((u) => {
        revoke = u;
        setSrc(u);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Image unavailable'));
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [url]);
  if (error) return <p className="muted" style={{ fontSize: '0.85rem' }}>{error}</p>;
  if (!src) return <p className="muted animate-pulse" style={{ fontSize: '0.85rem' }}>Loading image…</p>;
  // eslint-disable-next-line @next/next/no-img-element -- blob URL from an authenticated fetch
  return <img src={src} alt={alt} className="asset-image" />;
}
