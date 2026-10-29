# run with: pytest examples/retail   (sets DOMAIN=retail before the app is imported)
import os
import sys
from pathlib import Path

os.environ["DOMAIN"] = "retail"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from conftest import ask, client  # noqa: E402,F401
