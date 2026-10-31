/**
 * Synthetic demo data. Every customer, amount and metric here is invented
 * for the prototype; replace with real backend responses.
 */
import type {
  AuditEvent,
  BlockedCase,
  DraftParagraph,
  DraftSpan,
  EvaluationSummary,
  PolicyConfig,
  QueueItem,
  QueueSummary,
  ReviewCase,
  ValidationCheck,
} from '../types';

// ---- span helpers -------------------------------------------------------
const t = (text: string): DraftSpan => ({ text, kind: 'plain' });
const g = (text: string, evidenceKey?: string): DraftSpan => ({ text, kind: 'grounded', evidenceKey });
const para = (...spans: DraftSpan[]): DraftParagraph => ({ kind: 'text', spans });
const policy = (text: string): DraftParagraph => ({ kind: 'policy', spans: [{ text, kind: 'policy' }] });
const footer = (text: string): DraftParagraph => ({ kind: 'footer', spans: [t(text)] });
const signoff = para(t('Warm regards,\n[BRAND] Customer Care'));

const pass = (id: string, name: string, detail: string): ValidationCheck => ({ id, name, result: 'pass', detail });

const baseChecks = (overrides: Partial<Record<string, ValidationCheck>> = {}): ValidationCheck[] => {
  const list: ValidationCheck[] = [
    pass('evidence', 'Evidence complete', 'All required fields present and fresh (< 24 h)'),
    pass('grounded', 'Facts grounded', 'Every factual span matches evidence or campaign data'),
    pass('invented', 'No invented amounts or dates', 'All amounts and dates trace to source records'),
    pass('eligibility', 'Offer eligibility (deterministic)', 'Rule evaluated in code, not by the model'),
    pass('offer_terms', 'Offer terms, expiry, channel', 'Offer active and allowed on email'),
    pass('consent', 'Consent & preferences', 'Channel permitted by customer preference'),
    pass('frequency', 'Contact frequency', 'Within minimum gap since last outreach'),
    pass('language', 'Prohibited language', 'No blocked phrases or pressure tactics'),
    pass('pii', 'Sensitive data leakage', 'No account, ID or contact numbers in body'),
    pass('disclaimer', 'Required disclaimer', 'Required policy blocks present'),
  ];
  return list.map((c) => overrides[c.id] ?? c);
};

const modelInfo = (templateVersion: string) => ({
  model: 'llm-gen-v1',
  temperature: 0.2,
  templateVersion,
  policyVersion: 'policy-v3.4',
});

// ---- queue --------------------------------------------------------------
export const queueSummary: QueueSummary = {
  awaitingReview: 5,
  blocked: 1,
  approved: 0,
  policyVersion: 'policy-v3.4',
  templateVersion: 'tpl-v2.1',
};

export const queue: QueueItem[] = [
  { customerId: 'CUS-10231', planSummary: 'Postpaid Plus 799 · 46 mo', primarySegment: { key: 'loyalty', label: 'Loyalty candidate', confidence: 0.93 }, strategy: 'Reward + appreciation', tone: 'Warm, grateful', checksPassed: 10, checksTotal: 10, status: 'ready' },
  { customerId: 'CUS-10482', planSummary: 'Postpaid 599 · 31 mo', primarySegment: { key: 'consistent', label: 'Consistent', confidence: 0.88 }, strategy: 'Appreciation, no offer', tone: 'Warm, brief', checksPassed: 10, checksTotal: 10, status: 'ready' },
  { customerId: 'CUS-11307', planSummary: 'Postpaid 499 · 18 mo', primarySegment: { key: 'declining', label: 'Declining activity', confidence: 0.81 }, strategy: 'Re-engagement offer', tone: 'Helpful, curious', checksPassed: 9, checksTotal: 10, checksNote: '1 warning', status: 'attention' },
  { customerId: 'CUS-11952', planSummary: 'Prepaid 299 · 9 mo', primarySegment: { key: 'dormant', label: 'Dormant', confidence: 0.86 }, strategy: 'Win-back offer', tone: 'Friendly, low-pressure', checksPassed: 10, checksTotal: 10, status: 'ready' },
  { customerId: 'CUS-12088', planSummary: 'Postpaid 599 · 22 mo', primarySegment: { key: 'payment', label: 'Payment reminder', confidence: 0.97 }, strategy: 'Reminder · stage 2 of 3', tone: 'Courteous, clear', checksPassed: 10, checksTotal: 10, status: 'ready' },
  { customerId: 'CUS-12415', planSummary: 'Postpaid 999 · 14 mo', primarySegment: { key: 'payment', label: 'Payment reminder', confidence: 0.62 }, strategy: 'Reminder · stage 3 of 3', tone: 'Firmer notice', checksPassed: 7, checksTotal: 10, checksNote: '3 failed', status: 'blocked' },
];

