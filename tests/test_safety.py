"""Degraded-mode and scope checks that hold for ANY domain: embeddings down, LLM 429, out-of-scope, write guard."""
import httpx
import pytest
from conftest import ask
from test_contract import corpus  # noqa: F401  (ingests the QM-HB handbook)

from app import config, llm
from app.domain import COMMON_OUT_OF_SCOPE, DOMAIN, Ctx, Understanding
from app.retrieval import embed


def _audit(client, tid):
    return client.get(f"/audit/{tid}", headers={"X-Admin-Key": config.ADMIN_KEY}).json()


def test_embedding_down_falls_back_to_bm25(client, corpus, monkeypatch):  # noqa: F811
    def down(*_):
        raise httpx.ConnectError("embeddings down")
    monkeypatch.setattr(embed.get_embedder(), "query", down)
    r = ask(client, "What is the quillmark card replacement fee?")
    assert r["answer_type"] == "retrieved_fact" and "quillmark card" in r["answer"]   # 250, or 400 once superseded
    assert any("Keyword search only" in a for a in r["assumptions"])
    assert _audit(client, r["trace_id"])["safety_flags"]["embedding_fallback"] == "bm25"
    assert ask(client, "Do you deliver to Antarctica?")["answer_type"] == "not_found"


def test_llm_429_is_counted(client, corpus, monkeypatch):  # noqa: F811
    def limited(url, **_):
        req = httpx.Request("POST", url)
        raise httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req))
    monkeypatch.setattr(config, "MOCK_LLM", False)
    monkeypatch.setattr(config, "LLM_API_KEY", "x")
    monkeypatch.setattr(llm.httpx, "post", limited)
    before = llm._totals["rate_limited"]
    r = ask(client, "What is the quillmark card replacement fee?")
    assert r["answer_type"] == "retrieved_fact"   # deterministic fallback still answers
    rec = _audit(client, r["trace_id"])
    assert rec["llm_errors"] >= 1 and rec["llm_rate_limited"] >= 1
    assert llm._totals["rate_limited"] > before and llm._totals["last_error"] == "llm_errors: 429"


def test_out_of_scope_refused(client, monkeypatch):
    monkeypatch.setattr(DOMAIN, "OUT_OF_SCOPE", COMMON_OUT_OF_SCOPE)
    for q in ["Should I buy Infosys shares now?", "Can you diagnose my chest pain?"]:
        r = ask(client, q)
        assert r["answer_type"] == "refused" and r["answer"] == DOMAIN.OUT_OF_SCOPE_MSG
    assert ask(client, "What is the quillmark card replacement fee?")["answer_type"] != "refused"


def test_execute_only_inside_action_and_scoped():
    ctx = Ctx(DOMAIN, "C1", {}, Understanding(), None, {})
    with pytest.raises(PermissionError):
        ctx.execute("UPDATE t SET a = 1 WHERE owner = :sid")          # not inside an @action
    ctx.writable = True
    for sql in ["UPDATE t SET a = 1", "UPDATE t SET owner = :sid WHERE id = 1", "SELECT 1 WHERE x = :sid",
                "DELETE FROM t WHERE id = :id"]:
        with pytest.raises(PermissionError):
            ctx.execute(sql, {"id": 1})
