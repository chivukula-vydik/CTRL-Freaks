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
