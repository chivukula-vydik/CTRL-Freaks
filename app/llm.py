"""LLM client: any OpenAI-compatible endpoint (Gemini by default), MOCK_LLM for offline runs.

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


def reset_usage() -> None:
    _usage.set({"llm_calls": 0, "tokens": 0, "model": "mock" if config.MOCK_LLM else config.LLM_MODEL})


def usage() -> dict:
    try:
        return dict(_usage.get())
    except LookupError:
        return {"llm_calls": 0, "tokens": 0, "model": "none"}


def _add(tokens: int, model: str) -> None:
    try:
        u = _usage.get()
    except LookupError:
        reset_usage()
        u = _usage.get()
    u["llm_calls"] += 1
    u["tokens"] += tokens
    u["model"] = model


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.LLM_API_KEY}"}


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


def chat(system: str, user: str, as_json: bool = False, temperature: float = 0.0) -> str | None:
    if config.MOCK_LLM or not config.LLM_API_KEY:
        return None
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        return _api(msgs, as_json, temperature)
    except Exception:
        return None  # every caller has a deterministic fallback


def embed(texts: list[str]) -> list[list[float]]:
    r = httpx.post(f"{config.LLM_BASE_URL}/embeddings", json={"model": config.EMBED_MODEL, "input": texts},
                   timeout=config.LLM_TIMEOUT, headers=_headers())
    r.raise_for_status()
    return [x["embedding"] for x in r.json()["data"]]  # input order; Gemini omits "index"


def chat_json(system: str, user: str, required: list[str] | None = None, retries: int = 2) -> dict | None:
    """JSON output with validation + retry. Local 7-8B models do drift."""
    hint = ""
    for _ in range(retries + 1):
        raw = chat(system + hint, user, as_json=True)
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
        return {"status": "mock"}
    if not config.LLM_API_KEY:
        return {"status": "no_api_key"}
    t = time.time()
    try:
        r = httpx.get(f"{config.LLM_BASE_URL}/models", timeout=5, headers=_headers())
        r.raise_for_status()
        return {"status": "ok", "model": config.LLM_MODEL, "ms": int((time.time() - t) * 1000)}
    except Exception as e:
        return {"status": "down", "error": type(e).__name__}
