"""Extraction eval: run every doc through app/extract.py, score field values against expected rows.

  python eval/run_extract.py --label mock                      # active DOMAIN's <pack>/extract/
  python eval/run_extract.py --dir examples/extract/data/extract --label gemini

Folder: schema.json, docs/, expected.jsonl ({"doc": "<file name>", "<field>": <value>, ...}).
Writes eval/reports/extract_<label>.json and the output rows as extract_<label>.csv.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "eval" / "reports"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, help="default: <active pack>/extract")
    ap.add_argument("--label", default="run")
    a = ap.parse_args()
    from app import config
    from app.domain import pack_dir
    from app.extract import extract_file, score
    d = a.dir or pack_dir() / "extract"
    schema = json.loads((d / "schema.json").read_text())
    expected = [json.loads(x) for x in (d / "expected.jsonl").read_text().splitlines() if x.strip()]
    rows = [extract_file(p, schema) for p in sorted((d / "docs").iterdir()) if p.is_file()]
    s = score(rows, expected, schema)
    s.update(label=a.label, n_docs=len(rows), model="mock" if config.MOCK_LLM else config.LLM_MODEL,
             valid_rows=round(sum(r["_valid"] for r in rows) / (len(rows) or 1), 3))
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"extract_{a.label}.json").write_text(json.dumps({"summary": s, "rows": rows}, indent=2, default=str))
    with open(REPORTS / f"extract_{a.label}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["doc", *schema["fields"], "_valid", "_errors"], extrasaction="ignore")
        w.writeheader()
        w.writerows({**r, "_errors": "; ".join(r["_errors"])} for r in rows)
    for x in s["failures"]:
        print(f"FAIL {x['doc']} {x['field']}: got {x['got']!r} expected {x['expected']!r}")
    print(json.dumps({k: v for k, v in s.items() if k != "failures"}, indent=2))


if __name__ == "__main__":
    main()
