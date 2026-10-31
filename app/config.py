"""Runtime settings, all overridable by env vars (see .env.example)."""
import os
from pathlib import Path


def _b(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "y"}


ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Read .env so `python ...` and `uvicorn` match docker compose. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))

# Supabase Postgres. On Vercel use the transaction pooler URI (port 6543)
DATABASE_URL = os.getenv("DATABASE_URL", "")
# LLM provider: "anthropic" (Claude API, default) or "openai" (any OpenAI-compatible endpoint, e.g. Gemini)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5" if LLM_PROVIDER == "anthropic" else "gemini-flash-latest")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
MOCK_LLM = _b("MOCK_LLM")

ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()   # empty = every staff endpoint refuses (require_admin)
