# Plugging in the problem statement (day-of runbook)

Goal: one end-to-end cited answer within the first hour, then widen. The core (`app/` minus
`app/domain/<yours>.py`) does not change.

## 0. Kickoff (all, first 20 min)

Read the problem doc and mark these, they map 1:1 to the files below:

| In the problem doc | Goes into |
|---|---|
| Fixed data schema (tables, id formats, reserved ids) | `SCHEMA`, `SUBJECT_ID`, `RECORD_ID`, `VALIDATIONS` |
| Header that identifies the user | `SUBJECT_HEADER` in `.env` |
| Question types table | `INTENT_WORDS`, `PLAN`, eval set tags |
| Thresholds tools must use (windows, fees, limits) | `PARAMETERS` + `csv/rule_registry.csv` |
| Categories / tiers that rules are scoped by | `CATEGORY_WORDS`, `TIERS` |
| Calculations / eligibility logic | `@tool` methods |
| API contract (paths, response fields, answer types) | check against `app/schemas.py`, `app/main.py` |
| Precedence policy | check against `app/precedence.py` (built to the HCL Annex A) |

Then the integrator runs, commits and pushes:

```bash
python scripts/new_domain.py <name>      # app/domain/<name>.py + data/<name>/ + DOMAIN in .env
```

## 1. Parallel work (who does what)

| Role | Owns | First milestone |
|---|---|---|
| P3 AI core | `app/domain/<name>.py`: TODO 3-7 (identity, targets, intents, PLAN, tools) | one tool answer via `/ask` |
| P2 Backend | TODO 1-2 (`SCHEMA`, `VALIDATIONS`), judge loader check, contract diffs in `schemas.py`/`main.py` if the doc differs | `python scripts/load_data.py --dir <csvs>` loads clean |
| P4 Data/eval | `data/<name>/`: docs + `source_register.csv`, `csv/rule_registry.csv`, synthetic CSVs via `scripts/gen_synthetic.py`, `eval_set.jsonl` | 20+ eval lines covering every required category |
| P1 Frontend | `ui/app.py` relabels (header name, fields), demo script for the 10-min slot | UI shows a cited answer |
| P5 Integrator | merges, `pytest -q`, eval runs, README, tags `final` | green `pytest` on `main` every merge |

## 2. Fastest path to first answer

1. P4 drops ONE doc into `data/<name>/docs/` and one row in `source_register.csv`.
2. `python scripts/load_data.py` then `uvicorn app.main:app`.
3. `POST /ask` a question from that doc. A cited `retrieved_fact` back = RAG path done.
4. P3 fills one intent + one tool, P4 adds one rule row and a few data rows. A `calculated` answer back = tool path done.

## 3. Data pack layout

```
data/<name>/
  docs/                    the documents (pdf, docx, md, txt, scans)
  source_register.csv      one row per doc + a `file` column naming it in docs/
  csv/rule_registry.csv    every threshold, each linked to doc + section
  csv/<table>.csv          synthetic data, one file per SCHEMA table
  eval_set.jsonl           eval questions
```

Eval line format:

```json
{"id": "T01", "tags": ["tools", "last_day"], "customer_id": "C1001", "question": "...",
 "as_of": "2026-10-06", "expected_type": "calculated", "expect_contains": ["7"],
 "expected_source": "DOC-ID", "expected_tools": {"tool_name": {"result": "ELIGIBLE"}}}
```

## 4. Before code freeze

- `pytest -q` (contract + precedence, any domain) and the eval with the real model: `python eval/run_eval.py --base-url http://localhost:8000 --label final`
- Two eval runs with different settings (e.g. `TOP_K=4` vs `8`) for the comparison table
- Delete `examples/` if the judges should only see your domain (nothing in `app/` depends on it)
- README: replace the sample numbers with yours, fill the AI-usage and contribution sections
- `git tag final && git push --tags`

## Tool cheat sheet

```python
@tool
def check_x(self, ctx):
    row = ctx.q1("SELECT ... WHERE id = ? AND owner = ?", (ctx.target["id"], ctx.sid))  # always scope by ctx.sid
    limit = float(ctx.rule("x_limit"))          # from rule_registry, precedence applied, cited
    days = ctx.und.what_if.get("days", ...)     # what-if override
    if ctx.wants("refund"): ...                 # which intents were asked
    return {"result": "OK", "value": 1,          # recorded in tools_invoked + audit
            "_say": "Sentence for the answer.",  # deterministic answer text
            "_next": ["other_tool"],             # chain
            "_followup": "how to appeal steps"}  # pulls cited procedure text from the docs
```

## If the problem is field extraction from documents

Scored on exact field values per document, not chat answers. No domain code: one JSON schema.

