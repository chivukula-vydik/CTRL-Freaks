import { api } from '../api/client';
import { useAsync } from '../api/useAsync';
import { ErrorState, Loading, StatCard } from '../components/ui';
import type { AuditEvent } from '../types';

const sendBadge: Record<AuditEvent['sendStatus'], { label: string; cls: string }> = {
  awaiting: { label: 'Awaiting review', cls: 'badge-info' },
  blocked: { label: 'Blocked', cls: 'badge-bad' },
  mock_outbox: { label: 'Mock outbox', cls: 'badge-ok' },
  not_sent: { label: 'Not sent', cls: 'badge-neutral' },
  regenerated: { label: 'Regenerated', cls: 'badge-warn' },
};

function cellClass(row: number, col: number, v: number) {
  if (row === col) return v >= 9 ? 'cell-hit' : 'cell-hit-soft';
  return v > 0 ? 'cell-miss' : 'cell-zero';
}

export default function AuditPage() {
  const evalQ = useAsync(() => api.getEvaluation());
  const auditQ = useAsync(() => api.getAudit());
  const ev = evalQ.data;
  const log = auditQ.data;

  function exportReport() {
    const blob = new Blob([JSON.stringify({ evaluation: ev, audit: log }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'evaluation-report.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <header className="page-header">
        <div className="title-stack">
          <span className="eyebrow">Labelled synthetic scenarios{ev ? ` · n = ${ev.sampleSize}` : ''}</span>
          <h1 className="page-title">Audit &amp; evaluation</h1>
        </div>
        <button type="button" className="btn" onClick={exportReport} disabled={!ev || !log}>
          Export evaluation report
        </button>
      </header>

      {evalQ.error && <ErrorState error={evalQ.error} onRetry={evalQ.reload} />}
      {evalQ.loading && !ev && <Loading />}

      {ev && (
        <>
          <section className="stats" aria-label="Evaluation summary">
            <StatCard
              label="Classification accuracy"
              value={`${Math.round((ev.accuracy.correct / ev.accuracy.total) * 100)}%`}
              note={`${ev.accuracy.correct} of ${ev.accuracy.total} labelled`}
            />
            <StatCard
              label="Grounded spans"
              value={`${ev.grounded.matched} / ${ev.grounded.total}`}
              note={`${ev.grounded.caughtPreReview} caught by validator pre-review`}
            />
            <StatCard label="Policy compliance at send" value={`${Math.round(ev.complianceAtSend * 100)}%`} note="0 non-compliant drafts released" />
            <StatCard
              label="Safety tests refused"
              value={`${ev.safetyRefusals.refused} / ${ev.safetyRefusals.total}`}
              note="Missing evidence, ineligible, conflicts"
            />
          </section>

          <div className="columns">
            <section className="card" style={{ flex: '3 1 520px', minWidth: 0 }} aria-labelledby="cm-h">
              <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
                <h2 id="cm-h" className="card-title">
                  Confusion matrix
                </h2>
                <span className="footnote">Rows: labelled · Columns: predicted</span>
              </div>
              <div className="table-wrap">
                <table className="matrix" style={{ minWidth: 560 }}>
                  <thead>
                    <tr>
                      <th scope="col">
                        <span className="sr-only">Labelled segment</span>
                      </th>
                      {ev.labels.map((l) => (
                        <th key={l} scope="col">
                          {l}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ev.confusion.map((row, i) => (
                      <tr key={ev.labels[i]}>
                        <th scope="row">{ev.labels[i]}</th>
                        {row.map((v, j) => (
                          <td key={j} className={cellClass(i, j, v)}>
                            {v}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p style={{ fontSize: 13, color: 'var(--ink-2)', lineHeight: 1.6 }}>
                Confusion stays between neighbouring engagement strategies (declining ↔ dormant). No payment-reminder case was mistaken for an offer segment or
                the reverse.
              </p>
            </section>

            <section className="card" style={{ flex: '2 1 340px', minWidth: 0, gap: 12 }} aria-labelledby="sc-h">
              <h2 id="sc-h" className="card-title">
                Scenario coverage
              </h2>
              <ul className="list-plain">
                {ev.scenarios.map((s) => (
                  <li key={s.name} className="scenario">
                    <span>{s.name}</span>
                    <span className={s.ok ? 'text-ok' : 'text-bad'} style={{ fontWeight: 500 }}>
                      {s.result}
                    </span>
                  </li>
                ))}
              </ul>
              <div className="cell-stack" style={{ gap: 4, paddingTop: 4 }}>
                <span className="muted" style={{ fontSize: 13 }}>
                  Reviewer rubric average
                </span>
                <span className="mono" style={{ fontSize: 18, fontWeight: 500 }}>
                  {ev.rubricAverage} / 5 · {ev.edits} edits, {ev.rejections} rejections
                </span>
              </div>
            </section>
          </div>
        </>
      )}

      <section className="card flush" aria-labelledby="log-h">
        <div className="card-head">
          <h2 id="log-h" className="card-title">
            Audit log
          </h2>
          <span className="footnote">Personal data redacted · evidence stored as field names and hashes</span>
        </div>
        {auditQ.error && <ErrorState error={auditQ.error} onRetry={auditQ.reload} />}
        {log && (
          <div className="table-wrap">
            <table className="table compact" style={{ minWidth: 980 }}>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Customer</th>
                  <th scope="col">Event</th>
                  <th scope="col">Versions</th>
                  <th scope="col">Policy decision</th>
                  <th scope="col">Send status</th>
                </tr>
              </thead>
              <tbody>
                {log.map((e, i) => (
                  <tr key={i}>
                    <td className="mono" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
                      {e.at}
                    </td>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {e.customerId}
                    </td>
                    <td>{e.event}</td>
                    <td className="mono" style={{ fontSize: 12, color: 'var(--ink-2)' }}>
                      {e.versions}
                    </td>
                    <td>{e.policyDecision}</td>
                    <td>
                      <span className={`badge badge-sm ${sendBadge[e.sendStatus].cls}`}>{sendBadge[e.sendStatus].label}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
