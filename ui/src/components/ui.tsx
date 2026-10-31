import type { ReactNode } from 'react';
import type { CheckResult, QueueStatus, SegmentAssignment, SegmentKey } from '../types';
import { Icon } from './Icon';

export function SegmentChip({ segment, showConfidence = false }: { segment: SegmentAssignment; showConfidence?: boolean }) {
  return (
    <span className={`chip chip-${segment.key}`}>
      {segment.label}
      {showConfidence && ` · ${segment.confidence.toFixed(2)}`}
    </span>
  );
}

export function SegmentNameChip({ segKey, label }: { segKey: SegmentKey; label: string }) {
  return <span className={`chip chip-${segKey}`}>{label}</span>;
}

const segColor: Record<SegmentKey, string> = {
  loyalty: 'var(--seg-loyalty-fg)',
  consistent: 'var(--seg-consistent-fg)',
  declining: 'var(--seg-declining-fg)',
  dormant: 'var(--seg-dormant-fg)',
  payment: 'var(--seg-payment-fg)',
};

export function ConfidenceBar({ segment }: { segment: SegmentAssignment }) {
  const pct = Math.round(segment.confidence * 100);
  return (
    <div className="conf">
      <div
        className="conf-track"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={`Confidence ${segment.confidence.toFixed(2)}`}
      >
        <div className="conf-fill" style={{ width: `${pct}%`, background: segColor[segment.key] }} />
      </div>
      <span className="mono" style={{ fontSize: 13 }}>
        {segment.confidence.toFixed(2)}
      </span>
    </div>
  );
}

const statusMap: Record<QueueStatus, { label: string; cls: string }> = {
  ready: { label: 'Ready for review', cls: 'badge-info' },
  attention: { label: 'Needs attention', cls: 'badge-warn' },
  blocked: { label: 'Blocked', cls: 'badge-bad' },
  approved: { label: 'Approved · mock outbox', cls: 'badge-ok' },
  rejected: { label: 'Rejected', cls: 'badge-neutral' },
};

export function StatusBadge({ status }: { status: QueueStatus }) {
  const s = statusMap[status];
  return <span className={`badge ${s.cls}`}>{s.label}</span>;
}

export function CheckIcon({ result }: { result: CheckResult }) {
  if (result === 'pass') return <Icon name="check" color="var(--ok-mark)" strokeWidth={2.4} style={{ marginTop: 1 }} />;
  if (result === 'warn') return <Icon name="warn" color="var(--warn)" strokeWidth={2.2} style={{ marginTop: 1 }} />;
  return <Icon name="x" color="var(--bad-strong)" strokeWidth={2.4} style={{ marginTop: 1 }} />;
}

export function StatCard({ label, value, note, small, tone }: { label: string; value: ReactNode; note?: string; small?: boolean; tone?: 'bad' }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={'stat-value' + (small ? ' small' : '')} style={tone === 'bad' ? { color: 'var(--bad-strong)' } : undefined}>
        {value}
      </span>
      {note && <span className="stat-note">{note}</span>}
    </div>
  );
}

export function Loading() {
  return <div className="state">Loading…</div>;
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="state" role="alert">
      <p>Could not load data: {error.message}</p>
      {onRetry && (
        <button type="button" className="btn btn-sm" onClick={onRetry} style={{ marginTop: 12 }}>
          Retry
        </button>
      )}
    </div>
  );
}
