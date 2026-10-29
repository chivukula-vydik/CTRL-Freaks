"""Embeddings. API (Gemini) in production; hashing fallback only for offline tests."""
import hashlib
import math
import re
from functools import lru_cache

from app import config

TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    out = []
    for t in TOKEN.findall(text.lower()):
        # crude stemming so "returns/returned/returning" meet
        for suf in ("ing", "ed", "es", "s"):
            if len(t) > 4 and t.endswith(suf):
                t = t[: -len(suf)]
                break
        out.append(t)
    return out


class HashEmbedder:
    dim = 768

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        toks = tokens(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for f in feats:
            h = int(hashlib.md5(f.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 8) & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def docs(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def query(self, text: str) -> list[float]:
        return self._vec(text)


class APIEmbedder:
    """Embeddings from LLM_BASE_URL (Gemini by default). Normalised so dot product = cosine."""

    def _norm(self, v: list[float]) -> list[float]:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def docs(self, texts: list[str]) -> list[list[float]]:
        from app import llm
        out = []
        for i in range(0, len(texts), 100):  # API batch limit
            out += [self._norm(v) for v in llm.embed(texts[i:i + 100])]
        return out

    def query(self, text: str) -> list[float]:
        return self.docs([text])[0]


@lru_cache(maxsize=1)
def get_embedder():
    return APIEmbedder() if config.EMBED_BACKEND == "api" else HashEmbedder()
