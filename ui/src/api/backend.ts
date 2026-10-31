/**
 * Adapter from the UC5 FastAPI backend (draft_id based, snake_case) to the console's types.
 * The console is keyed by customer id, so every call resolves the customer's latest draft first.
 * Rules shown in the console come from GET /policy, which serves the YAMLs in config/.
 */
import type {
  AuditEvent,
  BlockedCase,
  CheckResult,
  DecisionResult,
  DraftParagraph,
  DraftSpan,
  EvaluationSummary,
  EvidenceField,
  PolicyConfig,
  QueueItem,
  QueueStatus,
  QueueSummary,
  ReviewCase,
  SegmentAssignment,
  SegmentKey,
  ValidationCheck,
} from '../types';

interface Issue { code: string; detail: string; rule_id?: string }
interface Checks { blocking: Issue[]; warnings: Issue[]; passed: boolean }
interface Seg { segment: string; confidence: number; reasons: string[]; rule_id?: string; rule_text?: string }
interface Draft {
  draft_id: string; customer_id: string; status: string; subject: string; body: string; trace_id: string;
  segments: { segments: Seg[]; primary: string | null; confidence: number } | null;
  strategy: { name: string; objective: string; tone: string; template: string; message_type: string; stage?: number | null } | null;
  facts: Record<string, unknown> | null; checks: Checks | null; offer_id: string | null;
  template_version: string; model: string;
}
interface AuditStep { step: string; evidence: unknown }
interface AuditRow {
  trace_id: string; step: string; timestamp: string; customer_id: string | null; actor: string;
  rule: string | null; model_version: string | null; record: Record<string, unknown>;
}
interface PaymentStage { stage: string; message_type: string; overdue_range: [number | null, number | null]; human_review_required?: boolean }
interface CatalogRow {
  offer_id: string; offer_name: string; message_type: string; eligible_segments: string; plan_type: string;
  min_tenure_months: number; channel: string; value: string | number; value_unit: string; valid_from: string; expiry_date: string;
}
interface PolicyResponse {
  policy: {
    version: string; snapshot_date: string;
    segmentation: { order: string[] };
    strategy: Record<string, unknown> & { names: Record<string, string>; payment_stages: PaymentStage[] };
    tone: Record<string, string>;
    precheck: { rules: { cooldown_or_duplicate: { cooldown_days: number; duplicate_days: number } } };
    message: { pii_fields_to_drop: string[]; locked_placeholders: string[] };
  };
  segmentation: { rules: { id: string; segment: string; description: string }[] };
  offers: { selection: { repeat_guard_days: number } };
  validator: { checks: { id: string; name: string; description: string; patterns?: Record<string, string>;
    forbidden_words?: Record<string, string[]>; sub_checks?: { pattern?: string }[] }[] };
  catalog: CatalogRow[];
  ai: { model: string; temperature: number; tones: Record<string, string> };
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

// the YAML rules change rarely: one fetch per page load
let policyCache: Promise<PolicyResponse> | null = null;
const policyOnce = () => (policyCache ??= call<PolicyResponse>('/policy').catch((e) => { policyCache = null; throw e; }));

const SEGMENT: Record<string, { key: SegmentKey; label: string }> = {
  payment_reminder: { key: 'payment', label: 'Payment reminder' },
  dormant: { key: 'dormant', label: 'Dormant' },
  declining_activity: { key: 'declining', label: 'Declining activity' },
  loyalty_candidate: { key: 'loyalty', label: 'Loyalty candidate' },
  consistent: { key: 'consistent', label: 'Consistent' },
};
const assign = (s: Seg): SegmentAssignment => ({ ...(SEGMENT[s.segment] ?? { key: 'consistent', label: s.segment }), confidence: s.confidence });
const words = (s: string) => s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

// gate 3 (pre-checks), gate 5 (offer) and step 7 (message_validator_rules.yaml MV-01..MV-06), folded into rows
const CHECKS: { id: string; name: string; codes: string[] }[] = [
  { id: 'account', name: 'Account active, data consistent', codes: ['account_inactive', 'data_conflict'] },
  { id: 'consent', name: 'Email allowed, consent, deliverable', codes: ['email_not_allowed', 'consent_missing', 'email_undeliverable'] },
  { id: 'dispute', name: 'No dispute, arrangement or hardship', codes: ['dispute_or_complaint_open', 'payment_arrangement_or_hardship'] },
  { id: 'frequency', name: 'Cooldown and duplicate window', codes: ['cooldown_or_duplicate'] },
  { id: 'offer', name: 'Offer gates still pass (OV-01..05)', codes: ['offer_no_longer_valid'] },
  { id: 'ai', name: 'AI draft writer', codes: ['AI_DRAFT_REJECTED', 'AI_UNAVAILABLE'] },
  { id: 'length', name: 'MV-01 Length and sentences', codes: ['EMPTY_DRAFT', 'LENGTH_CHECK'] },
  { id: 'greeting', name: 'MV-02/03 Greeting and sign-off', codes: ['GREETING_CHECK', 'SIGNOFF_CHECK'] },
  { id: 'pii', name: 'MV-04 No personal data', codes: ['PII_CHECK'] },
  { id: 'tone', name: 'MV-05 Tone matches strategy', codes: ['TONE_CHECK'] },
  { id: 'placeholders', name: 'MV-06 Placeholders, no injected values',
    codes: ['PLACEHOLDER_PRESENCE', 'PLACEHOLDER_UNKNOWN', 'NO_INJECTED_CURRENCY', 'NO_INJECTED_DATES', 'NO_INJECTED_OFFER_WORDS', 'NO_INJECTED_DIGITS'] },
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
    planSummary: d.facts?.plan_name ? `${d.facts.plan_name} · ${d.facts.plan_type} · ${d.facts.tenure_months} mo` : '—',
    primarySegment: primary ? assign(primary) : { key: 'consistent', label: 'No segment', confidence: 0 },
    strategy: d.strategy ? words(d.strategy.name) + (d.strategy.stage ? ` · stage ${d.strategy.stage} of 3` : '') : 'None',
    tone: d.strategy ? words(d.strategy.tone) : '—',
    checksPassed: checks.length - bad,
    checksTotal: checks.length,
    checksNote: bad ? `${bad} failed` : warn ? `${warn} warning${warn > 1 ? 's' : ''}` : undefined,
    status,
  };
}