// ---- review cases -------------------------------------------------------
export const reviewCases: Record<string, ReviewCase> = {
  'CUS-10231': {
    customerId: 'CUS-10231',
    segments: [
      { key: 'loyalty', label: 'Loyalty candidate', confidence: 0.93 },
      { key: 'consistent', label: 'Consistent', confidence: 0.88 },
    ],
    evidence: [
      { key: 'name', label: 'Greeting name', value: 'Priya' },
      { key: 'tenure', label: 'Tenure', value: '46 months' },
      { key: 'plan', label: 'Active plan', value: 'Postpaid Plus 799' },
      { key: 'ontime', label: 'On-time payments', value: '12 of last 12' },
      { key: 'billing', label: 'Billing status', value: 'Paid · next due 05 Nov 2026' },
      { key: 'usage', label: 'Data usage trend', value: 'Stable, 38 GB/mo avg' },
      { key: 'last_contact', label: 'Last outreach', value: '12 Sep 2026 · service notice' },
      { key: 'consent', label: 'Consent', value: 'Offer emails: opted in' },
    ],
    reasons: [
      { code: 'TENURE_GE_36M', text: 'Customer for 46 months, above the 36-month loyalty threshold.' },
      { code: 'ONTIME_12_OF_12', text: 'Every bill in the last 12 cycles paid by the due date.' },
      { code: 'ACTIVE_PREMIUM_PLAN', text: 'Active on a plan in the premium tier.' },
      { code: 'USAGE_STABLE_90D', text: 'Usage within ±10% of baseline over 90 days.' },
    ],
    strategy: { objective: 'Thank & reward', toneRule: 'Warm, grateful, no urgency', offerId: 'LOY-DATA-20', channel: 'Email (preferred)', templateId: 'tpl-loyalty-reward v2.1' },
    draft: {
      subject: 'Thank you for 46 months with us, Priya — a bonus on us',
      paragraphs: [
        para(t('Hi '), g('Priya', 'name'), t(',')),
        para(t('Thank you for being with us for '), g('46 months', 'tenure'), t(' on your '), g('Postpaid Plus 799', 'plan'), t(' plan, and for paying '), g('every bill on time over the past 12 months', 'ontime'), t('.')),
        para(t('As a thank-you, we have added '), g('20 GB of bonus data each month for your next 3 billing cycles', 'offer'), t(' (offer '), g('LOY-DATA-20', 'offer'), t('). Activate it in the app under Offers before '), g('30 Nov 2026', 'offer'), t('.')),
        policy('Offer terms: one activation per account; bonus data expires at the end of each billing cycle and has no cash value.'),
        policy('If you have any questions, our support team is here at [SUPPORT NUMBER].'),
        signoff,
        footer('You are receiving this because you opted in to offer emails. Unsubscribe any time.'),
      ],
      groundedSpans: 8,
      groundedMatched: 8,
      unsupportedClaims: 0,
      readingLevel: 'Grade 7',
    },
    checks: baseChecks({
      grounded: pass('grounded', 'Facts grounded', '8 of 8 spans match evidence or campaign data'),
      invented: pass('invented', 'No invented amounts or dates', 'Only 30 Nov 2026 and 20 GB, both from LOY-DATA-20'),
      eligibility: pass('eligibility', 'Offer eligibility (deterministic)', 'Rule LOY-R2: tenure ≥ 24 mo and on-time ≥ 11 of 12'),
      offer_terms: pass('offer_terms', 'Offer terms, expiry, channel', 'Active until 30 Nov 2026 · email allowed'),
      consent: pass('consent', 'Consent & preferences', 'Offer-email opt-in on record'),
      frequency: pass('frequency', 'Contact frequency', 'Last outreach 49 days ago · minimum gap 14 days'),
      disclaimer: pass('disclaimer', 'Required disclaimer', 'Offer terms and unsubscribe line present'),
    }),
    modelInfo: modelInfo('tpl-loyalty-reward v2.1'),
  },

  'CUS-10482': {
    customerId: 'CUS-10482',
    segments: [{ key: 'consistent', label: 'Consistent', confidence: 0.88 }],
    evidence: [
      { key: 'name', label: 'Greeting name', value: 'Arjun' },
      { key: 'tenure', label: 'Tenure', value: '31 months' },
      { key: 'plan', label: 'Active plan', value: 'Postpaid 599' },
      { key: 'ontime', label: 'On-time payments', value: '12 of last 12' },
      { key: 'billing', label: 'Billing status', value: 'Paid · next due 08 Nov 2026' },
      { key: 'usage', label: 'Data usage trend', value: 'Stable, 21 GB/mo avg' },
      { key: 'last_contact', label: 'Last outreach', value: '29 Aug 2026 · plan update' },
      { key: 'consent', label: 'Consent', value: 'Offer emails: opted out · service emails: on' },
    ],
    reasons: [
      { code: 'ONTIME_12_OF_12', text: 'Every bill in the last 12 cycles paid by the due date.' },
      { code: 'USAGE_STABLE_90D', text: 'Usage within ±10% of baseline over 90 days.' },
      { code: 'TENURE_LT_36M', text: 'Below the 36-month loyalty threshold, so no reward is selected.' },
    ],
    strategy: { objective: 'Appreciation', toneRule: 'Warm, brief', offerId: null, channel: 'Email (service)', templateId: 'tpl-appreciation v1.4' },
    draft: {
      subject: 'Thanks for staying with us, Arjun',
      paragraphs: [
        para(t('Hi '), g('Arjun', 'name'), t(',')),
        para(t('A quick note to say thank you for '), g('31 months', 'tenure'), t(' on your '), g('Postpaid 599', 'plan'), t(' plan, and for keeping '), g('every bill on time this past year', 'ontime'), t('.')),
        para(t('If there is anything we can do better, just reply to this email.')),
        policy('Need help? Our support team is here at [SUPPORT NUMBER].'),
        signoff,
      ],
      groundedSpans: 4,
      groundedMatched: 4,
      unsupportedClaims: 0,
      readingLevel: 'Grade 6',
    },
    checks: baseChecks({
      eligibility: pass('eligibility', 'Offer eligibility (deterministic)', 'No offer selected · offer emails opted out'),
      offer_terms: pass('offer_terms', 'Offer terms, expiry, channel', 'Not applicable · no offer in message'),
      consent: pass('consent', 'Consent & preferences', 'Service email permitted; no marketing content'),
    }),
    modelInfo: modelInfo('tpl-appreciation v1.4'),
  },

  'CUS-11307': {
    customerId: 'CUS-11307',
    segments: [{ key: 'declining', label: 'Declining activity', confidence: 0.81 }],
    evidence: [
      { key: 'name', label: 'Greeting name', value: 'Meera' },
      { key: 'tenure', label: 'Tenure', value: '18 months' },
      { key: 'plan', label: 'Active plan', value: 'Postpaid 499' },
      { key: 'ontime', label: 'On-time payments', value: '11 of last 12' },
      { key: 'billing', label: 'Billing status', value: 'Paid · next due 10 Nov 2026' },
      { key: 'usage', label: 'Data usage trend', value: '−42% over 90 days' },
      { key: 'last_contact', label: 'Last outreach', value: '19 Oct 2026 · survey' },
      { key: 'consent', label: 'Consent', value: 'Offer emails: opted in' },
    ],
    reasons: [
      { code: 'USAGE_DROP_GE_30PCT', text: 'Data usage down 42% versus the previous 90 days.' },
      { code: 'PLAN_ACTIVE', text: 'Plan still active, so re-engagement applies rather than win-back.' },
    ],
    strategy: { objective: 'Re-engagement offer', toneRule: 'Helpful, curious', offerId: 'RE-ENG-STREAM-3M', channel: 'Email (preferred)', templateId: 'tpl-reengage v1.8' },
    draft: {
      subject: 'Meera, a little extra to enjoy on your plan',
      paragraphs: [
        para(t('Hi '), g('Meera', 'name'), t(',')),
        para(t('We noticed you have been using your '), g('Postpaid 499', 'plan'), t(' plan a little less lately, and we would love to help you get more from it.')),
        para(t('You can add '), g('3 months of our streaming add-on', 'offer'), t(' at no extra cost (offer '), g('RE-ENG-STREAM-3M', 'offer'), t('). It is available until '), g('15 Dec 2026', 'offer'), t('.')),
        policy('Offer terms: add-on ends automatically after 3 months; no charge unless you choose to continue.'),
        policy('Questions? Our support team is here at [SUPPORT NUMBER].'),
        signoff,
        footer('You are receiving this because you opted in to offer emails. Unsubscribe any time.'),
      ],
      groundedSpans: 5,
      groundedMatched: 5,
      unsupportedClaims: 0,
      readingLevel: 'Grade 7',
    },
    checks: baseChecks({
      frequency: { id: 'frequency', name: 'Contact frequency', result: 'warn', detail: 'Last outreach 12 days ago · minimum gap 14 days. Hold until 02 Nov or approve with reason.' },
    }),
    modelInfo: modelInfo('tpl-reengage v1.8'),
  },

  'CUS-11952': {
    customerId: 'CUS-11952',
    segments: [{ key: 'dormant', label: 'Dormant', confidence: 0.86 }],
    evidence: [
      { key: 'name', label: 'Greeting name', value: 'Rahul' },
      { key: 'tenure', label: 'Tenure', value: '9 months' },
      { key: 'plan', label: 'Plan', value: 'Prepaid 299 · expired' },
      { key: 'last_active', label: 'Last activity', value: '74 days ago' },
      { key: 'billing', label: 'Billing status', value: 'No balance due' },
      { key: 'last_contact', label: 'Last outreach', value: '01 Sep 2026 · recharge reminder' },
      { key: 'consent', label: 'Consent', value: 'Offer emails: opted in' },
      { key: 'channel', label: 'Preferred channel', value: 'Email' },
    ],
    reasons: [
      { code: 'NO_ACTIVITY_GE_60D', text: 'No calls, data or recharges for 74 days.' },
      { code: 'PREPAID_EXPIRED', text: 'Prepaid validity lapsed; win-back offers apply.' },
    ],
    strategy: { objective: 'Win-back offer', toneRule: 'Friendly, low-pressure', offerId: 'WB-RECHARGE-10', channel: 'Email (preferred)', templateId: 'tpl-winback v1.2' },
    draft: {
      subject: 'We have kept your number ready for you, Rahul',
      paragraphs: [
        para(t('Hi '), g('Rahul', 'name'), t(',')),
        para(t('It has been a while since you last used your '), g('Prepaid 299', 'plan'), t(' connection. Whenever you are ready, we would be glad to have you back.')),
        para(t('Your next recharge comes with '), g('10% off', 'offer'), t(' (offer '), g('WB-RECHARGE-10', 'offer'), t('), valid until '), g('31 Dec 2026', 'offer'), t('.')),
        policy('Offer terms: valid on one recharge per number; cannot be combined with other offers.'),
        policy('Need help? Our support team is here at [SUPPORT NUMBER].'),
        signoff,
        footer('You are receiving this because you opted in to offer emails. Unsubscribe any time.'),
      ],
      groundedSpans: 5,
      groundedMatched: 5,
      unsupportedClaims: 0,
      readingLevel: 'Grade 6',
    },
    checks: baseChecks(),
    modelInfo: modelInfo('tpl-winback v1.2'),
  },

  'CUS-12088': {
    customerId: 'CUS-12088',
    segments: [{ key: 'payment', label: 'Payment reminder', confidence: 0.97 }],
    evidence: [
      { key: 'name', label: 'Greeting name', value: 'Kavya' },
      { key: 'plan', label: 'Active plan', value: 'Postpaid 599' },
      { key: 'amount', label: 'Amount due', value: '₹1,249.00' },
      { key: 'due', label: 'Due date', value: '13 Oct 2026' },
      { key: 'overdue', label: 'Days overdue', value: '18' },
      { key: 'sources', label: 'Billing sources', value: 'Billing + ledger agree' },
      { key: 'dispute', label: 'Open dispute', value: 'None' },
      { key: 'last_contact', label: 'Last reminder', value: '17 Oct 2026 · stage 1' },
    ],
    reasons: [
      { code: 'OVERDUE_11_25D', text: '18 days past due, inside the stage-2 window.' },
      { code: 'SOURCES_AGREE', text: 'Billing system and payments ledger report the same amount and date.' },
      { code: 'NO_OPEN_DISPUTE', text: 'No billing dispute on record, so stage 2 is allowed.' },
    ],
    strategy: { objective: 'Reminder · stage 2', toneRule: 'Courteous, clear, no threats', offerId: null, channel: 'Email (transactional)', templateId: 'tpl-reminder-s2 v2.0' },
    draft: {
      subject: 'Reminder: your bill of ₹1,249.00 is past due',
      paragraphs: [
        para(t('Hi '), g('Kavya', 'name'), t(',')),
        para(t('Our records show that your '), g('Postpaid 599', 'plan'), t(' bill of '), g('₹1,249.00', 'amount'), t(', due on '), g('13 Oct 2026', 'due'), t(', has not yet been paid.')),
        para(t('You can pay in the app, online or at any store. If you have already paid, please ignore this message.')),
        policy('If you think this bill is wrong or you need more time, contact us at [SUPPORT NUMBER] and we will help, including raising a billing dispute.'),
        signoff,
      ],
      groundedSpans: 4,
      groundedMatched: 4,
      unsupportedClaims: 0,
      readingLevel: 'Grade 6',
    },
    checks: baseChecks({
      eligibility: pass('eligibility', 'Reminder stage (deterministic)', 'BILL-R2: 11–25 days overdue → stage 2'),
      offer_terms: pass('offer_terms', 'Billing sources agree', 'Amount and due date identical in billing and ledger'),
      consent: pass('consent', 'Consent & preferences', 'Transactional email permitted'),
      frequency: pass('frequency', 'Contact frequency', 'Last reminder 14 days ago · minimum gap 5 days'),
      disclaimer: pass('disclaimer', 'Required disclaimer', 'Support and dispute path present'),
    }),
    modelInfo: modelInfo('tpl-reminder-s2 v2.0'),
    reminderStage: { current: 2, total: 3 },
  },
};

