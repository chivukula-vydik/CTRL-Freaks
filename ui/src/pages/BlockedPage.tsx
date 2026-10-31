import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { useAsync } from '../api/useAsync';
import { Icon } from '../components/Icon';
import { ErrorState, Loading, SegmentChip } from '../components/ui';
import type { ReminderStep } from '../types';

const stepClass: Record<ReminderStep['state'], string> = {
  sent: 'text-ok',
  suppressed: 'text-warn',
  refused: 'text-bad',
  pending: 'muted',
};

export default function BlockedPage() {
  const { customerId = '' } = useParams();
  const { data: bc, error, loading, reload } = useAsync(() => api.getBlockedCase(customerId), [customerId]);
  const [ticket, setTicket] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading && !bc) return <Loading />;
  if (!bc)
    return (
      <div className="state">
        {customerId} is not blocked. <Link to="/">Back to queue</Link>
      </div>
    );

  async function escalate() {
    setBusy(true);
    try {
      const r = await api.escalate(customerId);
      setTicket(r.ticketId);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="crumbs">
        <Link to="/">Review queue</Link>
        <span aria-hidden="true">/</span>
        <span>{bc.customerId}</span>
      </div>

      <header className="row" style={{ gap: 14 }}>
        <h1 className="page-title mono" style={{ fontSize: 26 }}>
          {bc.customerId}
        </h1>
        <SegmentChip segment={bc.segment} showConfidence />
        <span className="badge badge-solid-bad">Blocked</span>
      </header>

      <div className="alert-refused" role="alert">
        <Icon name="alert" size={28} color="var(--bad-strong)" />
        <div>
          <h2>{bc.headline}</h2>
          <p>{bc.summary}</p>
        </div>
      </div>

      {ticket && (
        <div className="banner banner-info" role="status">
          <Icon name="check" size={20} strokeWidth={2.2} />
          <span>
            <strong>Escalated to Billing Operations.</strong> Ticket <span className="mono">{ticket}</span> opened with evidence attached; customer removed from
            reminder cadence until resolved.
          </span>
        </div>
      )}

      <div className="columns">
        <section className="col" style={{ flex: '2 1 520px' }} aria-labelledby="fail-h">
          <h2 id="fail-h" className="card-title">
            Failed checks
          </h2>

          {bc.failed.map((f) => (
            <article key={f.code} className="card">
              <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <h3 className="card-title">{f.title}</h3>
                <span className="mono" style={{ fontSize: 12, fontWeight: 500, color: 'var(--bad)' }}>
                  {f.code}
                </span>
              </div>

              {f.conflict && (
                <>
                  <div className="table-wrap">
                    <table className="table compact" style={{ minWidth: 440 }}>
                      <thead>
                        <tr>
                          <th scope="col">Field</th>
                          <th scope="col">{f.conflict.sourceALabel}</th>
                          <th scope="col">{f.conflict.sourceBLabel}</th>
                        </tr>
                      </thead>
                      <tbody className="mono">
                        {f.conflict.rows.map((r) => (
                          <tr key={r.field}>
                            <td style={{ fontFamily: 'var(--font-sans)' }}>{r.field}</td>
                            <td>{r.sourceA}</td>
                            <td style={{ color: 'var(--bad)', fontWeight: 500 }}>{r.sourceB}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p style={{ fontSize: 13, color: 'var(--ink-2)' }}>{f.conflict.policyNote}</p>
                </>
              )}

              {f.confidence && (
                <div className="row">
                  <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={f.confidence.value} aria-label="Classification confidence">
                    <div className="meter-fill" style={{ width: `${f.confidence.value * 100}%` }} />
                    <div className="meter-mark" style={{ left: `${f.confidence.threshold * 100}%` }} />
                  </div>
                  <span className="mono" style={{ fontSize: 13 }}>
                    {f.confidence.value.toFixed(2)} / min {f.confidence.threshold.toFixed(2)}
                  </span>
                </div>
              )}

              {f.description && <p style={{ fontSize: 13, lineHeight: 1.6, color: 'var(--ink-2)' }}>{f.description}</p>}
            </article>
          ))}

          <details className="card" style={{ padding: '16px 20px' }}>
            <summary>{bc.passed.length} checks passed</summary>
            <ul>
              {bc.passed.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </details>
        </section>

        <aside className="col" style={{ flex: '1 1 300px' }} aria-label="Next steps">
          <div className="card" style={{ gap: 12 }}>
            <h2 className="card-title">Reviewer options</h2>
            <button type="button" className="btn btn-primary btn-lg" onClick={escalate} disabled={busy || !!ticket}>
              {ticket ? 'Escalated' : 'Escalate to Billing Operations'}
            </button>
            <button type="button" className="btn" onClick={reload}>
              Request data refresh
            </button>
            <Link to="/" className="btn">
              Close without contact
            </Link>
            <button type="button" className="btn" disabled>
              Send — locked by guardrails
            </button>
          </div>

          <div className="card" style={{ gap: 12 }}>
            <h2 className="card-title">Delivery attempts</h2>
            {bc.attempts.map((a, i) => (
              <div key={i} className="attempt">
                <span className="mono" style={{ fontSize: 12, color: 'var(--bad)', fontWeight: 500 }}>
                  {a.at} · {a.outcome}
                </span>
                <span style={{ fontSize: 13 }}>{a.description}</span>
              </div>
            ))}
            <p className="footnote">Every refusal is written to the audit log with the failed rule IDs.</p>
          </div>

          <div className="card" style={{ gap: 10 }}>
            <h2 className="card-title">Reminder progression</h2>
            <ol className="list-plain step-list">
              {bc.progression.map((s) => (
                <li key={s.stage}>
                  <span>
                    {s.stage} · {s.label}
                  </span>
                  <span className={stepClass[s.state]} style={{ fontWeight: 500 }}>
                    {s.note}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </aside>
      </div>
    </>
  );
}
