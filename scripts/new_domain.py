"""Scaffold a domain for a new problem statement.

  python scripts/new_domain.py hospital

Creates app/domain/<name>.py (fill the TODOs), data/<name>/ (docs, register, csv, eval set)
and sets DOMAIN=<name> in .env. Nothing else in the repo needs to change.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TEMPLATE = '''"""{title} domain. Fill every TODO from the problem statement; see examples/retail/domain.py."""
import re
from datetime import date

from app.domain.base import Domain, Understanding, tool


class {cls}(Domain):
    name = "{name}"

    # TODO 1. Fixed data schema from the problem doc, VERBATIM (judges load CSVs in it).
    # Order tables parent -> child: the CSV loader inserts in this order.
    SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
  subject_id TEXT PRIMARY KEY, full_name TEXT NOT NULL, tier TEXT);
CREATE TABLE IF NOT EXISTS records (
  record_id TEXT PRIMARY KEY, subject_id TEXT NOT NULL REFERENCES subjects(subject_id),
  item_name TEXT, category TEXT, created_on TEXT, status TEXT);
"""
    # TODO 2. Logical constraints the doc lists: (label, SQL returning the violating rows)
    VALIDATIONS = [
        ("record without subject", "SELECT record_id FROM records WHERE subject_id NOT IN (SELECT subject_id FROM subjects)"),
    ]

    # TODO 3. Identity. Logged-in user comes ONLY from the header (SUBJECT_HEADER in .env).
    SUBJECT_ID = re.compile(r"\\bS\\d{{4}}\\b", re.I)          # id format of a user
    SUBJECT_TABLE, SUBJECT_KEY, SUBJECT_TIER_COL = "subjects", "subject_id", "tier"
    RECORD_ID = re.compile(r"\\bR-\\d{{6}}\\b", re.I)          # id format of a user's record
    RECORD_TABLE, RECORD_KEY, RECORD_SUBJECT_COL = "records", "record_id", "subject_id"

    # TODO 4. What a personal question can point at. :sid = logged-in user.
    TARGETS_SQL = """SELECT r.* FROM records r WHERE r.subject_id = :sid ORDER BY r.created_on DESC"""
    TARGET_ID_COLS = ["record_id"]      # logged as tool input
    TARGET_NAME_COL = "item_name"       # matched against words in the question
    TARGET_CATEGORY_COL = "category"    # scope category for rules

    # TODO 5. Intents (regex first; LLM fallback is automatic and restricted to these names)
    INTENT_WORDS = {{
        "status": [r"\\bstatus\\b", r"where is", r"\\btrack"],
        "eligibility": [r"\\bcan i\\b", r"eligib", r"allowed", r"what if"],
    }}
    PERSONAL_INTENTS = {{"status", "eligibility"}}
    PLAN = {{"status": ["lookup_record"], "eligibility": ["check_eligibility"]}}   # intent -> first tools
    CATEGORY_WORDS = {{}}                 # e.g. {{"CARDIOLOGY": ["heart", "cardiac"]}}
    TIERS: list[str] = []               # e.g. ["STANDARD", "GOLD"]

    # TODO 6. Rule parameters: every threshold a tool uses. Rows live in rule_registry.csv
    PARAMETERS = ["window_days"]
    PARAM_QUERIES = {{"window_days": [r"how (many|long).*days"]}}   # policy question -> parameter
    PARAM_UNIT = {{"window_days": "{{v}} days"}}

    def record_level(self, intent: str) -> bool:
        return intent == "status"     # status is about the whole record, not one item

    # TODO 7. Tools. Pure code. Data via ctx.q/q1 (always filter by ctx.sid), thresholds via ctx.rule().
    # Return a dict; optional keys: _say (answer sentence), _next (tools to run after), _followup (doc query).
    @tool
    def lookup_record(self, ctx):
        r = ctx.q1("SELECT * FROM records WHERE record_id = ? AND subject_id = ?", (ctx.target["record_id"], ctx.sid))
        if not r:
            return {{"result": "NOT_FOUND_FOR_SUBJECT"}}
        return {{"result": "FOUND", "status": r["status"], "_say": f"Record {{r['record_id']}} is {{r['status']}}."}}

    @tool
    def check_eligibility(self, ctx):
        window = int(float(ctx.rule("window_days")))     # cites the winning document clause
        days = ctx.und.what_if.get("days", (ctx.as_of - date.fromisoformat(ctx.target["created_on"])).days)
        ok = days <= window
        return {{"result": "ELIGIBLE" if ok else "EXPIRED", "days": days, "window_days": window,
                "_say": f"{{'Yes' if ok else 'No'}}: {{days}} days against a {{window}}-day window."}}


DOMAIN = {cls}()
'''

REGISTER_HEADER = ("doc_id,title,issuer,authority_level,doc_type,version,effective_from,effective_to,supersedes,"
                   "scope_categories,scope_tiers,provenance,retrieved_on,synthetic,file\n")
RULES_HEADER = ("rule_id,description,parameter,operator,value,scope_categories,scope_tiers,effective_from,"
                "effective_to,source_doc_id,source_section\n")
EVAL_STARTER = (
    '{"id": "N01", "tags": ["not_found"], "question": "Do you deliver to Antarctica?", "expected_type": "not_found"}\n'
)


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"[a-z][a-z0-9_]*", sys.argv[1]):
        sys.exit("usage: python scripts/new_domain.py <name>   (lowercase, letters/digits/_)")
    name = sys.argv[1]
    mod = ROOT / "app" / "domain" / f"{name}.py"
    pack = ROOT / "data" / name
    if mod.exists():
        sys.exit(f"{mod} already exists")
    cls = "".join(p.capitalize() for p in name.split("_"))
    mod.write_text(TEMPLATE.format(name=name, cls=cls, title=name.replace("_", " ").title()))
    (pack / "docs").mkdir(parents=True, exist_ok=True)
    (pack / "csv").mkdir(exist_ok=True)
    (pack / "docs" / ".gitkeep").touch()
    for f, body in ((pack / "source_register.csv", REGISTER_HEADER),
                    (pack / "csv" / "rule_registry.csv", RULES_HEADER),
                    (pack / "eval_set.jsonl", EVAL_STARTER)):
        if not f.exists():
            f.write_text(body)

    env = ROOT / ".env"
    text = env.read_text() if env.exists() else (ROOT / ".env.example").read_text()
    text = re.sub(r"(?m)^DOMAIN=.*$", f"DOMAIN={name}", text) if "DOMAIN=" in text else f"DOMAIN={name}\n" + text
    env.write_text(text)

    print(f"created {mod.relative_to(ROOT)}  (fill TODO 1-7)")
    print(f"created {pack.relative_to(ROOT)}/  docs/, source_register.csv, csv/rule_registry.csv, eval_set.jsonl")
    print(f"set DOMAIN={name} in .env")
    print("next: drop docs in docs/, fill the register + rules, then")
    print("      python scripts/load_data.py && pytest -q && python eval/run_eval.py --label first")


if __name__ == "__main__":
    main()