// ---- blocked case -------------------------------------------------------
export const blockedCases: Record<string, BlockedCase> = {
  'CUS-12415': {
    customerId: 'CUS-12415',
    segment: { key: 'payment', label: 'Payment reminder', confidence: 0.62 },
    headline: 'The assistant refused to generate a stage-3 overdue notice',
    summary:
      'Three required checks failed before drafting. No message was written, and sending is locked for this customer until the billing record is reconciled. A reviewer cannot override these checks from this screen.',
    failed: [
      {
        code: 'BILL_SOURCE_CONFLICT',
        title: 'Contradictory billing data',
        description: '',
        conflict: {
          sourceALabel: 'Billing system',
          sourceBLabel: 'Payments ledger',
          rows: [
            { field: 'Status', sourceA: 'Overdue · 34 days', sourceB: 'Payment received' },
            { field: 'Amount', sourceA: '₹2,148.00 due', sourceB: '₹2,148.00 paid' },
            { field: 'Date', sourceA: 'Due 27 Sep 2026', sourceB: 'Paid 27 Oct 2026 · unreconciled' },
          ],
          policyNote: 'Policy BILL-P1: a reminder may only cite an amount and date that every billing source agrees on.',
        },
      },
      {
        code: 'DISPUTE_OPEN',
        title: 'Open billing dispute',
        description:
          'Dispute DSP-2291 was raised on 02 Oct 2026 and is still open. Policy BILL-P4 suppresses firmer notices (stage 2 and above) while a dispute is open.',
      },
      {
        code: 'CONF_LT_0.75',
        title: 'Classification confidence below threshold',
        description: 'The segment rests on conflicting inputs, so the system will not choose a tone for it.',
        confidence: { value: 0.62, threshold: 0.75 },
      },
    ],
    passed: [
      'Evidence fields present',
      'No protected or proxy attributes used',
      'Contact frequency within limit',
      'Communication preference: email allowed',
      'Template version approved',
      'Sensitive data scan clean',
      'Support and dispute path available',
    ],
    attempts: [{ at: '31 Oct 2026 · 09:58', outcome: 'REFUSED', description: 'API request POST /send without reviewer approval was rejected.' }],
    progression: [
      { stage: 1, label: 'Courteous reminder', state: 'sent', note: 'Sent 04 Oct' },
      { stage: 2, label: 'Clear follow-up', state: 'suppressed', note: 'Suppressed · dispute' },
      { stage: 3, label: 'Firmer notice', state: 'refused', note: 'Refused' },
    ],
  },
};

