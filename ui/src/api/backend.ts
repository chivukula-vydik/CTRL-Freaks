/**
 * Adapter from the hcl-rag-agent backend (draft_id based, snake_case) to the console's types.
 * The console is keyed by customer id, so every call resolves the customer's latest draft first.
 * Policy / evaluation / audit list have no backend endpoint yet and stay on mock data (see client.ts).
 */
import type {
  BlockedCase,
  CheckResult,
  DecisionResult,
  DraftParagraph,
  DraftSpan,
  EvidenceField,
  QueueItem,
  QueueStatus,
  QueueSummary,
  ReviewCase,
  SegmentAssignment,
  SegmentKey,
  ValidationCheck,
} from '../types';

interface Issue { code: string; detail: string }
interface Checks { blocking: Issue[]; warnings: Issue[]; passed: boolean }
interface Seg { segment: string; confidence: number; reasons: string[] }
interface Draft {
  draft_id: string; customer_id: string; status: string; subject: string; body: string; trace_id: string;
  segments: { segments: Seg[]; primary: string | null; confidence: number } | null;
  strategy: { objective: string; tone: string; template: string; stage?: number } | null;
  facts: Record<string, unknown> | null; checks: Checks | null; offer_id: string | null;
  template_version: string; model: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, { headers: { 'Content-Type': 'application/json' }, ...init });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail).catch(() => '');
    throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}
const post = (body: unknown = {}): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

const SEGMENT: Record<string, { key: SegmentKey; label: string }> = {
  payment_reminder: { key: 'payment', label: 'Payment reminder' },
  dormant: { key: 'dormant', label: 'Dormant' },
  declining: { key: 'declining', label: 'Declining activity' },
  loyalty_candidate: { key: 'loyalty', label: 'Loyalty candidate' },
  consistent: { key: 'consistent', label: 'Consistent' },
};
const assign = (s: Seg): SegmentAssignment => ({ ...(SEGMENT[s.segment] ?? { key: 'consistent', label: s.segment }), confidence: s.confidence });
const words = (s: string) => s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

// the console shows 10 fixed checks; backend codes are folded into them
const CHECKS: { id: string; name: string; codes: string[] }[] = [
  { id: 'evidence', name: 'Evidence complete', codes: ['MISSING_EVIDENCE', 'NO_SEGMENT', 'CONTRADICTORY_DATA'] },
  { id: 'grounded', name: 'Facts grounded', codes: ['EMPTY_DRAFT', 'LLM_DRAFT_REJECTED'] },
  { id: 'invented', name: 'No invented amounts or dates', codes: ['UNSUPPORTED_NUMBER'] },
  { id: 'eligibility', name: 'Offer eligibility (deterministic)', codes: ['DISPUTED_INVOICE', 'UNKNOWN_OFFER'] },
  { id: 'offer_terms', name: 'Offer terms, expiry, channel', codes: ['OFFER_EXPIRED', 'MISSING_OFFER_TERMS', 'NO_ELIGIBLE_OFFER'] },
  { id: 'consent', name: 'Consent & preferences', codes: ['NO_CONSENT', 'DO_NOT_CONTACT'] },
  { id: 'frequency', name: 'Contact frequency', codes: ['RECENT_CONTACT', 'PENDING_DRAFT_EXISTS'] },
  { id: 'language', name: 'Prohibited language', codes: ['BLOCKED_PHRASE'] },
  { id: 'pii', name: 'Sensitive data leakage', codes: ['PII_LEAK'] },
  { id: 'disclaimer', name: 'Required disclaimer', codes: ['MISSING_DISPUTE_PATH'] },
];

export function toChecks(c: Checks | null): ValidationCheck[] {
  const hit = (list: Issue[] | undefined, codes: string[]) => (list ?? []).filter((i) => codes.includes(i.code));
  const known = CHECKS.flatMap((x) => x.codes);
  const out: ValidationCheck[] = CHECKS.map((x) => {
    const bad = hit(c?.blocking, x.codes);
    const warn = hit(c?.warnings, x.codes);
    const result: CheckResult = bad.length ? 'fail' : warn.length ? 'warn' : 'pass';
    const detail = [...bad, ...warn].map((i) => i.detail).join('; ') || 'Passed';
    return { id: x.id, name: x.name, result, detail };
  });
  // a code the table doesn't know must still block approval
  for (const i of [...(c?.blocking ?? [])].filter((b) => !known.includes(b.code))) {
    out.push({ id: i.code.toLowerCase(), name: words(i.code.toLowerCase()), result: 'fail', detail: i.detail });
  }
  return out;
}

