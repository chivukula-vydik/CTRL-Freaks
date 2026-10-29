# RAG Agent Skeleton (HCL AI Engineer Hackathon)

Domain-agnostic grounded RAG agent with an open FastAPI surface. The core is built and tested.
A new problem statement is one scaffold command plus filling one config-style file:
**see [INTEGRATION.md](INTEGRATION.md)**.

**Stack:** FastAPI + Pydantic v2, LangGraph, Qdrant (vectors), Supabase Postgres (tables),
Gemini (LLM + embeddings, OpenAI-compatible endpoint), Streamlit, deployed on Vercel.

## Layout

```
app/                   core, do not edit on the day
  main.py              API endpoints
  agent.py             LangGraph flow: guard -> tools -> retrieve -> compose -> audit
  ingest/ retrieval/   parsing + chunking, Qdrant + BM25 hybrid search
  precedence.py        source precedence policy (Annex A)
  rules.py             rule registry lookups with precedence
  guard.py llm.py      safety helpers, Gemini client with mock mode
  db.py                Supabase Postgres (pooled; SQLite-style ? params translated)
  domain/base.py       the domain contract + default behaviour (auth, matching, tool loop, loaders)
  domain/generic.py    default domain: pure grounded RAG, runs as-is
  domain/<yours>.py    created by scripts/new_domain.py   <-- the only code you write
data/<yours>/          docs, source_register.csv, csv/, eval_set.jsonl   <-- your data pack
examples/retail/       complete worked example (domain + data + eval + tests), delete before submit
scripts/               new_domain.py, load_data.py, gen_synthetic.py
eval/run_eval.py       metrics + config comparison
tests/                 contract + precedence tests, pass for ANY domain
ui/app.py              Streamlit
```

## Run

```bash
pip install -r requirements-dev.txt
cp .env.example .env                        # DATABASE_URL, QDRANT_URL/KEY, GEMINI_API_KEY
python scripts/load_data.py                 # loads the active domain's data pack into Supabase + Qdrant
uvicorn app.main:app --reload               # http://localhost:8000/docs
API_URL=http://localhost:8000 streamlit run ui/app.py
```

Deploy: `vercel` (entrypoint `index.py`), then add the same env vars with `vercel env add`. Use
Supabase's transaction pooler URI (port 6543) for `DATABASE_URL`. Streamlit does not run on Vercel;
run it locally or on Streamlit Cloud with `API_URL` set to the Vercel URL.
Offline: `MOCK_LLM=true EMBED_BACKEND=hash QDRANT_URL=:memory:`.

Worked example: set `DOMAIN=retail`, then `python scripts/load_data.py` and ask
`{"question":"Can I return the headphones from order O-100001?","as_of_date":"2026-10-06"}`
with header `X-Customer-Id: C1001`.

## How it decides

A **fixed LangGraph workflow, not multi-agent**, on purpose: HCL scores the simplest design that
meets the requirements. Code makes every decision and calculation. The LLM only (1) picks an
intent from a closed list when regex can't, (2) writes answers from retrieved text, (3) explains
tool output. A guard drops any explanation containing a number the tools didn't produce. Every
LLM call has a deterministic fallback, so `MOCK_LLM=true` runs the whole pipeline.

| Capability | Where |
|---|---|
| Live ingest (PDF, DOCX, MD, TXT, OCR for scans) with Source Register metadata, no restart | `app/ingest/` |
| Hybrid retrieval: Qdrant vectors + BM25, reciprocal rank fusion | `app/retrieval/store.py` |
| Precedence: applicability, supersession, authority, recency, unresolved = conflict | `app/precedence.py` |
| Every tool threshold from `rule_registry`, resolved by the same precedence, cited | `app/rules.py`, `ctx.rule()` |
| Answer types: retrieved_fact, calculated, not_found, clarification_needed, refused, conflict_flagged | `app/schemas.py` |
| Identity only from header; same refusal whether another user's record exists or not | `app/agent.py` n_guard |
| Instruction-like text in docs / notes neutralised, never triggers a tool | `app/guard.py` |
| Audit record per answer: sources, tools with I/O, rules, conflicts, model, tokens, latency | `GET /audit/{id}` |

## API

| Endpoint | Purpose |
|---|---|
| `POST /ask` | `{"question", "as_of_date"?}` + user header (`SUBJECT_HEADER`, default `X-Customer-Id`) |
| `POST /ingest` | multipart `file` + `metadata` JSON (Source Register fields, optional `rules`, `extract_rules`) |
| `GET /health` | API, vector store, database, LLM status |
| `GET /audit/{trace_id}` | owner (same header) or admin (`X-Admin-Key`); anyone else gets 404 |
| `GET /sources`, `GET /rules` | Source Register, rule registry |
| `POST /admin/rules?source_doc_id=` | add or replace one rule (admin) |
| `POST /admin/load-data` | upload judge CSVs, one `<table>.csv` per table (admin) |

```bash
curl -X POST localhost:8000/ingest -F file=@circular.pdf -F 'metadata={
  "doc_id":"CIRC-2026-10","title":"Window change","authority_level":2,"effective_from":"2026-10-01",
  "supersedes":"CIRC-2026-07#1","scope_categories":"ELECTRONICS",
  "rules":[{"rule_id":"RET-WIN-ELEC-03","parameter":"return_window_days","value":"5",
            "scope_categories":"ELECTRONICS","source_section":"1"}]}'
```

## Precedence policy (as implemented)

1. **Applicability**: in force on `as_of_date` and scope covers the request. Not-yet-effective items go to `upcoming_changes`, never applied.
2. **Supersession**: an in-force level 1-2 doc whose `supersedes` names `DOC` or `DOC#section`, and whose scope covers the request, removes it.
3. **Authority**: lower level wins, regardless of date.
4. **Recency**: same level, later `effective_from` wins.
5. Tiebreak (our stated assumption): same level and date, the more specific scope wins.
6. Still different values: `conflict_flagged`, both cited.

Level 5 (unofficial) never sets a rule. A question with no tier only matches ALL-tier rules.

## Tests and eval

```bash
docker compose up -d db                     # throwaway Postgres; tests TRUNCATE, never use prod
pytest -q                                   # contract + precedence, any DOMAIN (Qdrant in-memory)
DOMAIN=retail pytest -q examples/retail     # 17 worked-example tests
EMBED_BACKEND=hash MOCK_LLM=true python eval/run_eval.py --label mock        # fresh store, active pack
python eval/run_eval.py --base-url http://localhost:8000 --label topk6        # real stack
```

Eval method: exact match on answer type, numbers and tool outputs; citation = expected doc cited;
retrieval hit = expected doc retrieved. No LLM judge. `eval/reports/comparison.md` tabulates
all runs (the "compare two configurations" deliverable).

Retail example, mock LLM + hash embeddings (a floor, not the real stack): correctness 0.96,
citation 0.91, abstention 0.96, tools 1.0, retrieval hit 1.0.

## Known limits

- `MIN_RELEVANCE` must be tuned per embedding model; sweep it with the eval.
- Section detection is regex on numbered headings; unusual layouts may need a parser tweak.
- `extract_rules=true` lets the LLM propose rules from an unseen doc, restricted to known parameters and numeric values; review via `GET /rules`.
- Not yet run end to end against live Supabase + Qdrant Cloud + Gemini; the store and SQL translation were checked offline (Qdrant in-memory).
