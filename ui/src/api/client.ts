/**
 * API client. Two interchangeable implementations:
 *  - http: calls the FastAPI backend under /api (default; vite proxies /api to it)
 *  - mock: in-browser synthetic data, no backend needed (set VITE_DATA_SOURCE=mock)
 *
 * Backend endpoints used (adapter in ./backend.ts):
 *   POST /engage/batch · GET /drafts · GET /drafts/:id · POST /drafts/:id/{edit,approve,reject,send}
 *   GET /audit · GET /audit/:trace_id · GET /policy · GET /evaluation
 */
import type {
  AuditEvent,
  BlockedCase,
  DecisionResult,
  EvaluationSummary,
  PolicyConfig,
  QueueItem,
  QueueSummary,
  ReviewCase,
  ReviewDecision,
  ValidationCheck,
} from '../types';
import * as mock from '../data/mock';
import * as backend from './backend';

export interface Api {
  getQueue(): Promise<{ summary: QueueSummary; items: QueueItem[] }>;
  getReviewCase(id: string): Promise<ReviewCase | null>;
  getBlockedCase(id: string): Promise<BlockedCase | null>;
  revalidate(id: string, subject: string, body: string): Promise<ValidationCheck[]>;
  submitDecision(decision: ReviewDecision): Promise<DecisionResult>;
  escalate(id: string): Promise<{ ticketId: string }>;
  getPolicy(): Promise<PolicyConfig>;
  getEvaluation(): Promise<EvaluationSummary>;
  getAudit(): Promise<AuditEvent[]>;
  generate(): Promise<void>;
}

// ---------------------------------------------------------------- mock ---
const wait = <T,>(value: T, ms = 150) => new Promise<T>((r) => setTimeout(() => r(value), ms));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const eventId = () => 'evt-' + Math.random().toString(16).slice(2, 8);
const nowStamp = () =>
  new Date().toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).replace(',', '');

const queueState = clone(mock.queue);
const auditState = clone(mock.auditLog);

// Mirrors a subset of the backend's deterministic checks so edits can be
// re-validated locally in mock mode. The backend is the source of truth.
const BLOCKED = [/final warning/i, /legal action/i, /act now or lose/i, /guaranteed/i, /you failed to/i, /\b\d{12}\b/];

const mockApi: Api = {
  async generate() {},
  async getQueue() {
    const summary: QueueSummary = {
      ...mock.queueSummary,
      awaitingReview: queueState.filter((q) => q.status === 'ready' || q.status === 'attention').length,
      blocked: queueState.filter((q) => q.status === 'blocked').length,
      approved: queueState.filter((q) => q.status === 'approved').length,
    };
    return wait({ summary, items: clone(queueState) });
  },
  async getReviewCase(id) {
    return wait(mock.reviewCases[id] ? clone(mock.reviewCases[id]) : null);
  },
  async getBlockedCase(id) {
    return wait(mock.blockedCases[id] ? clone(mock.blockedCases[id]) : null);
  },
  async revalidate(id, subject, body) {
    const base = clone(mock.reviewCases[id]?.checks ?? []);
    const text = subject + '\n' + body;
    const hit = BLOCKED.find((re) => re.test(text));
    return wait(
      base.map((c) => {
        if (c.id === 'language' && hit) return { ...c, result: 'fail' as const, detail: `Blocked pattern found: ${hit.source}` };
        if (c.id === 'pii' && /\b\d{10,}\b/.test(text)) return { ...c, result: 'fail' as const, detail: 'Long number found in message body' };
        if (c.id === 'disclaimer' && !/support/i.test(body)) return { ...c, result: 'fail' as const, detail: 'Support / dispute line missing' };
        return c;
      }),
      300,
    );
  },
  async submitDecision(d) {
    const id = eventId();
    const row = queueState.find((q) => q.customerId === d.customerId);
    if (row) row.status = d.action === 'approve' ? 'approved' : 'rejected';
    auditState.unshift({
      at: nowStamp(),
      customerId: d.customerId,
      event: d.action === 'approve' ? (d.editedBody ? 'Reviewer edited, approved' : 'Reviewer approved') : 'Reviewer rejected',
      versions: mock.reviewCases[d.customerId]?.modelInfo.templateVersion ?? '—',
      policyDecision: d.feedback ? `Feedback: ${d.feedback.slice(0, 40)}` : 'Checks pass',
      sendStatus: d.action === 'approve' ? 'mock_outbox' : 'not_sent',
    });
    return wait({ auditEventId: id, sendStatus: d.action === 'approve' ? 'mock_outbox' : 'not_sent' } as DecisionResult);
  },
  async escalate(id) {
    auditState.unshift({ at: nowStamp(), customerId: id, event: 'Escalated to Billing Ops', versions: 'policy-v3.4', policyDecision: 'Removed from reminder cadence', sendStatus: 'blocked' });
    return wait({ ticketId: 'ESC-0412' });
  },
  async getPolicy() {
    return wait(clone(mock.policyConfig));
  },
  async getEvaluation() {
    return wait(clone(mock.evaluation));
  },
  async getAudit() {
    return wait(clone(auditState));
  },
};

// ---------------------------------------------------------------- http ---
const httpApi: Api = {
  getQueue: backend.getQueue,
  getReviewCase: backend.getReviewCase,
  getBlockedCase: backend.getBlockedCase,
  revalidate: backend.revalidate,
  submitDecision: backend.submitDecision,
  escalate: backend.escalate,
  generate: backend.generate,
  getPolicy: backend.getPolicy,
  getEvaluation: backend.getEvaluation,
  getAudit: backend.getAudit,
};

export const api: Api = import.meta.env.VITE_DATA_SOURCE === 'mock' ? mockApi : httpApi;
