"""Run the eval set and report Section 7 metrics. Method: exact match / substring on numbers and
types, plus citation-doc match. No LLM judge (deterministic and cheap to re-run).

  # in-process, fresh store loaded from the active domain's pack, mock LLM (fast, CI)
  EMBED_BACKEND=hash MOCK_LLM=true DOMAIN=retail python eval/run_eval.py --label mock  # needs `docker compose up db`
  # against the running API (real Ollama + sentence-transformers)
  python eval/run_eval.py --base-url http://localhost:8000 --label topk6
  # compare configs: run twice with different env (TOP_K=4 / TOP_K=8, CHUNK_CHARS...), reports are tabulated
"""
import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "eval" / "reports"


def make_client(base_url: str | None, fresh: bool, pack: Path | None):
    if base_url:
        import httpx
        return httpx.Client(base_url=base_url, timeout=300)
    from fastapi.testclient import TestClient

    from app import db
    from app.loader import load_pack
    from app.main import app
    db.init_db()
    db.reset()
    load_pack(pack)
    return TestClient(app)


def check(case: dict, r: dict, audit: dict) -> dict:
    tools = {t["tool"]: t["output"] for t in r.get("tools_invoked", [])}
    ok_type = r["answer_type"] == case["expected_type"]
    ok_text = all(s.lower() in r["answer"].lower() for s in case.get("expect_contains", []))
    ok_tools = True
    for tool, exp in case.get("expected_tools", {}).items():
        out = tools.get(tool)
        ok_tools &= out is not None and all(out.get(k) == v for k, v in exp.items())
    cited = {c["doc_id"] for c in r.get("citations", [])}
    src = case.get("expected_source")
    retrieved = [s["doc_id"] for s in audit.get("sources_retrieved", [])]
    return {
        "id": case["id"], "tags": case.get("tags", []), "answer_type": r["answer_type"],
        "correct": ok_type and ok_text and ok_tools,
        "citation_ok": (src in cited) if src else None,
        "abstain_ok": (r["answer_type"] == "not_found") == (case["expected_type"] == "not_found"),
        "tools_ok": ok_tools if case.get("expected_tools") else None,
        "retrieval_hit": (src in retrieved or src in cited) if src else None,
        "upcoming_ok": bool(r.get("upcoming_changes")) if case.get("expect_upcoming") else None,
        "latency_ms": audit.get("latency_ms"), "llm_calls": audit.get("llm_calls", 0),
        "tokens": audit.get("tokens", 0), "answer": r["answer"][:200],
    }


LOCAL_TEST_DB = "postgresql://postgres:postgres@localhost:5432/postgres"  # docker compose `db`


def rate(rows, key):
    vals = [x[key] for x in rows if x[key] is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, help="data pack (default: active DOMAIN's pack)")
    ap.add_argument("--set", type=Path, help="eval set (default: <pack>/eval_set.jsonl)")
    ap.add_argument("--base-url")
    ap.add_argument("--label", default="run")
    ap.add_argument("--admin-key", default=os.getenv("ADMIN_KEY"))
    a = ap.parse_args()
    if a.pack:
        os.environ["PACK_DIR"] = str(a.pack)
    if not a.base_url:  # fresh store on the TEST database, set before any app import reads config
        os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL", LOCAL_TEST_DB)
        os.environ["QDRANT_URL"] = ":memory:"
    from app.domain import pack_dir
    from app.main import SUBJECT_HEADER
    pack = pack_dir()
    eval_set = a.set or pack / "eval_set.jsonl"
    if not eval_set.exists():
        sys.exit(f"no eval set at {eval_set}")
    client = make_client(a.base_url, fresh=True, pack=pack)
    cases = [json.loads(x) for x in eval_set.read_text().splitlines() if x.strip()]
    rows = []
    for c in cases:
        h = {SUBJECT_HEADER: c["customer_id"]} if c.get("customer_id") else {}
        t = time.time()
        r = client.post("/ask", json={"question": c["question"], "as_of_date": c.get("as_of", "2026-10-06")},
                        headers=h).json()
        audit = client.get(f"/audit/{r['trace_id']}", headers={"X-Admin-Key": a.admin_key}).json()
        audit.setdefault("latency_ms", int((time.time() - t) * 1000))
        rows.append(check(c, r, audit))

    lat = [x["latency_ms"] for x in rows]
    summary = {
        "label": a.label, "n": len(rows),
        "env": {k: os.getenv(k) for k in ("EMBED_BACKEND", "EMBED_MODEL", "LLM_MODEL", "MOCK_LLM", "TOP_K",
                                          "CHUNK_CHARS", "MIN_RELEVANCE")},
        "answer_correctness": rate(rows, "correct"), "citation_accuracy": rate(rows, "citation_ok"),
        "abstention_accuracy": rate(rows, "abstain_ok"), "tool_correctness": rate(rows, "tools_ok"),
        "retrieval_hit_rate": rate(rows, "retrieval_hit"),
        "latency_p50_ms": statistics.median(lat), "latency_p95_ms": sorted(lat)[max(0, int(len(lat) * .95) - 1)],
        "llm_calls_per_q": round(sum(x["llm_calls"] for x in rows) / len(rows), 2),
        "tokens_per_q": round(sum(x["tokens"] for x in rows) / len(rows), 1),
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{a.label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2))

    for x in rows:
        if not x["correct"]:
            print(f"FAIL {x['id']:4} [{x['answer_type']}] {x['answer']}")
    print(json.dumps(summary, indent=2))
    # comparison table across all saved runs
    keys = ["answer_correctness", "citation_accuracy", "abstention_accuracy", "tool_correctness",
            "retrieval_hit_rate", "latency_p50_ms", "latency_p95_ms", "tokens_per_q"]
    lines = ["| run | " + " | ".join(keys) + " |", "|---" * (len(keys) + 1) + "|"]
    for f in sorted(REPORTS.glob("*.json")):
        s = json.loads(f.read_text())["summary"]
        lines.append(f"| {s['label']} | " + " | ".join(str(s.get(k)) for k in keys) + " |")
    (REPORTS / "comparison.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
