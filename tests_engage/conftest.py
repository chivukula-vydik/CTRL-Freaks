# run with: pytest tests_engage   (sets DOMAIN=engage before the app is imported)
import os
import sys
from pathlib import Path

os.environ["DOMAIN"] = "engage"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import ask, client  # noqa: E402,F401
