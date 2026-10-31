# UC5 Customer Loyalty and Engagement Assistant — Ctrl Freaks

Drafts personalised customer emails for a telecom company and keeps a human in charge of every send.
Deterministic code makes every decision (segment, eligibility, offer, block); the LLM only writes the
email body, around locked placeholders, and never sees a customer's name, amount or date.

**Stack:** Python · FastAPI · Pydantic v2 · psycopg 3 · Supabase Postgres 16 · Gemini Flash (OpenAI-compatible
API) or the Claude API · React 18 + Vite + TypeScript review console · Docker Compose.

## Pipeline

| Step | What it does | Code / config |
|---|---|---|
| 1 Context builder | Loads permitted facts only; the six PII test fields are never selected | `app/domain/engage.py` `context()` |
| 2 Segment classifier | 5 rules, first match wins; confidence drops near a threshold | `classify()` · `policy.yaml`, `segmentation_rules.yaml` |
| 3 Pre-check gate | 8 stop signs (inactive, data conflict, consent, deliverability, dispute, hardship, cooldown) | `precheck()` · `policy.yaml`, `data_conflict_rules.yaml` |
| 4 Strategy selector | Message type, tone, 4 payment stages; stage 3 needs a reviewer note | `strategy()` · `policy.yaml` |
| 5 Offer validator | 5 gates (group, expiry, channel, tenure, repeat), first pass wins | `select_offer()` · `offers.yaml`, `offer_validator_rules.yaml` |
| 6 AI draft writer | LLM writes the body; failed drafts go back with the reasons, then rule-based fallback | `app/engage.py` `generate()` · `ai_prompt.yaml` |
| 7 Message validator | MV-01…MV-06: length, greeting, sign-off, PII, tone, placeholder integrity | `validate()` · `message_validator_rules.yaml` |
| 8 Human review | Approve, edit or reject in the console | `ui/` → `/drafts/*` |
| 9 Mock outbox | Outbox row, contact history and audit written in one transaction | `app/engage.py` `send()` |

Steps 3, 5 and 7 re-run on current data at edit, approve and send. Every step writes a row to `audit_log`,
which a trigger keeps insert-only. A blocked customer gets a stored draft with the reason code and nothing is sent.

## Layout

```
app/
  main.py            FastAPI endpoints
  engage.py          steps 6-9: AI writer, review actions, re-run gates, mock outbox, audit trail
  domain/engage.py   steps 1-5 and the step-7 validator (no AI); drafts/outbox tables
  policy.py          loads the YAMLs in config/
  llm.py             Gemini (OpenAI-compatible) or Claude client, MOCK_LLM mode
  evaluation.py      GET /evaluation: pipeline vs the answer key, review stats
  db.py schema.sql   Postgres pool and core tables (insert-only audit_log)
config/              the 7 rule YAMLs: every threshold lives here, not in code
data/dataset/        synthetic dataset, generator, validator, ground_truth.csv (answer key)
supabase/            schema.sql + seed.sql for the five data tables
eval/run_eval.py     per-step accuracy, confusion matrices, groundedness -> eval/report.md
tests_engage/        pytest suite (needs a throwaway Postgres)
ui/                  reviewer console (see ui/README.md)
```

## Configuration

| File | Holds |
|---|---|
| `config/policy.yaml` | Master: segment thresholds and order, strategy and tone mapping, pre-checks, message limits, locked placeholders, PII fields to drop |
| `config/segmentation_rules.yaml` | Rule ids SEG-01…05 and reason text |
| `config/data_conflict_rules.yaml` | The 9 data-conflict checks behind the `data_conflict` block |
| `config/offers.yaml` | Selection mode, gates, repeat guard, value formats; offer list mirrors `offer_catalog` (a test keeps them equal) |
| `config/offer_validator_rules.yaml` | Gates OV-01…05 and the allowed channels |
| `config/message_validator_rules.yaml` | MV-01…MV-06 patterns and tone-forbidden words |
| `config/ai_prompt.yaml` | Model, system and user prompts, tone guidance, subjects, retries, fallback templates |

Keys added on top of the original v2 configs are marked `# added` in the files.

## Run

**Local, everything in Docker** (Postgres seeded from `supabase/`, API, console):

