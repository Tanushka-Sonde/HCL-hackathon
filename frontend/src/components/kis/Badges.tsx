import type { Outcome } from '@/lib/kis';

const OUTCOME_CLASS: Record<Outcome, string> = {
  success: 'badge-success',
  partial: 'badge-warn',
  failed: 'badge-danger',
};

const OUTCOME_LABEL: Record<Outcome, string> = {
  success: 'Success',
  partial: 'Partial / Fallback',
  failed: 'Failed',
};

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return <span className={`badge ${OUTCOME_CLASS[outcome]}`}>{OUTCOME_LABEL[outcome]}</span>;
}

export function ReasonBadges({ reasons, flags = [] }: { reasons: string[]; flags?: string[] }) {
  return (
    <>
      {reasons.filter((r) => r !== 'OK').map((r) => (
        <span key={r} className="badge badge-muted mono">{r}</span>
      ))}
      {flags.map((f) => (
        <span key={f} className="badge badge-info mono">{f}</span>
      ))}
    </>
  );
}

export function StatusDot({ status }: { status: string | null | undefined }) {
  const s = status || 'n/a';
  const cls =
    s === 'ok' || s === 'success' ? 'badge-success'
      : s === 'error' || s === 'failed' ? 'badge-danger'
        : s === 'fallback' || s === 'partial' ? 'badge-warn'
          : 'badge-muted';
  return <span className={`badge ${cls}`}>{s}</span>;
}
