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
# Qdrant Cloud URL, or ":memory:" for tests / offline eval
QDRANT_URL = os.getenv("QDRANT_URL", ":memory:")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
COLLECTION = os.getenv("QDRANT_COLLECTION", "docs")

# LLM + embeddings: any OpenAI-compatible endpoint, Gemini by default
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-flash-latest")
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
MOCK_LLM = _b("MOCK_LLM")
# "api" = LLM_BASE_URL /embeddings, "hash" = offline fallback for tests
EMBED_BACKEND = os.getenv("EMBED_BACKEND", "api")
EMBED_MODEL = os.getenv("EMBED_MODEL", "gemini-embedding-001")

# Retrieval
TOP_K = int(os.getenv("TOP_K", "6"))
CHUNK_CHARS = int(os.getenv("CHUNK_CHARS", "900"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
# below this fused relevance the system abstains (not_found). Tune with eval/run_eval.py
MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.30"))

ADMIN_KEY = os.getenv("ADMIN_KEY", "admin-dev-key")