```bash
cp .env.example .env        # set ADMIN_KEY; an LLM key, or MOCK_LLM=true
docker compose up           # open http://localhost:5173 and press "Classify new batch"
```

**Against Supabase**, without Docker:

```bash
pip install -r requirements-dev.txt
# .env: DATABASE_URL (Supabase), ADMIN_KEY, LLM settings (below)
uvicorn app.main:app --port 8000                # applies schema changes on startup
cd ui && npm install && npm run dev             # ui/.env needs the same ADMIN_KEY
```

Load the five data tables once in the Supabase SQL editor: `supabase/schema.sql`, then `supabase/seed.sql`.

| Setting (`.env`) | Meaning |
|---|---|
| `DATABASE_URL` | Supabase or local Postgres |
| `ADMIN_KEY` | Required by every staff endpoint; the console's dev proxy adds it, so it never reaches the browser |
| `LLM_PROVIDER` | `anthropic` (Claude, default) or `openai` (any OpenAI-compatible endpoint, e.g. Gemini) |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | Key for the chosen provider |
| `LLM_MODEL` | Overrides `model.model_id` in `ai_prompt.yaml` (e.g. `gemini-flash-latest`) |
| `MOCK_LLM` | `true` = no AI calls; every draft uses the fallback text |
| `BATCH_WORKERS` | Customers drafted in parallel by `/engage/batch` (default 4) |

Deploy: `vercel` serves the API from `index.py`. `eval/`, `data/` and `ui/` are not deployed, so
`/evaluation` answers 404 there and the console needs its own host.

## API

All endpoints except `/health`, `/policy` and `/audit/{trace_id}` need the `X-Admin-Key` header.
`X-Reviewer` names the reviewer on review actions.

| Endpoint | Purpose |
|---|---|
| `POST /engage` | Steps 1-7 for one customer `{"customer_id", "as_of_date"?}`; returns the existing draft if one is open |
| `POST /engage/batch` | `{"customer_ids"}`, or `{"limit": N}` for the next N customers without a draft; returns `remaining` |
| `GET /drafts` | List (`status`, `customer_id` filters); `full=true` returns every draft with details in one call |
| `GET /drafts/{id}` | One draft with segments, strategy, facts, checks, offer |
| `POST /drafts/{id}/edit` | Store reviewer text, re-run gates 5 and 7 |
| `POST /drafts/{id}/approve` · `/reject` · `/send` | Review decision; approve and send re-run gates 3, 5 and 7 |
| `GET /outbox` | Mock outbox, emails masked |
| `GET /audit` · `GET /audit/{trace_id}` | Newest audit rows; all steps of one request (owner or admin) |
| `GET /policy` | Every rule YAML, the offer catalogue and the AI writer settings |
| `GET /evaluation` | Steps 1-5 vs the answer key, plus review stats |
| `GET /health` | Database and LLM status |

## Tests and evaluation

```bash
docker compose up -d db                                  # throwaway Postgres; tests drop the public schema
pytest -q                                                # TEST_DATABASE_URL, never production
MOCK_LLM=true python eval/run_eval.py --label mock       # uses DATABASE_URL; read-only
```

Current results (seeded dataset, 222 customers):

- **39 tests** pass: answer key, PII never read, AI retries and fallback, validator, re-run gates, one-transaction send, insert-only audit, endpoints.
- **Eval:** all 16 checked fields 222/222 (segment, reasons, block reasons, strategy, offer, bill, amounts, conflicts…); 149/149 drafts pass every validator check; 73/73 customers that must not be contacted are blocked.
- **Live (Supabase + Gemini):** pages load in 0.5–2 s; an AI draft takes about 3.6 s with 4 in parallel; the evaluation runs in under 2 s.

## Known limits

- Gemini takes 7–10 s per call; drafting all customers takes several minutes even in parallel. Raise `BATCH_WORKERS` if your rate limit allows.
- Send writes to a mock outbox only; "Escalate" rejects the draft (no ticketing system).
- The console runs on the Vite dev server, whose proxy adds the admin key; a production host needs a server-side proxy that does the same.
- Mock sends add rows to `contact_history`, so later evaluations count those customers as in cooldown.