export async function getQueue(): Promise<{ summary: QueueSummary; items: QueueItem[] }> {
  const [drafts, pol] = await Promise.all([latestDrafts(), policyOnce()]);
  const items = drafts.map(toQueueItem);
  const count = (...s: QueueStatus[]) => items.filter((i) => s.includes(i.status)).length;
  return {
    items,
    summary: {
      awaitingReview: count('ready', 'attention'), blocked: count('blocked'), approved: count('approved'),
      policyVersion: pol.policy.version, templateVersion: drafts[0]?.template_version ?? '—',
    },
  };
}

/** Wrap fact values found in the text as grounded spans. */
function spansFor(text: string, facts: Record<string, unknown>): DraftSpan[] {
  const vals = Object.entries(facts).filter(([k]) => k !== 'language').map(([k, v]) => [String(v), k] as const).filter(([v]) => v.length > 1);
  if (!vals.length) return [{ text, kind: 'plain' }];
  const re = new RegExp(`(${vals.map(([v]) => v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).sort((a, b) => b.length - a.length).join('|')})`);
  return text.split(re).filter(Boolean).map((part) => {
    const hit = vals.find(([v]) => v === part);
    return hit ? { text: part, kind: 'grounded', evidenceKey: hit[1] } : { text: part, kind: 'plain' };
  });
}