const STATUS: Record<string, QueueStatus> = { pending_review: 'ready', blocked: 'blocked', approved: 'approved', sent: 'approved', rejected: 'rejected' };

/** Latest draft per customer, full detail. */
async function latestDrafts(): Promise<Draft[]> {
  const list = await call<{ draft_id: string; customer_id: string }[]>('/drafts'); // newest first
  const seen = new Set<string>();
  const latest = list.filter((d) => !seen.has(d.customer_id) && !!seen.add(d.customer_id));
  return Promise.all(latest.map((d) => call<Draft>(`/drafts/${d.draft_id}`)));
}
async function draftFor(customerId: string): Promise<Draft | null> {
  const list = await call<{ draft_id: string; customer_id: string }[]>('/drafts');
  const hit = list.find((d) => d.customer_id === customerId.toUpperCase());
  return hit ? call<Draft>(`/drafts/${hit.draft_id}`) : null;
}

function toQueueItem(d: Draft): QueueItem {
  const checks = toChecks(d.checks);
  const bad = checks.filter((c) => c.result === 'fail').length;
  const warn = checks.filter((c) => c.result === 'warn').length;
  const primary = d.segments?.segments[0];
  let status = STATUS[d.status] ?? 'ready';
  if (status === 'ready' && warn) status = 'attention';
  return {
    customerId: d.customer_id,
    planSummary: d.facts?.plan ? `${d.facts.plan} · ${d.facts.tenure_months} mo` : '—',
    primarySegment: primary ? assign(primary) : { key: 'consistent', label: 'No segment', confidence: 0 },
    strategy: d.strategy ? words(d.strategy.objective) + (d.strategy.stage ? ` · stage ${d.strategy.stage} of 3` : '') : 'None',
    tone: d.strategy ? words(d.strategy.tone) : '—',
    checksPassed: checks.length - bad,
    checksTotal: checks.length,
    checksNote: bad ? `${bad} failed` : warn ? `${warn} warning${warn > 1 ? 's' : ''}` : undefined,
    status,
  };
}

export async function getQueue(): Promise<{ summary: QueueSummary; items: QueueItem[] }> {
  const drafts = await latestDrafts();
  const items = drafts.map(toQueueItem);
  const count = (...s: QueueStatus[]) => items.filter((i) => s.includes(i.status)).length;
  return {
    items,
    summary: {
      awaitingReview: count('ready', 'attention'), blocked: count('blocked'), approved: count('approved'),
      policyVersion: 'rule_registry', templateVersion: drafts[0]?.template_version ?? '—',
    },
  };
}

/** Wrap fact values found in the text as grounded spans. */
function spansFor(text: string, facts: Record<string, unknown>): DraftSpan[] {
  const vals = Object.entries(facts).map(([k, v]) => [String(v), k] as const).filter(([v]) => v.length > 1);
  if (!vals.length) return [{ text, kind: 'plain' }];
  const re = new RegExp(`(${vals.map(([v]) => v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).sort((a, b) => b.length - a.length).join('|')})`);
  return text.split(re).filter(Boolean).map((part) => {
    const hit = vals.find(([v]) => v === part);
    return hit ? { text: part, kind: 'grounded', evidenceKey: hit[1] } : { text: part, kind: 'plain' };
  });
}

function toParagraphs(d: Draft): DraftParagraph[] {
  const f = d.facts ?? {};
  const policyText = [f.offer_terms, f.dispute_contact].filter(Boolean).map(String);
  return d.body.split(/\n{2,}/).map((p) =>
    policyText.some((t) => p.includes(t))
      ? { kind: 'policy', spans: [{ text: p, kind: 'policy' }] }
      : { kind: 'text', spans: spansFor(p, f) },
  );
}

async function evidenceFor(d: Draft): Promise<EvidenceField[]> {
  const out: EvidenceField[] = [{ key: 'first_name', label: 'Greeting name', value: String(d.facts?.first_name ?? '—') }];
  try {
    const rec = await call<{ evidence?: Record<string, unknown> }>(`/audit/${d.trace_id}`);
    for (const [k, v] of Object.entries(rec.evidence ?? {})) {
      if (v === null || v === undefined || typeof v === 'object' && !Array.isArray(v)) continue;
      const value = Array.isArray(v) ? (v.length ? `${v.length} item${v.length > 1 ? 's' : ''}` : 'none') : String(v);
      out.push({ key: k, label: words(k), value });
    }
  } catch { /* audit record is optional context */ }
  return out;
}