// ---- policy -------------------------------------------------------------
export const policyConfig: PolicyConfig = {
  version: 'policy-v3.4',
  liveSince: '24 Oct 2026',
  allowedInputs: 'activity, tenure, active plan, payment timeliness, consent',
  segments: [
    { key: 'loyalty', name: 'Loyalty candidate', rule: 'tenure ≥ 36m AND ontime ≥ 11/12 AND plan.active', objective: 'Thank & reward', tone: 'Warm, grateful', template: 'tpl-loyalty-reward v2.1' },
    { key: 'consistent', name: 'Consistent', rule: 'ontime ≥ 11/12 AND usage Δ90d within ±10%', objective: 'Appreciation', tone: 'Warm, brief', template: 'tpl-appreciation v1.4' },
    { key: 'declining', name: 'Declining activity', rule: 'usage Δ90d ≤ −30% AND plan.active', objective: 'Re-engagement offer', tone: 'Helpful, curious', template: 'tpl-reengage v1.8' },
    { key: 'dormant', name: 'Dormant', rule: 'no activity ≥ 60 days', objective: 'Win-back offer', tone: 'Friendly, low-pressure', template: 'tpl-winback v1.2' },
    { key: 'payment', name: 'Payment reminder', rule: 'bill.overdue_days ≥ 3 AND sources agree', objective: 'Reminder by stage', tone: 'Courteous → firmer', template: 'tpl-reminder-s1..s3 v2.0' },
  ],
  offers: [
    { id: 'LOY-DATA-20', value: '20 GB bonus/mo × 3 cycles', eligibility: 'tenure ≥ 24m, ontime ≥ 11/12', expiry: '30 Nov 2026', channels: 'Email, app' },
    { id: 'RE-ENG-STREAM-3M', value: '3 months streaming add-on', eligibility: 'segment = declining', expiry: '15 Dec 2026', channels: 'Email' },
    { id: 'WB-RECHARGE-10', value: '10% off next recharge', eligibility: 'segment = dormant, prepaid', expiry: '31 Dec 2026', channels: 'Email, SMS' },
    { id: 'APP-THANKS-01', value: 'No offer · thank-you only', eligibility: 'any non-overdue', expiry: '—', channels: 'Email' },
  ],
  reminderStages: [
    { stage: 1, name: 'Courteous reminder', window: '3–10 days overdue', guidance: 'friendly, assumes oversight' },
    { stage: 2, name: 'Clear follow-up', window: '11–25 days', guidance: 'states amount, date and payment options' },
    { stage: 3, name: 'Firmer notice', window: '26+ days', guidance: 'factual consequences, still respectful' },
  ],
  disclaimers: [
    { id: 'DSC-OFFER', text: 'Offer terms block with expiry and no-cash-value line' },
    { id: 'DSC-UNSUB', text: 'Unsubscribe line on every marketing email' },
    { id: 'DSC-DISPUTE', text: 'Support and dispute contact on every reminder' },
  ],
  blockedPhrases: ['“final warning”', '“legal action”', '“act now or lose”', '“guaranteed”', '“you failed to”', '/\\b\\d{12}\\b/ account no.'],
  blockedPhraseCount: 42,
  blockedPatternCount: 6,
  contactLimits: '1 marketing email per 14 days · 1 reminder per 5 days.',
};