function toParagraphs(d: Draft): DraftParagraph[] {
  const f = d.facts ?? {};
  const terms = f.offer_terms ? String(f.offer_terms) : null;
  return d.body.split(/\n{2,}/).map((p) => {
    if (terms && p.includes(terms)) {
      const [before, after] = [p.slice(0, p.indexOf(terms)), p.slice(p.indexOf(terms) + terms.length)];
      return { kind: 'text', spans: [...spansFor(before, f), { text: terms, kind: 'policy' }, ...spansFor(after, f)] };
    }
    return { kind: 'text', spans: spansFor(p, f) };
  });
}

async function evidenceFor(d: Draft): Promise<EvidenceField[]> {
  const out: EvidenceField[] = [{ key: 'first_name', label: 'Greeting name', value: String(d.facts?.first_name ?? '—') }];
  try {
    const rec = await call<{ steps: AuditStep[] }>(`/audit/${d.trace_id}`);
    const ev = (rec.steps.find((s) => s.step === 'context')?.evidence ?? {}) as Record<string, unknown>;
    for (const [k, v] of Object.entries(ev)) {
      if (v === null || v === undefined || (typeof v === 'object' && !Array.isArray(v))) continue;
      const value = Array.isArray(v) ? (v.length ? (typeof v[0] === 'string' ? v.join(', ') : `${v.length} item${v.length > 1 ? 's' : ''}`) : 'none') : String(v);
      out.push({ key: k, label: words(k), value });
    }
  } catch { /* audit record is optional context */ }
  return out;
}

export async function getReviewCase(id: string): Promise<ReviewCase | null> {
  const d = await draftFor(id);
  if (!d || !d.strategy || !d.segments) return null;
  const [evidence, pol] = await Promise.all([evidenceFor(d), policyOnce()]);
  const paragraphs = toParagraphs(d);
  const grounded = paragraphs.flatMap((p) => p.spans).filter((s) => s.kind === 'grounded').length;
  const checks = toChecks(d.checks);
  const primary = d.segments.segments[0];
  return {
    customerId: d.customer_id,
    segments: d.segments.segments.map(assign),
    evidence,
    reasons: (primary?.reasons ?? []).map((code) => ({ code, text: primary?.rule_text ?? words(code.toLowerCase()) })),
    strategy: {
      objective: words(d.strategy.name), toneRule: words(d.strategy.tone), offerId: d.offer_id,
      channel: 'Email', templateId: d.strategy.message_type,
    },
    draft: {
      subject: d.subject, paragraphs, groundedSpans: grounded, groundedMatched: grounded,
      unsupportedClaims: checks.find((c) => c.id === 'placeholders')?.result === 'fail' ? 1 : 0, readingLevel: '—',
    },
    checks,
    modelInfo: { model: d.model, temperature: pol.ai.temperature, templateVersion: d.template_version, policyVersion: pol.policy.version },
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
    failed: blocking.map((b) => ({ code: b.rule_id ? `${b.rule_id} ${b.code}` : b.code, title: words(b.code.toLowerCase()), description: b.detail })),
    passed: toChecks(d.checks).filter((c) => c.result === 'pass').map((c) => c.name),
    attempts: [],
    progression: [],
  };
}

// no dry-run endpoint: /edit stores the text and re-runs gates 5 and 7, which is also audited
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

// ---------------------------------------------------------------- policy, evaluation, audit ---
const range = ([lo, hi]: [number | null, number | null]) =>
  lo === null ? `due within the reminder window (≤ ${hi} days overdue)` : hi === null ? `${lo}+ days overdue` : `${lo}–${hi} days overdue`;