```
data/<name>/extract/
  schema.json        {"fields": {"<field>": {"type": "str|number|date|bool", "required", "labels",
                                              "hint", "pattern", "enum", "min", "max", "tol"}}}
  docs/              the documents (pdf, docx, txt, scans)
  expected.jsonl     {"doc": "<file name>", "<field>": <value>, ...}   one line per doc
```

Flow (`app/extract.py`): parse -> LLM returns `{field: {value, quote}}` -> code drops any value whose
quote is not in the doc, coerces types (`12.5 lakh` -> 1250000, `3rd March 1990` -> 1990-03-03,
`(1,234)` -> -1234), checks `pattern/enum/min/max/required` -> one row with `_sources` (quote + page),
`_errors`, `_valid`. `MOCK_LLM=true` falls back to `Label: value` lines using `labels`.

- API: `POST /extract` multipart `files` (many), optional `fields_json` form field
- Eval: `python eval/run_extract.py --label x` -> field accuracy, doc exact match, per-field accuracy,
  failures, and the output rows as `eval/reports/extract_x.csv`
- Cross-field checks (field A = B + C, etc.) go after `extract_file()` in the caller

## If the problem is a data pipeline + analytics over CSVs

Scored on correct numbers and data quality. No domain code: one JSON schema.

```
data/<name>/pipeline/
  schema.json        tables (columns: type, required, default, pattern, enum, min, max, filterable; key)
                     + metrics (op sum|avg|count|min|max|median|count_distinct|ratio, column, where,
                       join, date_column, label, words)            full format: app/pipeline.py header
  csv/<table>.csv    raw data, dirty is fine
  expected.jsonl     {"id","question","expected"} | {"id","question","expected_type":"not_found"}
                     | {"id","dq":"<table>.rows_rejected","expected":6}
```

Flow (`app/pipeline.py`): read CSV -> schema check (missing/extra columns) -> clean (trim, null
tokens, number/date parsing, enum to canonical spelling, defaults) -> rejected rows with line number
+ reasons (bad type, required missing, rule broken, duplicate key) and exact duplicates dropped ->
data-quality report per table (counts, nulls, fills, rejections by column, orphan join keys) ->
`calc()`, the one calculation tool -> `ask()` picks metric (words, else LLM from the closed list),
filters (enum/filterable values named in the question), "by <column>" grouping, time buckets
("monthly", "by quarter"), ranking ("top 5 <column>", "lowest"), dates (ISO, YYYY-MM, Q1 2024, "in 2024") by code. The LLM never does maths; `MOCK_LLM=true` runs everything.

- API: `POST /admin/pipeline/upload` (`<table>.csv` files, admin key, returns DQ report),
  `GET /pipeline/report`, `GET /pipeline/metrics`, `POST /pipeline/calc` `{"metric","filters"?,"group_by"? (col or date_col:month|quarter|year),
  "date_from"?,"date_to"?,"top"?,"bottom"?}`, `POST /pipeline/ask` `{"question"}`
- Eval: `python eval/run_pipeline.py --label x` -> calc accuracy, DQ accuracy, rejected rows CSV
- A calculation the ops can't express: add a function next to `calc()` and call it from the endpoint

## Optional plug-ins (all off by default, set in the domain class)

| Need in the problem doc | Set | Default |
|---|---|---|
| Exact not-found / refusal wording | `NOT_FOUND_MSG`, `REFUSE_OTHER_MSG`, `REFUSE_LOGIN_MSG`, `OUT_OF_SCOPE_MSG` | generic text |
| "Do not give investment advice / diagnoses" | `OUT_OF_SCOPE = COMMON_OUT_OF_SCOPE + [r"...", ...]` -> `refused` | `[]` |
| Cite a live system, e.g. "Hospital Scheduling System" | `SYSTEM_NAME = "..."` -> tool answers get a citation with `system` set | `""` |
| Agent changes data (book, cancel, block card) | `@action(risk="low"\|"medium"\|"high")` instead of `@tool`, writes only via `ctx.execute(sql, params)` | none |

Actions: `low` runs at once; `medium` answers `clarification_needed` with an `action_id`, then
`POST /ask {"question": "yes", "confirm_action_id": "<id>"}` (same user header) runs it -> `action_completed`;
`high` is stored as `pending_approval` and never run by the agent. Every action has a row in `actions`
and the audit record holds before/after rows. `ctx.execute` must scope rows with `:sid` (bound to the
logged-in user). Example: `raise_return` in `examples/retail/domain.py`.

Degraded mode: if embeddings fail, retrieval goes keyword-only (BM25), sets `safety_flags.embedding_fallback`
and adds an assumption. LLM/embedding errors and 429s are counted per request in the audit record
(`llm_errors`, `llm_rate_limited`, `embed_errors`) and per instance in `/health`. `ADMIN_KEY` is required.
