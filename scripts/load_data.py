"""Load docs + CSVs into the store, then validate.

  python scripts/load_data.py                      # the active DOMAIN's pack (data/<domain>/)
  python scripts/load_data.py --dir test_customers/  # judge CSVs, <table>.csv per table
  python scripts/load_data.py --pack data/x --reingest
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.domain import DOMAIN, pack_dir  # noqa: E402
from app.loader import load_dir, load_pack  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, help="data pack folder (default: active domain's pack)")
    ap.add_argument("--dir", type=Path, help="only load a folder of <table>.csv files (judge data)")
    ap.add_argument("--reingest", action="store_true", help="re-index docs already in the register")
    a = ap.parse_args()
    db.init_db()
    if a.dir:
        print(json.dumps({"loaded": load_dir(a.dir)}))
    else:
        out = load_pack(a.pack or pack_dir(), reingest=a.reingest)
        for d in out["docs"]:
            print(json.dumps(d))
        print(json.dumps({"loaded": out["tables"]}))
    v = DOMAIN.validate()
    print(f"validation: {len(v)} violation(s)")
    for line in v:
        print("  " + line)


if __name__ == "__main__":
    main()