// ---- evaluation + audit -------------------------------------------------
export const evaluation: EvaluationSummary = {
  sampleSize: 50,
  accuracy: { correct: 46, total: 50 },
  grounded: { matched: 406, total: 412, caughtPreReview: 6 },
  complianceAtSend: 1,
  safetyRefusals: { refused: 12, total: 12 },
  labels: ['Loyalty', 'Consistent', 'Declining', 'Dormant', 'Payment'],
  confusion: [
    [9, 1, 0, 0, 0],
    [0, 10, 0, 0, 0],
    [0, 0, 8, 2, 0],
    [0, 0, 1, 9, 0],
    [0, 0, 0, 0, 10],
  ],
  scenarios: [
    { name: 'Consistent customer', result: 'Appreciation drafted', ok: true },
    { name: 'Loyalty-reward candidate', result: 'Reward drafted', ok: true },
    { name: 'Declining activity', result: 'Re-engage drafted', ok: true },
    { name: 'Inactive / dormant', result: 'Win-back drafted', ok: true },
    { name: 'Overdue bill', result: 'Stage 2 drafted', ok: true },
    { name: 'Conflicting billing data', result: 'Refused · escalated', ok: false },
  ],
  rubricAverage: 4.4,
  edits: 9,
  rejections: 2,
};