export async function getReviewCase(id: string): Promise<ReviewCase | null> {
  const d = await draftFor(id);
  if (!d || !d.strategy || !d.segments) return null;
  const paragraphs = toParagraphs(d);
  const grounded = paragraphs.flatMap((p) => p.spans).filter((s) => s.kind === 'grounded').length;
  const checks = toChecks(d.checks);
  return {
    customerId: d.customer_id,
    segments: d.segments.segments.map(assign),
    evidence: await evidenceFor(d),
    reasons: (d.segments.segments[0]?.reasons ?? []).map((code) => ({ code, text: words(code.toLowerCase()) })),
    strategy: {
      objective: words(d.strategy.objective), toneRule: words(d.strategy.tone), offerId: d.offer_id,
      channel: 'Email', templateId: d.strategy.template,
    },
    draft: {
      subject: d.subject, paragraphs, groundedSpans: grounded, groundedMatched: grounded,
      unsupportedClaims: checks.find((c) => c.id === 'invented')?.result === 'fail' ? 1 : 0, readingLevel: '—',
    },
    checks,
    modelInfo: { model: d.model, temperature: 0, templateVersion: d.template_version, policyVersion: 'rule_registry' },
    reminderStage: d.strategy.stage ? { current: d.strategy.stage, total: 3 } : undefined,
  };
}

export async function getBlockedCase(id: string): Promise<BlockedCase | null> {
  const d = await draftFor(id);
  if (!d || d.status !== 'blocked') return null;
  const blocking = d.checks?.blocking ?? [];
  const primary = d.segments?.segments[0];
  return {
    customerId: d.customer_id,
    segment: primary ? assign(primary) : { key: 'consistent', label: 'No segment', confidence: 0 },
    headline: 'Draft blocked by guardrails',
    summary: `${blocking.length} check${blocking.length === 1 ? '' : 's'} failed. Nothing can be sent for this customer until the cause is resolved.`,
    failed: blocking.map((b) => ({ code: b.code, title: words(b.code.toLowerCase()), description: b.detail })),
    passed: toChecks(d.checks).filter((c) => c.result === 'pass').map((c) => c.name),
    attempts: [],
    progression: [],
  };
}

// no dry-run endpoint: /edit stores the text and re-runs the checks, which is also audited
export async function revalidate(id: string, subject: string, body: string): Promise<ValidationCheck[]> {
  const d = await draftFor(id);
  if (!d) throw new Error('draft not found');
  const r = await call<{ checks: Checks }>(`/drafts/${d.draft_id}/edit`, post({ subject, body }));
  return toChecks(r.checks);
}

export async function submitDecision(x: {
  customerId: string; action: 'approve' | 'reject'; editedSubject?: string; editedBody?: string;
  rubric: Record<string, number>; feedback: string;
}): Promise<DecisionResult> {
  const d = await draftFor(x.customerId);
  if (!d) throw new Error('draft not found');
  const note = x.feedback + (x.feedback ? ' ' : '') + `[rubric ${JSON.stringify(x.rubric)}]`;
  const base = `/drafts/${d.draft_id}`;
  if (x.action === 'reject') {
    const r = await call<{ trace_id: string }>(`${base}/reject`, post({ note }));
    return { auditEventId: r.trace_id, sendStatus: 'not_sent' };
  }
  if (x.editedBody !== undefined) {
    const e = await call<{ checks: Checks; status: string; trace_id: string }>(
      `${base}/edit`, post({ subject: x.editedSubject ?? d.subject, body: x.editedBody, note }));
    if (e.status === 'blocked') return { auditEventId: e.trace_id, sendStatus: 'blocked', checks: toChecks(e.checks) };
  }
  await call(`${base}/approve`, post({ note }));
  const s = await call<{ trace_id: string }>(`${base}/send`, post()); // mock outbox
  return { auditEventId: s.trace_id, sendStatus: 'mock_outbox' };
}

// no escalation endpoint yet: rejecting removes the draft from the queue; the draft id stands in for a ticket
export async function escalate(id: string): Promise<{ ticketId: string }> {
  const d = await draftFor(id);
  if (!d) throw new Error('draft not found');
  await call(`/drafts/${d.draft_id}/reject`, post({ note: 'Escalated to Billing Ops' }));
  return { ticketId: d.draft_id };
}

export async function generate(): Promise<void> {
  await call('/engage/batch', post({}));
}
