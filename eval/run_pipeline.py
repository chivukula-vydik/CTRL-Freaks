"""Pipeline eval: clean the CSVs, then score answers and data-quality numbers against expected.jsonl.

  python eval/run_pipeline.py --label mock                     # active DOMAIN's <pack>/pipeline/
  python eval/run_pipeline.py --dir examples/pipeline/data --label x

expected.jsonl lines (tol = absolute tolerance, default 0.01):
  {"id": "Q1", "question": "...", "expected": 123.4}              number, or {"group": number}
  {"id": "Q2", "question": "...", "expected_type": "not_found"}
  {"id": "D1", "dq": "<table>.rows_rejected", "expected": 6}       any dotted path into the DQ report
Writes eval/reports/pipeline_<label>.json and the rejected rows as pipeline_<label>_rejected.csv.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "eval" / "reports"


def close(got, exp, tol: float) -> bool:
    if isinstance(exp, dict):
        return isinstance(got, dict) and got.keys() == exp.keys() and all(close(got[k], exp[k], tol) for k in exp)
    if isinstance(exp, (int, float)) and isinstance(got, (int, float)):
        return abs(got - exp) <= tol
    return got == exp


def dig(report: dict, path: str):
    t, _, rest = path.partition(".")
    cur = report.get(t, {})
    for k in rest.split(".") if rest else []:
        # keys like "item_id->items" contain no dots, so a plain split works
        cur = cur.get(k) if isinstance(cur, dict) else None
    return cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, help="pack dir holding pipeline/ (default: active pack)")
    ap.add_argument("--label", default="run")
    a = ap.parse_args()
    from app.domain import pack_dir
    from app.pipeline import ask, load
    pack = a.dir or pack_dir()
    schema, res = load(pack, uploads=False)   # score the pack files, never live uploads
    cases = [json.loads(x) for x in (pack / "pipeline" / "expected.jsonl").read_text().splitlines() if x.strip()]
    rows = []
    for c in cases:
        tol = c.get("tol", 0.01)
        if "dq" in c:
            got = dig(res["report"], c["dq"])
            rows.append({"id": c["id"], "kind": "dq", "ok": close(got, c["expected"], tol), "got": got,
                         "expected": c["expected"]})
            continue
        r = ask(schema, res["tables"], c["question"])
        got = (r["calculation"] or {}).get("value")
        ok = r["answer_type"] == c["expected_type"] if "expected_type" in c else \
            r["answer_type"] == "calculated" and close(got, c["expected"], tol)
        rows.append({"id": c["id"], "kind": "calc", "ok": ok, "got": got, "expected": c.get("expected"),
                     "answer": r["answer"]})
    rate = lambda k: round(sum(x["ok"] for x in rows if x["kind"] == k) / max(1, sum(x["kind"] == k for x in rows)), 3)  # noqa: E731
    summary = {"label": a.label, "calc_accuracy": rate("calc"), "dq_accuracy": rate("dq"), "n": len(rows),
               "rows_rejected": len(res["rejected"])}
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"pipeline_{a.label}.json").write_text(json.dumps(
        {"summary": summary, "rows": rows, "report": res["report"]}, indent=2, default=str))
    with open(REPORTS / f"pipeline_{a.label}_rejected.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["table", "line", "reasons", "row"])
        w.writerows([b["table"], b["line"], "; ".join(b["reasons"]), json.dumps(b["row"])] for b in res["rejected"])
    for x in rows:
        if not x["ok"]:
            print(f"FAIL {x['id']}: got {x['got']!r} expected {x['expected']!r}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
