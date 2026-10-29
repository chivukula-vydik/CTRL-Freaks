"""LLM-generated synthetic data, schema-enforced. Fill TABLES + EDGE_CASES once the schema is known.

  python scripts/gen_synthetic.py --out data/generated --table customers --n 30
Writes <table>.csv and appends the exact prompt + model to data/generated/prompts.md (deliverable).
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, llm  # noqa: E402

# TODO on the day: copy the fixed schema from the problem doc. column -> constraint text for the prompt
TABLES: dict[str, dict[str, str]] = {
    "customers": {"customer_id": "C followed by 4 digits, unique, not C9000-C9999",
                  "full_name": "synthetic Indian name", "tier": "STANDARD|GOLD|PLATINUM",
                  "city": "Indian city", "joined_year": "2015-2026"},
}
# TODO: deliberate edge cases the problem doc lists, each must map to a concrete row
EDGE_CASES: list[str] = []

PROMPT = """Generate {n} rows of synthetic data for table `{table}`.
Columns and rules:
{cols}
{edges}
Return ONLY JSON: {{"rows": [{{...}}, ...]}} with exactly these keys. No real people."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", type=Path, default=Path("data/generated"))
    a = ap.parse_args()
    cols = TABLES[a.table]
    prompt = PROMPT.format(n=a.n, table=a.table, cols="\n".join(f"- {k}: {v}" for k, v in cols.items()),
                           edges=("Must include these edge cases:\n- " + "\n- ".join(EDGE_CASES)) if EDGE_CASES else "")
    out = llm.chat_json("You generate realistic synthetic test data that satisfies every rule.", prompt,
                        required=["rows"])
    if not out:
        sys.exit("LLM unavailable (MOCK_LLM or Ollama down)")
    rows = [{k: r.get(k) for k in cols} for r in out["rows"] if set(cols) <= set(r)]
    a.out.mkdir(parents=True, exist_ok=True)
    with (a.out / f"{a.table}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cols))
        w.writeheader()
        w.writerows(rows)
    with (a.out / "prompts.md").open("a") as f:
        f.write(f"\n## {a.table} ({datetime.now():%Y-%m-%d %H:%M}, model {config.LLM_MODEL})\n```\n{prompt}\n```\n"
                f"kept {len(rows)}/{len(out['rows'])} rows after key check; run scripts/load_data.py to validate\n")
    print(json.dumps({"table": a.table, "rows": len(rows)}))


if __name__ == "__main__":
    main()
