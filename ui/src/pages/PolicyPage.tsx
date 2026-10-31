import { api } from '../api/client';
import { useAsync } from '../api/useAsync';
import { ErrorState, Loading, SegmentNameChip } from '../components/ui';

const stageColors = [
  { bg: 'var(--info-bg)', fg: 'var(--info)' },
  { bg: 'var(--warn-bg)', fg: 'var(--warn)' },
  { bg: 'var(--bad-bg)', fg: 'var(--bad)' },
];

export default function PolicyPage() {
  const { data: p, error, loading, reload } = useAsync(() => api.getPolicy());

  return (
    <>
      <header className="page-header">
        <div className="title-stack">
          <span className="eyebrow">Deterministic rules · versioned</span>
          <h1 className="page-title">Policy &amp; content</h1>
        </div>
        <div className="row">
          {p && (
            <span className="tag" style={{ fontSize: 13, padding: '8px 12px', color: 'var(--ink)' }}>
              {p.version} · live since {p.liveSince}
            </span>
          )}
          <button type="button" className="btn">
            Compare versions
          </button>
          <button type="button" className="btn btn-primary">
            Propose change
          </button>
        </div>
      </header>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !p && <Loading />}

      {p && (
        <>
          <section className="card flush" aria-labelledby="seg-h">
            <div className="card-head">
              <h2 id="seg-h" className="card-title">
                Segment definitions &amp; strategy mapping
              </h2>
              <span className="footnote">Inputs allowed: {p.allowedInputs}</span>
            </div>
            <div className="table-wrap">
              <table className="table compact" style={{ minWidth: 900 }}>
                <thead>
                  <tr>
                    <th scope="col">Segment</th>
                    <th scope="col">Rule</th>
                    <th scope="col">Objective</th>
                    <th scope="col">Tone</th>
                    <th scope="col">Template</th>
                  </tr>
                </thead>
                <tbody>
                  {p.segments.map((s) => (
                    <tr key={s.key}>
                      <td>
                        <SegmentNameChip segKey={s.key} label={s.name} />
                      </td>
                      <td className="mono" style={{ fontSize: 12, color: 'var(--ink-2)' }}>
                        {s.rule}
                      </td>
                      <td>{s.objective}</td>
                      <td>{s.tone}</td>
                      <td className="mono" style={{ fontSize: 12 }}>
                        {s.template}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div className="columns">
            <section className="card flush" style={{ flex: '3 1 520px', minWidth: 0 }} aria-labelledby="off-h">
              <div className="card-head">
                <h2 id="off-h" className="card-title">
                  Approved offers &amp; rewards
                </h2>
              </div>
              <div className="table-wrap">
                <table className="table compact" style={{ minWidth: 600 }}>
                  <thead>
                    <tr>
                      <th scope="col">Offer ID</th>
                      <th scope="col">Value</th>
                      <th scope="col">Eligibility</th>
                      <th scope="col">Expiry</th>
                      <th scope="col">Channel</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.offers.map((o) => (
                      <tr key={o.id}>
                        <td className="mono" style={{ fontWeight: 500 }}>
                          {o.id}
                        </td>
                        <td>{o.value}</td>
                        <td className="mono" style={{ fontSize: 12, color: 'var(--ink-2)' }}>
                          {o.eligibility}
                        </td>
                        <td>{o.expiry}</td>
                        <td>{o.channels}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="card" style={{ flex: '2 1 340px', minWidth: 0 }} aria-labelledby="rem-h">
              <h2 id="rem-h" className="card-title">
                Reminder progression
              </h2>
              <ol className="list-plain" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {p.reminderStages.map((s, i) => (
                  <li key={s.stage} className="stage">
                    <span className="stage-num" style={{ background: stageColors[i % 3].bg, color: stageColors[i % 3].fg }}>
                      {s.stage}
                    </span>
                    <div className="cell-stack" style={{ gap: 3 }}>
                      <span className="stage-name">{s.name}</span>
                      <span className="footnote">
                        {s.window} · {s.guidance}
                      </span>
                    </div>
                  </li>
                ))}
              </ol>
              <p style={{ fontSize: 12, color: 'var(--ink-2)', lineHeight: 1.6 }}>
                Every stage must include a support and dispute path. Stage 2+ is suppressed while a dispute is open.
              </p>
            </section>
          </div>

          <div className="columns">
            <section className="card" style={{ flex: '1 1 380px', minWidth: 0, gap: 12 }} aria-labelledby="disc-h">
              <h2 id="disc-h" className="card-title">
                Required disclaimers
              </h2>
              <ul className="list-plain" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {p.disclaimers.map((d) => (
                  <li key={d.id} className="disclaimer">
                    <span className="mono">{d.id}</span> · {d.text}
                  </li>
                ))}
              </ul>
            </section>

            <section className="card" style={{ flex: '1 1 380px', minWidth: 0, gap: 12 }} aria-labelledby="blk-h">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <h2 id="blk-h" className="card-title">
                  Blocked language
                </h2>
                <span className="footnote">
                  {p.blockedPhraseCount} phrases · {p.blockedPatternCount} patterns
                </span>
              </div>
              <div className="pills">
                {p.blockedPhrases.map((ph) => (
                  <span key={ph} className={'phrase' + (ph.startsWith('/') ? ' mono' : '')}>
                    {ph}
                  </span>
                ))}
              </div>
              <p style={{ fontSize: 12, color: 'var(--ink-2)' }}>Contact limits: {p.contactLimits}</p>
            </section>
          </div>
        </>
      )}
    </>
  );
}
