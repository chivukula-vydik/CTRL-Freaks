import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { useAsync } from '../api/useAsync';
import { Icon } from '../components/Icon';
import { CheckIcon, ErrorState, Loading, SegmentChip } from '../components/ui';
import type { DecisionResult, EmailDraft, RubricKey, ValidationCheck } from '../types';

const rubricLabels: [RubricKey, string][] = [
  ['relevance', 'Relevance'],
  ['clarity', 'Clarity'],
  ['personalization', 'Personalization'],
  ['cta', 'Call to action'],
  ['tone', 'Tone fit'],
];

/** Flattens the span model into editable plain text. */
function draftToText(d: EmailDraft) {
  return d.paragraphs.map((p) => p.spans.map((s) => s.text).join('')).join('\n\n');
}

export default function ReviewPage() {
  const { customerId = '' } = useParams();
  const { data: rc, error, loading, reload } = useAsync(() => api.getReviewCase(customerId), [customerId]);

  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [edited, setEdited] = useState(false);
  const [checks, setChecks] = useState<ValidationCheck[]>([]);
  const [revalidating, setRevalidating] = useState(false);
  const [rubric, setRubric] = useState<Record<RubricKey, number>>({ relevance: 5, clarity: 4, personalization: 5, cta: 4, tone: 5 });
  const [feedback, setFeedback] = useState('');
  const [decision, setDecision] = useState<{ action: 'approve' | 'reject'; result: DecisionResult } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!rc) return;
    setSubject(rc.draft.subject);
    setBody(draftToText(rc.draft));
    setChecks(rc.checks);
    setEdited(false);
    setEditing(false);
    setDecision(null);
    setFeedback('');
  }, [rc]);

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading && !rc) return <Loading />;
  if (!rc)
    return (
      <div className="state">
        No reviewable draft for {customerId}. <Link to="/">Back to queue</Link>
      </div>
    );

  const failed = checks.filter((c) => c.result === 'fail').length;
  const warned = checks.filter((c) => c.result === 'warn').length;
  const passed = checks.length - failed - warned;
  const canApprove = failed === 0 && !editing && !revalidating && !decision;

  async function finishEditing() {
    setEditing(false);
    setRevalidating(true);
    try {
      setChecks(await api.revalidate(customerId, subject, body));
    } finally {
      setRevalidating(false);
    }
  }

  async function decide(action: 'approve' | 'reject') {
    setSubmitting(true);
    try {
      const result = await api.submitDecision({
        customerId,
        action,
        editedSubject: edited ? subject : undefined,
        editedBody: edited ? body : undefined,
        rubric,
        feedback,
      });
      setDecision({ action, result });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      <div className="crumbs">
        <Link to="/">Review queue</Link>
        <span aria-hidden="true">/</span>
        <span>{customerId}</span>
      </div>

      <header className="page-header" style={{ alignItems: 'center' }}>
        <div className="row" style={{ gap: 14 }}>
          <h1 className="page-title mono" style={{ fontSize: 26 }}>
            {rc.customerId}
          </h1>
          {rc.segments.map((s) => (
            <SegmentChip key={s.key} segment={s} showConfidence />
          ))}
        </div>
        <div className="row" style={{ gap: 8 }}>
          <span className="tag">
            model: {rc.modelInfo.model} · temp {rc.modelInfo.temperature}
          </span>
          <span className="tag">{rc.modelInfo.templateVersion}</span>
          <span className="tag">{rc.modelInfo.policyVersion}</span>
        </div>
      </header>

      {decision?.action === 'approve' && (
        <div className="banner banner-ok" role="status">
          <Icon name="check" size={20} strokeWidth={2.2} />
          <span>
            <strong>Approved by reviewer.</strong> Draft queued to the mock outbox · audit event <span className="mono">{decision.result.auditEventId}</span>{' '}
            recorded.
          </span>
        </div>
      )}
      {decision?.action === 'reject' && (
        <div className="banner banner-bad" role="status">
          <Icon name="x" size={20} strokeWidth={2.2} />
          <span>
            <strong>Rejected.</strong> Nothing will be sent. Feedback stored with the draft for evaluation · audit event{' '}
            <span className="mono">{decision.result.auditEventId}</span>.
          </span>
        </div>
      )}

      <div className="columns">
        {/* ---------------- evidence column ---------------- */}
        <section className="col" style={{ flex: '1 1 300px' }} aria-labelledby="ev-h">
          <div className="card">
            <h2 id="ev-h" className="card-title">
              Customer evidence
            </h2>
            <dl className="kv-grid">
              {rc.evidence.map((e) => (
                <div key={e.key}>
                  <dt>{e.label}</dt>
                  <dd>{e.value}</dd>
                </div>
              ))}
            </dl>
            <p className="footnote divider-top">
              Only permitted fields are loaded. Name is used for greeting only; no address, phone or ID fields reach the model.
            </p>
          </div>

          <div className="card">
            <h2 className="card-title">Why this segment</h2>
            <ul className="list-plain">
              {rc.reasons.map((r) => (
                <li key={r.code} className="reason">
                  <span className="reason-code">{r.code}</span>
                  <span className="reason-text">{r.text}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h2 className="card-title">Selected strategy</h2>
            <div className="kv-grid">
              <div className="kv">
                <span className="muted">Objective</span>
                <span className="v">{rc.strategy.objective}</span>
              </div>
              <div className="kv">
                <span className="muted">Tone rule</span>
                <span className="v">{rc.strategy.toneRule}</span>
              </div>
              <div className="kv">
                <span className="muted">Offer</span>
                <span className="v mono">{rc.strategy.offerId ?? 'None'}</span>
              </div>
              <div className="kv">
                <span className="muted">Channel</span>
                <span className="v">{rc.strategy.channel}</span>
              </div>
            </div>
          </div>
        </section>

        {/* ---------------- draft column ---------------- */}
        <section className="card flush" style={{ flex: '2 1 460px', minWidth: 0 }} aria-labelledby="draft-h">
          <div className="card-head">
            <h2 id="draft-h" className="card-title">
              Generated email draft {edited && <span className="badge badge-sm badge-warn" style={{ marginLeft: 8 }}>Edited by reviewer</span>}
            </h2>
            <div className="legend">
              <span>
                <span className="legend-swatch span-grounded" />
                Grounded in evidence
              </span>
              <span>
                <span className="legend-swatch para-policy" style={{ padding: 0 }} />
                Policy-controlled block
              </span>
            </div>
          </div>

          <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="field">
              <label htmlFor="subj" className="field-label">
                Subject
              </label>
              <input
                id="subj"
                className="input"
                value={subject}
                readOnly={!editing}
                onChange={(e) => {
                  setSubject(e.target.value);
                  setEdited(true);
                }}
              />
            </div>

            {editing ? (
              <div className="field">
                <label htmlFor="body-edit" className="field-label">
                  Body · editing
                </label>
                <textarea
                  id="body-edit"
                  className="textarea editing"
                  rows={16}
                  value={body}
                  onChange={(e) => {
                    setBody(e.target.value);
                    setEdited(true);
                  }}
                />
                <span className="text-warn" style={{ fontSize: 12, fontWeight: 400 }}>
                  Edits re-run all {checks.length} checks before approval is allowed.
                </span>
              </div>
            ) : (
              <div className="field">
                <span className="field-label">Body</span>
                {edited ? (
                  <div className="email-body">
                    {body.split(/\n{2,}/).map((p, i) => (
                      <p key={i}>{p}</p>
                    ))}
                  </div>
                ) : (
                  <div className="email-body">
                    {rc.draft.paragraphs.map((p, i) => (
                      <p key={i} className={p.kind === 'policy' ? 'para-policy' : p.kind === 'footer' ? 'para-footer' : undefined}>
                        {p.spans.map((s, j) =>
                          s.kind === 'grounded' ? (
                            <span key={j} className="span-grounded" title={s.evidenceKey ? `Evidence: ${s.evidenceKey}` : undefined}>
                              {s.text}
                            </span>
                          ) : (
                            <span key={j}>{s.text}</span>
                          ),
                        )}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="mini-stats">
              <div className="mini-stat">
                <span className="muted">Grounded spans</span>
                <span className="v">
                  {rc.draft.groundedMatched} / {rc.draft.groundedSpans} matched
                </span>
              </div>
              <div className="mini-stat">
                <span className="muted">Unsupported claims</span>
                <span className="v">{rc.draft.unsupportedClaims}</span>
              </div>
              <div className="mini-stat">
                <span className="muted">Reading level</span>
                <span className="v">{rc.draft.readingLevel}</span>
              </div>
            </div>
          </div>
        </section>

        {/* ---------------- validation + decision column ---------------- */}
        <aside className="col" style={{ flex: '1 1 300px' }} aria-label="Validation and decision">
          <div className="card" style={{ gap: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 className="card-title">Validation results</h2>
              <span className={'mono ' + (failed ? 'text-bad' : warned ? 'text-warn' : 'text-ok')} style={{ fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap' }}>
                {revalidating ? 'Re-checking…' : `${passed} / ${checks.length} pass${warned ? ` · ${warned} warn` : ''}${failed ? ` · ${failed} fail` : ''}`}
              </span>
            </div>
            <ul className="list-plain" aria-busy={revalidating}>
              {checks.map((c) => (
                <li key={c.id} className="check">
                  <CheckIcon result={c.result} />
                  <div className="cell-stack">
                    <span className="check-name">{c.name}</span>
                    <span className="check-detail">{c.detail}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h2 className="card-title">Reviewer rubric</h2>
            {rubricLabels.map(([key, label]) => (
              <div key={key} className="rubric-row" role="group" aria-label={label}>
                <span style={{ fontSize: 13 }}>{label}</span>
                <div className="rubric-scores">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      type="button"
                      className="score"
                      aria-pressed={rubric[key] === n}
                      aria-label={`${label} ${n} of 5`}
                      onClick={() => setRubric((r) => ({ ...r, [key]: n }))}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            <label htmlFor="fb" style={{ fontSize: 13, fontWeight: 500, paddingTop: 4 }}>
              Feedback for the model team
            </label>
            <textarea
              id="fb"
              className="textarea"
              rows={3}
              placeholder="What should change in tone, facts or offer?"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              style={{ fontSize: 13 }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <button type="button" className="btn btn-primary btn-lg" disabled={!canApprove || submitting} onClick={() => decide('approve')}>
              {failed ? 'Approval locked · fix failed checks' : 'Approve & queue to mock outbox'}
            </button>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
              <button
                type="button"
                className="btn"
                disabled={!!decision || revalidating}
                onClick={() => (editing ? finishEditing() : setEditing(true))}
              >
                {editing ? 'Done editing' : 'Edit draft'}
              </button>
              <button type="button" className="btn btn-danger" disabled={!!decision || submitting} onClick={() => decide('reject')}>
                Reject
              </button>
            </div>
            <p className="footnote">Approval releases this one draft only. Bulk or unsupervised sending is disabled.</p>
          </div>
        </aside>
      </div>
    </>
  );
}
