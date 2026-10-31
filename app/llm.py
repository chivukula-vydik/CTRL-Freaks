"""LLM client: Claude API (default) or any OpenAI-compatible endpoint (LLM_PROVIDER=openai), MOCK_LLM for offline runs.

Every caller must have a deterministic fallback for when this returns None.
The LLM never produces authoritative numbers; it classifies and phrases.
"""
import json
import time
from contextvars import ContextVar

import httpx

from app import config

# per-request usage counters (read by audit)
_usage: ContextVar[dict] = ContextVar("llm_usage")
_ERRS = {"llm_errors": 0, "rate_limited": 0, "embed_errors": 0}
# ponytail: per-process totals for /health; on Vercel each instance counts its own. Move to the DB if that matters
_totals = {**_ERRS, "last_error": None}


def reset_usage() -> None:
    _usage.set({"llm_calls": 0, "tokens": 0, "model": "mock" if config.MOCK_LLM else config.LLM_MODEL, **_ERRS})


def usage() -> dict:
    try:
        return dict(_usage.get())
    except LookupError:
        return {"llm_calls": 0, "tokens": 0, "model": "none", **_ERRS}


def _cur() -> dict:
    try:
        return _usage.get()
    except LookupError:
        reset_usage()
        return _usage.get()


def _add(tokens: int, model: str) -> None:
    u = _cur()
    u["llm_calls"] += 1
    u["tokens"] += tokens
    u["model"] = model


def _fail(kind: str, e: Exception) -> None:
    """Count a failed call so a deterministic fallback never looks like a working model."""
    limited = isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429
    for d in (_cur(), _totals):
        d[kind] += 1
        d["rate_limited"] += limited
    _totals["last_error"] = f"{kind}: {'429' if limited else type(e).__name__}"


def _anthropic() -> bool:
    return config.LLM_PROVIDER == "anthropic"


def _key() -> str:
    return config.ANTHROPIC_API_KEY if _anthropic() else config.LLM_API_KEY


def _headers() -> dict:
    if _anthropic():
        return {"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {config.LLM_API_KEY}"}


def _api_anthropic(system: str, user: str, temperature: float, max_tokens: int) -> str:
    body = {"model": config.LLM_MODEL, "max_tokens": max_tokens, "temperature": temperature, "system": system,
            "messages": [{"role": "user", "content": user}]}
    r = httpx.post(f"{config.ANTHROPIC_BASE_URL}/v1/messages", json=body, timeout=config.LLM_TIMEOUT,
                   headers={**_headers(), "content-type": "application/json"})
    r.raise_for_status()
    d = r.json()
    u = d.get("usage", {})
    _add(u.get("input_tokens", 0) + u.get("output_tokens", 0), config.LLM_MODEL)
    return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")


def _api(messages: list[dict], as_json: bool, temperature: float) -> str:
    body = {"model": config.LLM_MODEL, "messages": messages, "temperature": temperature}
    if as_json:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{config.LLM_BASE_URL}/chat/completions", json=body, timeout=config.LLM_TIMEOUT,
                   headers=_headers())
    r.raise_for_status()
    d = r.json()
    _add(d.get("usage", {}).get("total_tokens", 0), config.LLM_MODEL)
    return d["choices"][0]["message"]["content"]


def chat(system: str, user: str, as_json: bool = False, temperature: float = 0.0, max_tokens: int = 700) -> str | None:
    if config.MOCK_LLM or not _key():
        return None
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        if _anthropic():
            return _api_anthropic(system, user, temperature, max_tokens)
        return _api(msgs, as_json, temperature)
    except Exception as e:
        _fail("llm_errors", e)
        return None  # every caller has a deterministic fallback


def embed(texts: list[str]) -> list[list[float]]:
    try:
        r = httpx.post(f"{config.LLM_BASE_URL}/embeddings", json={"model": config.EMBED_MODEL, "input": texts},
                       timeout=config.LLM_TIMEOUT, headers=_headers())
        r.raise_for_status()
    except Exception as e:
        _fail("embed_errors", e)
        raise
    return [x["embedding"] for x in r.json()["data"]]  # input order; Gemini omits "index"


def chat_json(system: str, user: str, required: list[str] | None = None, retries: int = 2,
              temperature: float = 0.0, max_tokens: int = 700) -> dict | None:
    """JSON output with validation + retry. Local 7-8B models do drift."""
    hint = ""
    for _ in range(retries + 1):
        raw = chat(system + hint, user, as_json=True, temperature=temperature, max_tokens=max_tokens)
        if raw is None:
            return None
        try:
            obj = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            if not required or all(k in obj for k in required):
                return obj
            hint = f"\nReturn ONLY a JSON object with keys: {required}."
        except Exception:
            hint = "\nYour last output was not valid JSON. Return ONLY one JSON object."
    return None


def health() -> dict:
    if config.MOCK_LLM:
        return {"status": "mock", **_totals}
    if not _key():
        return {"status": "no_api_key", **_totals}
    t = time.time()
    try:
        base = f"{config.ANTHROPIC_BASE_URL}/v1" if _anthropic() else config.LLM_BASE_URL
        r = httpx.get(f"{base}/models", timeout=5, headers=_headers())
        r.raise_for_status()
        return {"status": "ok", "model": config.LLM_MODEL, "ms": int((time.time() - t) * 1000), **_totals}
    except Exception as e:
        return {"status": "down", "error": type(e).__name__, **_totals}
