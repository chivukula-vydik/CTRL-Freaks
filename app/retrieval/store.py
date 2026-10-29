"""Qdrant vectors + in-memory BM25, fused with reciprocal rank fusion.

BM25 catches exact terms (clause numbers, SKUs); vectors catch paraphrases
("send back" vs "return"). The BM25 index is rebuilt when the Source Register
changes, so POST /ingest on any instance is live everywhere with no restart.
"""
import threading
import uuid

from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from app import config, db
from app.retrieval.embed import get_embedder, tokens

_lock = threading.Lock()
_client: QdrantClient | None = None
_bm25 = {"index": None, "ids": [], "docs": [], "metas": [], "vocab": set(), "stamp": None}


def client() -> QdrantClient:
    global _client
    if _client is None:
        # QDRANT_URL=":memory:" gives an in-process store for tests / offline eval
        _client = QdrantClient(location=config.QDRANT_URL, api_key=config.QDRANT_API_KEY or None)
    return _client


def _exists() -> bool:
    return client().collection_exists(config.COLLECTION)


def _doc_filter(doc_id: str) -> models.Filter:
    return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])


def _pid(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))  # Qdrant ids must be uint or uuid


def _split(payload: dict) -> tuple[str, str, dict]:
    p = dict(payload)
    return p.pop("_id"), p.pop("text"), p


def count() -> int:
    return client().count(config.COLLECTION, exact=True).count if _exists() else 0


def add(ids: list[str], texts: list[str], metas: list[dict]) -> None:
    embs = get_embedder().docs(texts)
    if not _exists():
        client().create_collection(config.COLLECTION, vectors_config=models.VectorParams(
            size=len(embs[0]), distance=models.Distance.COSINE))
        client().create_payload_index(config.COLLECTION, "doc_id", models.PayloadSchemaType.KEYWORD)
    client().upsert(config.COLLECTION, points=[
        models.PointStruct(id=_pid(i), vector=e, payload={"_id": i, "text": t, **m})
        for i, t, m, e in zip(ids, texts, metas, embs)])
    _bm25["stamp"] = None


def delete_doc(doc_id: str) -> None:
    if _exists():
        client().delete(config.COLLECTION, points_selector=models.FilterSelector(filter=_doc_filter(doc_id)))
    _bm25["stamp"] = None


def _scroll(flt: models.Filter | None = None) -> list[dict]:
    out, offset = [], None
    while True:
        pts, offset = client().scroll(config.COLLECTION, scroll_filter=flt, limit=512, offset=offset,
                                      with_payload=True, with_vectors=False)
        out += [p.payload for p in pts]
        if offset is None:
            return out


def _ensure_bm25():
    # ponytail: one extra DB + Qdrant round trip per search to spot ingests on other instances;
    # move the stamp to a cache (Redis) if that latency shows up in the eval
    stamp = (db.q1("SELECT max(ingested_at) AS t FROM source_register")["t"], count())
    with _lock:
        if _bm25["stamp"] == stamp:
            return
        rows = [_split(p) for p in _scroll()] if stamp[1] else []
        _bm25["ids"] = [r[0] for r in rows]
        _bm25["docs"] = [r[1] for r in rows]
        _bm25["metas"] = [r[2] for r in rows]
        corpus = [tokens(d) for d in _bm25["docs"]]
        _bm25["index"] = BM25Okapi(corpus) if corpus else None
        _bm25["vocab"] = {t for doc in corpus for t in doc}
        _bm25["stamp"] = stamp


def vocab() -> set[str]:
    _ensure_bm25()
    return _bm25["vocab"]


def page_for(doc_id: str, section: str | None) -> int | None:
    """Page where a cited section starts, so rule citations carry a page too."""
    from app.precedence import norm_section
    try:
        metas = [_split(p)[2] for p in _scroll(_doc_filter(doc_id))]
    except Exception:
        return None
    want = norm_section(section)
    pages = [m.get("page") for m in metas if norm_section(m.get("section")) == want]
    return min(pages) if pages else None


def search(query: str, k: int = config.TOP_K) -> list[dict]:
    """Returns hits sorted by fused score. Each hit: id, text, meta, score, cosine."""
    total = count()
    if total == 0:
        return []
    n = min(k * 4, total)
    qv = get_embedder().query(query)
    vr = client().query_points(config.COLLECTION, query=qv, limit=n, with_payload=True).points
    hits: dict[str, dict] = {}
    for rank, p in enumerate(vr):
        i, d, m = _split(p.payload)
        hits[i] = {"id": i, "text": d, "meta": m, "cosine": p.score, "score": 1 / (60 + rank)}

    _ensure_bm25()
    if _bm25["index"] is not None:
        scores = _bm25["index"].get_scores(tokens(query))
        order = sorted(range(len(scores)), key=lambda j: -scores[j])[:n]
        for rank, j in enumerate(order):
            if scores[j] <= 0:
                break
            hid = _bm25["ids"][j]
            h = hits.setdefault(hid, {"id": hid, "text": _bm25["docs"][j], "meta": _bm25["metas"][j],
                                      "cosine": None, "score": 0.0})
            h["score"] += 1 / (60 + rank)
            h["bm25"] = float(scores[j])

    out = sorted(hits.values(), key=lambda h: -h["score"])[:k]
    # fill cosine for BM25-only hits so abstention has one comparable number
    missing = [h for h in out if h["cosine"] is None]
    if missing:
        embs = get_embedder().docs([h["text"] for h in missing])
        for h, e in zip(missing, embs):
            h["cosine"] = sum(a * b for a, b in zip(qv, e))
    return out