export const auditLog: AuditEvent[] = [
  { at: '31 Oct 10:04:12', customerId: 'CUS-10231', event: 'Draft generated', versions: 'llm-gen-v1 · tpl-loyalty-reward v2.1', policyDecision: 'LOY-R2 pass · 10/10 checks', sendStatus: 'awaiting' },
  { at: '31 Oct 09:58:40', customerId: 'CUS-12415', event: 'Send request refused', versions: 'policy-v3.4', policyDecision: 'BILL-P1, BILL-P4, CONF fail', sendStatus: 'blocked' },
  { at: '31 Oct 09:51:03', customerId: 'CUS-12088', event: 'Draft generated', versions: 'llm-gen-v1 · tpl-reminder-s2 v2.0', policyDecision: 'Stage 2 · sources agree', sendStatus: 'awaiting' },
  { at: '30 Oct 17:22:18', customerId: 'CUS-09874', event: 'Reviewer edited, approved', versions: 'llm-gen-v1 · tpl-reengage v1.8', policyDecision: 'Checks re-run · pass', sendStatus: 'mock_outbox' },
  { at: '30 Oct 16:40:55', customerId: 'CUS-09311', event: 'Reviewer rejected', versions: 'llm-gen-v1 · tpl-winback v1.2', policyDecision: 'Pass · tone feedback', sendStatus: 'not_sent' },
  { at: '30 Oct 15:12:09', customerId: 'CUS-08820', event: 'Offer removed by validator', versions: 'policy-v3.4', policyDecision: 'RE-ENG ineligible · prepaid', sendStatus: 'regenerated' },
];
