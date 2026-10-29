"""Minimal Streamlit UI: ask, ingest, sources, audit. Scored only for usability, keep it plain."""
import json
import os
from datetime import date

import httpx
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
st.set_page_config(page_title="RAG Agent", layout="wide")

with st.sidebar:
    st.subheader("Session")
    sid = st.text_input("Logged-in user id (header)", "")
    as_of = st.date_input("as_of_date", date.today())
    try:
        st.json(httpx.get(f"{API}/health", timeout=5).json(), expanded=False)
    except Exception as e:
        st.error(f"API down: {e}")

tab_ask, tab_ingest, tab_src, tab_audit = st.tabs(["Ask", "Ingest", "Sources", "Audit"])

with tab_ask:
    q = st.text_area("Question", height=80)
    if st.button("Ask", type="primary") and q.strip():
        h = {"X-Customer-Id": sid} if sid.strip() else {}
        r = httpx.post(f"{API}/ask", json={"question": q, "as_of_date": as_of.isoformat()}, headers=h, timeout=300).json()
        st.markdown(f"**{r['answer_type']}** · trace `{r['trace_id']}`")
        st.write(r["answer"])
        for c in r.get("citations", []):
            st.caption(f"📄 {c['doc_id']} · {c.get('title')} · §{c.get('section')} · p{c.get('page')} · "
                       f"v{c.get('version')} · eff {c.get('effective_from')}")
        for k in ("upcoming_changes", "assumptions"):
            if r.get(k):
                st.info(f"{k}: " + " | ".join(r[k]))
        with st.expander("Tools, rules, conflicts"):
            st.json({k: r.get(k) for k in ("tools_invoked", "applied_rules", "conflicts_detected", "explanation")})

with tab_ingest:
    f = st.file_uploader("Document", type=["pdf", "docx", "md", "txt", "png", "jpg"])
    meta = st.text_area("Metadata JSON (Source Register fields + optional rules)", height=220, value=json.dumps({
        "doc_id": "NEW-DOC-01", "title": "", "issuer": "", "authority_level": 2, "doc_type": "circular",
        "version": "1.0", "effective_from": date.today().isoformat(), "supersedes": "",
        "scope_categories": "ALL", "scope_tiers": "ALL", "provenance": "", "synthetic": "N", "rules": []}, indent=2))
    if st.button("Ingest") and f:
        r = httpx.post(f"{API}/ingest", files={"file": (f.name, f.getvalue())}, data={"metadata": meta}, timeout=600)
        st.json(r.json())

with tab_src:
    st.dataframe(httpx.get(f"{API}/sources").json(), use_container_width=True)
    st.dataframe(httpx.get(f"{API}/rules").json(), use_container_width=True)

with tab_audit:
    tid = st.text_input("trace_id")
    key = st.text_input("admin key (optional)", type="password")
    if st.button("Load") and tid:
        h = {"X-Customer-Id": sid} if sid else {}
        if key:
            h["X-Admin-Key"] = key
        st.json(httpx.get(f"{API}/audit/{tid}", headers=h).json())
