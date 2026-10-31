# Engagement Assistant — Reviewer Console (frontend)

React + TypeScript + Vite frontend for the **Customer Loyalty and Engagement Assistant** use case.
It is the human-review layer (FR-08) on top of a backend that does classification, deterministic
policy checks and LLM drafting. Nothing is sent without a reviewer approving it.

## Screens

| Route | Screen | Covers |
| --- | --- | --- |
| `/` | Review queue: segment, confidence, strategy, checks, status; filter + search | FR-02, FR-03 |
| `/review/:customerId` | Review workspace: evidence, reason codes, strategy, grounded draft, 10 checks, rubric, approve / edit / reject | FR-01–FR-08 |
| `/blocked/:customerId` | Refused case: failed checks, source conflict, locked send, escalation | FR-07, FR-10 |
| `/policy` | Segment rules, approved offers, reminder stages, disclaimers, blocked language | Policy config |
| `/audit` | Evaluation metrics, confusion matrix, scenario coverage, audit log, JSON export | FR-09, evaluation |

## Run it

```bash
npm install
cp .env.example .env      # optional
npm run dev               # http://localhost:5173
```

By default the app runs on **synthetic mock data** (`src/data/mock.ts`), so it works with no backend.
Try: open CUS-10231 → *Edit draft* → type "final warning" → *Done editing*. The language check fails
and approval locks.

## Connect your backend

Set `VITE_DATA_SOURCE=http` in `.env`. The dev server proxies `/api/*` to `VITE_BACKEND_URL`
(default `http://localhost:8000`, e.g. FastAPI). Endpoints expected by `src/api/client.ts`:

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/queue` | `{ summary: QueueSummary, items: QueueItem[] }` |
| GET | `/api/customers/:id/review` | `ReviewCase` (404 if none) |
| GET | `/api/customers/:id/blocked` | `BlockedCase` (404 if not blocked) |
| POST | `/api/customers/:id/revalidate` | `ValidationCheck[]` — body `{ subject, body }` |
| POST | `/api/customers/:id/decision` | `DecisionResult` — body `ReviewDecision` |
| POST | `/api/customers/:id/escalate` | `{ ticketId }` |
| GET | `/api/policy` | `PolicyConfig` |
| GET | `/api/evaluation` | `EvaluationSummary` |
| GET | `/api/audit` | `AuditEvent[]` |

All shapes are defined in **`src/types.ts`**, which is the data contract. Make your Pydantic
models match it, or generate one from the other.

### Grounding display

`EmailDraft.paragraphs[].spans[]` carries `kind: 'plain' | 'grounded' | 'policy'` and an optional
`evidenceKey`. Have the backend return the draft already split into spans (e.g. the LLM fills
template slots, and slot values are tagged with the evidence field they came from). The UI then
highlights grounded facts in green and policy-controlled blocks in purple.

### Guardrails the UI enforces (the backend must enforce them too)

- Approve is disabled while any check is `fail`, while editing, or while re-validating.
- Any reviewer edit triggers `/revalidate` before approval is possible.
- Blocked cases have no approve path; Send is permanently disabled on that screen.
- The UI never calls a send endpoint directly. `decision` with `approve` queues to the mock outbox.

## Project structure

```
src/
  api/client.ts        mock + http implementations behind one interface
  api/useAsync.ts      small data-loading hook
  components/          Sidebar, Icon, chips, badges, stat cards
  data/mock.ts         synthetic customers, policy, evaluation, audit log
  pages/               QueuePage, ReviewPage, BlockedPage, PolicyPage, AuditPage
  styles/global.css    design tokens (colors, type) and all component styles
  types.ts             data contract
```

Design tokens (IBM Plex Sans/Mono, ink `#14171F`, accent teal `#0B5E5E`, segment color pairs)
live at the top of `global.css`.

All numbers and customers in `mock.ts` are synthetic placeholders. Replace the evaluation figures
with your real results before presenting.
