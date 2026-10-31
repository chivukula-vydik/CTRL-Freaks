"""Evaluation over data/dataset/ground_truth.csv. Read-only: nothing is written to the database.
    python -m eval.run_eval                 # uses DATABASE_URL and whatever LLM is configured (MOCK_LLM=true = no AI)
Prints per-step accuracy, a confusion matrix for the primary segment, block-reason accuracy and a groundedness count
(drafts that pass every check in config/message_validator_rules.yaml), and writes eval/report.md."""
import collections
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import engage, llm  # noqa: E402
from app.domain import engage as D  # noqa: E402
from eval import groundtruth as gt  # noqa: E402


def table(rows: list[list[str]]) -> str:
    w = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)) for r in rows)


def main() -> int:
    key = gt.load()
    llm.reset_usage()
    per_step = collections.Counter()
    fails = collections.defaultdict(list)
    seg_cm, block_cm = collections.Counter(), collections.Counter()
    drafted = grounded = ai = fallback = 0
    pre = D.preload()
    for cid, g in key.items():
        d = engage.decide(cid, pre=pre)
        exp, got = gt.expected(g), gt.got(d)
        mm = gt.mismatches(d, g)
        for k in gt.FIELDS:
            per_step[k] += k not in mm
        for k, (a, e) in mm.items():
            fails[k].append((cid, g["scenario_tag"], a, e))
        seg_cm[(exp["segment"], got["segment"])] += 1
        block_cm[(exp["block"] or "none", got["block"] or "none")] += 1
        if not d["blocks"]:
            drafted += 1
            out = engage.generate(d)
            issues = D.validate(out, d["facts"], d["strategy"], d["offer"])
            grounded += not issues
            ai += out["source"] == "ai"
            fallback += out["source"] == "fallback"
    n = len(key)
    segs = sorted({k[0] for k in seg_cm} | {k[1] for k in seg_cm})
    lines = [f"# Evaluation, {n} customers", "", "## Accuracy per step (deterministic pipeline vs ground_truth.csv)", ""]
    lines += [f"- {k}: {per_step[k]}/{n}" for k in gt.FIELDS]
    lines += ["", "## Primary segment confusion matrix (rows = expected, columns = predicted)", "", "```",
              table([["expected \\ got"] + segs] + [[e] + [str(seg_cm[(e, p)]) for p in segs] for e in segs]), "```"]
    blocks = sorted({k[0] for k in block_cm} | {k[1] for k in block_cm})
    lines += ["", "## First block reason confusion matrix", "", "```",
              table([["expected \\ got"] + blocks] + [[e] + [str(block_cm[(e, p)]) for p in blocks] for e in blocks]), "```",
              "", "## Drafts", "",
              f"- customers with a draft: {drafted}",
              f"- grounded (all message_validator_rules checks pass, no injected digits/dates/offers): {grounded}/{drafted}",
              f"- written by the AI: {ai}, plain fallback text: {fallback}",
              f"- LLM usage: {llm.usage()}"]
    for k, items in fails.items():
        lines += ["", f"## Mismatches: {k} ({len(items)})", ""] + [f"- {c} [{t}] got {a!r}, expected {e!r}" for c, t, a, e in items[:20]]
    report = "\n".join(lines)
    print(report)
    (Path(__file__).parent / "report.md").write_text(report + "\n", encoding="utf-8")
    return 0 if not fails and grounded == drafted else 1


if __name__ == "__main__":
    sys.exit(main())
