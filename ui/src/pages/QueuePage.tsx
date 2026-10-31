import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useAsync } from '../api/useAsync';
import { Icon } from '../components/Icon';
import { ConfidenceBar, ErrorState, Loading, SegmentChip, StatCard, StatusBadge } from '../components/ui';
import type { QueueItem, SegmentKey } from '../types';

const filters: { key: SegmentKey | 'all'; label: string }[] = [
  { key: 'all', label: 'All segments' },
  { key: 'loyalty', label: 'Loyalty candidate' },
  { key: 'consistent', label: 'Consistent' },
  { key: 'declining', label: 'Declining activity' },
  { key: 'dormant', label: 'Dormant' },
  { key: 'payment', label: 'Payment reminder' },
];

function checksClass(item: QueueItem) {
  if (item.status === 'blocked') return 'text-bad';
  if (item.checksPassed < item.checksTotal) return 'text-warn';
  return 'text-ok';
}

export default function QueuePage() {
  const { data, error, loading, reload } = useAsync(() => api.getQueue());
  const [filter, setFilter] = useState<SegmentKey | 'all'>('all');
  const [query, setQuery] = useState('');

  const rows = useMemo(() => {
    if (!data) return [];
    return data.items.filter(
      (i) =>
        (filter === 'all' || i.primarySegment.key === filter) &&
        i.customerId.toLowerCase().includes(query.trim().toLowerCase()),
    );
  }, [data, filter, query]);

  return (
    <>
      <header className="page-header">
        <div className="title-stack">
          <span className="eyebrow">Human review required before any send</span>
          <h1 className="page-title">Review queue</h1>
        </div>
        <div className="row">
          <label className="search">
            <Icon name="search" size={16} />
            <span className="sr-only">Search customers</span>
            <input type="search" placeholder="Search by customer ID" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <button type="button" className="btn btn-primary" onClick={() => api.generate().then(reload).catch(alert)}>
            Classify new batch
          </button>
        </div>
      </header>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}

      {data && (
        <>
          <section className="stats" aria-label="Queue summary">
            <StatCard label="Awaiting review" value={data.summary.awaitingReview} />
            <StatCard label="Blocked by guardrails" value={data.summary.blocked} tone="bad" />
            <StatCard label="Approved to mock outbox" value={data.summary.approved} />
            <StatCard label="Active policy" value={`${data.summary.policyVersion} · ${data.summary.templateVersion}`} small />
          </section>

          <div className="pills" role="group" aria-label="Filter by segment">
            {filters.map((f) => {
              const count = f.key === 'all' ? data.items.length : data.items.filter((i) => i.primarySegment.key === f.key).length;
              return (
                <button key={f.key} type="button" className="pill" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                  {f.label} · {count}
                </button>
              );
            })}
          </div>

          <section className="card flush" aria-label="Customers awaiting review">
            <div className="table-wrap">
              <table className="table" style={{ minWidth: 960 }}>
                <thead>
                  <tr>
                    <th scope="col">Customer</th>
                    <th scope="col">Segment</th>
                    <th scope="col">Confidence</th>
                    <th scope="col">Strategy &amp; tone</th>
                    <th scope="col">Checks</th>
                    <th scope="col">Status</th>
                    <th scope="col">
                      <span className="sr-only">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const blocked = r.status === 'blocked';
                    return (
                      <tr key={r.customerId}>
                        <td>
                          <div className="cell-stack">
                            <span className="mono" style={{ fontWeight: 500 }}>
                              {r.customerId}
                            </span>
                            <span className="cell-sub">{r.planSummary}</span>
                          </div>
                        </td>
                        <td>
                          <SegmentChip segment={r.primarySegment} />
                        </td>
                        <td>
                          <ConfidenceBar segment={r.primarySegment} />
                        </td>
                        <td>
                          <div className="cell-stack">
                            <span>{r.strategy}</span>
                            <span className="cell-sub">{r.tone}</span>
                          </div>
                        </td>
                        <td className="mono" style={{ fontSize: 13, whiteSpace: 'nowrap' }}>
                          <span className={checksClass(r)}>
                            {r.checksPassed} / {r.checksTotal} {r.checksNote ? `· ${r.checksNote}` : 'pass'}
                          </span>
                        </td>
                        <td>
                          <StatusBadge status={r.status} />
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          <Link className="btn btn-sm" to={blocked ? `/blocked/${r.customerId}` : `/review/${r.customerId}`}>
                            {blocked ? 'See why' : r.status === 'approved' || r.status === 'rejected' ? 'View' : 'Review'}
                          </Link>
                        </td>
                      </tr>
                    );
                  })}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={7} className="state">
                        No customers match this filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
          <p className="footnote">
            Segments are assigned from activity, loyalty, active-plan and on-time-payment indicators only. Protected characteristics and proxy
            attributes are excluded from the feature set.
          </p>
        </>
      )}
    </>
  );
}
