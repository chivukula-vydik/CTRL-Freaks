/**
 * Data contract between the reviewer console and the backend.
 * The backend owns classification, eligibility and validation; the UI only
 * displays results and records reviewer actions.
 */

export type SegmentKey = 'loyalty' | 'consistent' | 'declining' | 'dormant' | 'payment';

export type QueueStatus = 'ready' | 'attention' | 'blocked' | 'approved' | 'rejected';

export interface SegmentAssignment {
  key: SegmentKey;
  label: string;
  confidence: number; // 0..1
}

/** One row in the review queue (FR-02, FR-03 summary). */
export interface QueueItem {
  customerId: string;
  planSummary: string;
  primarySegment: SegmentAssignment;
  strategy: string;
  tone: string;
  checksPassed: number;
  checksTotal: number;
  checksNote?: string; // e.g. "1 warning", "3 failed"
  status: QueueStatus;
}

export interface QueueSummary {
  awaitingReview: number;
  blocked: number;
  approved: number;
  policyVersion: string;
  templateVersion: string;
}

/** FR-01: minimal customer context, permitted fields only. */
export interface EvidenceField {
  key: string;
  label: string;
  value: string;
}

/** FR-02: interpretable reason codes. */
export interface ReasonCode {
  code: string;
  text: string;
}

/** FR-03: selected strategy. */
export interface Strategy {
  objective: string;
  toneRule: string;
  offerId: string | null;
  channel: string;
  templateId: string;
}

/** FR-04: a draft broken into spans so the UI can show grounding. */
export type SpanKind = 'plain' | 'grounded' | 'policy';
export interface DraftSpan {
  text: string;
  kind: SpanKind;
  evidenceKey?: string; // which evidence field backs a grounded span
}
export interface DraftParagraph {
  kind: 'text' | 'policy' | 'footer';
  spans: DraftSpan[];
}
export interface EmailDraft {
  subject: string;
  paragraphs: DraftParagraph[];
  groundedSpans: number;
  groundedMatched: number;
  unsupportedClaims: number;
  readingLevel: string;
}

/** FR-05..FR-07: deterministic validation results. */
export type CheckResult = 'pass' | 'warn' | 'fail';
export interface ValidationCheck {
  id: string;
  name: string;
  result: CheckResult;
  detail: string;
}

export interface ModelInfo {
  model: string;
  temperature: number;
  templateVersion: string;
  policyVersion: string;
}

export interface ReviewCase {
  customerId: string;
  segments: SegmentAssignment[];
  evidence: EvidenceField[];
  reasons: ReasonCode[];
  strategy: Strategy;
  draft: EmailDraft;
  checks: ValidationCheck[];
  modelInfo: ModelInfo;
  reminderStage?: { current: number; total: number };
}

/** Blocked / refused case (FR-07, FR-10). */
export interface SourceConflictRow {
  field: string;
  sourceA: string;
  sourceB: string;
}
export interface FailedCheck {
  code: string;
  title: string;
  description: string;
  conflict?: { sourceALabel: string; sourceBLabel: string; rows: SourceConflictRow[]; policyNote: string };
  confidence?: { value: number; threshold: number };
}
export interface DeliveryAttempt {
  at: string;
  outcome: 'REFUSED' | 'SENT_MOCK';
  description: string;
}
export interface ReminderStep {
  stage: number;
  label: string;
  state: 'sent' | 'suppressed' | 'refused' | 'pending';
  note: string;
}
export interface BlockedCase {
  customerId: string;
  segment: SegmentAssignment;
  headline: string;
  summary: string;
  failed: FailedCheck[];
  passed: string[];
  attempts: DeliveryAttempt[];
  progression: ReminderStep[];
}

/** Reviewer action (FR-08). */
export type RubricKey = 'relevance' | 'clarity' | 'personalization' | 'cta' | 'tone';
export interface ReviewDecision {
  customerId: string;
  action: 'approve' | 'reject';
  editedSubject?: string;
  editedBody?: string;
  rubric: Record<RubricKey, number>;
  feedback: string;
}
export interface DecisionResult {
  auditEventId: string;
  sendStatus: 'mock_outbox' | 'not_sent' | 'blocked';
  checks?: ValidationCheck[];
}

/** Policy configuration. */
export interface SegmentRule {
  key: SegmentKey;
  name: string;
  rule: string;
  objective: string;
  tone: string;
  template: string;
}
export interface Offer {
  id: string;
  value: string;
  eligibility: string;
  expiry: string;
  channels: string;
}
export interface ReminderStageRule {
  stage: number;
  name: string;
  window: string;
  guidance: string;
}
export interface Disclaimer {
  id: string;
  text: string;
}
export interface PolicyConfig {
  version: string;
  liveSince: string;
  allowedInputs: string;
  segments: SegmentRule[];
  offers: Offer[];
  reminderStages: ReminderStageRule[];
  disclaimers: Disclaimer[];
  blockedPhrases: string[];
  blockedPatternCount: number;
  blockedPhraseCount: number;
  contactLimits: string;
}

/** Evaluation + audit. */
export interface EvaluationSummary {
  sampleSize: number;
  accuracy: { correct: number; total: number };
  grounded: { matched: number; total: number; caughtPreReview: number };
  complianceAtSend: number; // 0..1
  safetyRefusals: { refused: number; total: number };
  labels: string[];
  confusion: number[][]; // rows = labelled, cols = predicted
  scenarios: { name: string; result: string; ok: boolean }[];
  rubricAverage: number;
  edits: number;
  rejections: number;
}
export interface AuditEvent {
  at: string;
  customerId: string;
  event: string;
  versions: string;
  policyDecision: string;
  sendStatus: 'awaiting' | 'blocked' | 'mock_outbox' | 'not_sent' | 'regenerated';
}