export async function getPolicy(): Promise<PolicyConfig> {
  const p = await policyOnce();
  const { policy: pol, ai } = p;
  const stages = pol.strategy.payment_stages;
  const toneOf = (key: string) => pol.tone[key] ?? '—';
  const forbidden = [...new Set(p.validator.checks.flatMap((c) => Object.values(c.forbidden_words ?? {}).flat()))];
  const patterns = p.validator.checks.reduce((n, c) => n + Object.keys(c.patterns ?? {}).length + (c.sub_checks ?? []).filter((s) => s.pattern).length, 0);
  const cd = pol.precheck.rules.cooldown_or_duplicate;
  return {
    version: pol.version,
    liveSince: pol.snapshot_date,
    allowedInputs: `permitted facts only · dropped: ${pol.message.pii_fields_to_drop.join(', ')}`,
    segments: p.segmentation.rules.map((r) => {
      const pay = r.segment === 'payment_reminder';
      const mtype = String(pol.strategy[r.segment] ?? '');
      const toneKey = `${mtype}_${r.segment}` in pol.tone ? `${mtype}_${r.segment}` : mtype;
      return {
        key: (SEGMENT[r.segment] ?? { key: 'consistent' }).key,
        name: SEGMENT[r.segment]?.label ?? r.segment,
        rule: `${r.id} · ${r.description.trim()}`,
        objective: pay ? stages.map((s) => s.stage).join(' → ') : words(pol.strategy.names[r.segment] ?? '—'),
        tone: pay ? [toneOf('payment_reminder'), ...stages.slice(1).map((_, i) => toneOf(`overdue_notice_stage_${i + 1}`))].join(' / ') : toneOf(toneKey),
        template: pay ? [...new Set(stages.map((s) => s.message_type))].join(' / ') : mtype,
      };
    }),
    offers: p.catalog.map((o) => ({
      id: o.offer_id,
      value: `${o.offer_name} · ${o.value} ${o.value_unit}`,
      eligibility: `${o.eligible_segments.replace(/\|/g, ', ')} · ${o.plan_type} · ≥${o.min_tenure_months} mo`,
      expiry: `${o.valid_from} → ${o.expiry_date}`,
      channels: o.channel,
    })),
    reminderStages: stages.map((s, i) => ({
      stage: i,
      name: words(s.stage),
      window: range(s.overdue_range),
      guidance: (ai.tones[toneOf(i ? `overdue_notice_stage_${i}` : 'payment_reminder')] ?? '') + (s.human_review_required ? ' · reviewer note required' : ''),
    })),
    disclaimers: p.validator.checks.map((c) => ({ id: c.id, text: c.description.trim() })),
    blockedPhrases: forbidden,
    blockedPatternCount: patterns,
    blockedPhraseCount: forbidden.length,
    contactLimits: `cooldown ${cd.cooldown_days} days · same message type ${cd.duplicate_days} days · same offer ${p.offers.selection.repeat_guard_days} days`,
  };
}

export async function getEvaluation(): Promise<EvaluationSummary> {
  const e = await call<EvaluationSummary>('/evaluation');
  return { ...e, labels: e.labels.map((l) => SEGMENT[l]?.label ?? l) };
}

function sendStatus(r: AuditRow): AuditEvent['sendStatus'] {
  const rec = r.record;
  if (r.step === 'send') return 'mock_outbox';
  if (r.step.endsWith('_refused') || rec.passed === false || rec.status === 'blocked') return 'blocked';
  if (r.step === 'reject') return 'not_sent';
  if (r.step === 'draft' && Array.isArray(rec.warnings) && rec.warnings.length) return 'regenerated';
  return 'awaiting';
}

export async function getAudit(): Promise<AuditEvent[]> {
  const rows = await call<AuditRow[]>('/audit?limit=300');
  return rows.map((r) => ({
    at: new Date(r.timestamp).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).replace(',', ''),
    customerId: r.customer_id ?? '—',
    event: words(r.step) + (r.actor !== 'system' ? ` · ${r.actor}` : '') + (typeof r.record.note === 'string' && r.record.note ? ` · “${r.record.note.replace(/\s*\[rubric.*\]$/, '').slice(0, 40)}”` : ''),
    versions: r.model_version ?? r.trace_id,
    policyDecision: (r.rule ?? '—') + (r.record.passed === true ? ' · passed' : r.record.passed === false ? ' · failed' : ''),
    sendStatus: sendStatus(r),
  }));
}
