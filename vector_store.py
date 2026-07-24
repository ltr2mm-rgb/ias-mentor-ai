"""Qdrant vector store for the RAG knowledge base.

Why Qdrant here: the Space's own disk is EPHEMERAL (wiped on every restart), so
an embedded index (FAISS/Chroma on disk) would vanish; Postgres/pgvector ties
vector capacity to the small free-DB quota. Qdrant Cloud's free tier (1GB, no
card) is a managed, persistent, purpose-built vector DB — 1GB holds several
hundred thousand 384-dim chunks, far beyond this app's needs.

Config (Space settings):
  QDRANT_URL       e.g. https://xxxx.cloud.qdrant.io  (variable)
  QDRANT_API_KEY   the cluster API key                 (secret)
  QDRANT_COLLECTION optional, default aivora_knowledge

Point id == knowledge_chunks.id, so upserts are idempotent and deletes can
target a source's chunk ids exactly. Payload: text, subject, source_id.
"""
import os
import threading

QDRANT_URL = os.getenv("QDRANT_URL", "").strip()
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "").strip()
COLLECTION = os.getenv("QDRANT_COLLECTION", "aivora_knowledge")

_client = None
_lock = threading.Lock()
_collection_ready = False
LAST_ERROR = ""


def enabled() -> bool:
    return bool(QDRANT_URL)


def _get_client():
    global _client, LAST_ERROR
    if not enabled():
        return None
    if _client is None:
        with _lock:
            if _client is None:
                try:
                    from qdrant_client import QdrantClient
                    _client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None, timeout=20)
                except Exception as e:
                    LAST_ERROR = f"client: {type(e).__name__}: {str(e)[:200]}"
                    return None
    return _client


def ensure_collection(dim: int) -> bool:
    """Create the collection (cosine distance) and payload indexes if missing."""
    global _collection_ready, LAST_ERROR
    if _collection_ready:
        return True
    c = _get_client()
    if c is None:
        return False
    try:
        from qdrant_client import models as qm
        if not c.collection_exists(COLLECTION):
            c.create_collection(
                collection_name=COLLECTION,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE))
            try:
                c.create_payload_index(COLLECTION, field_name="subject",
                                       field_schema=qm.PayloadSchemaType.KEYWORD)
                c.create_payload_index(COLLECTION, field_name="source_id",
                                       field_schema=qm.PayloadSchemaType.INTEGER)
            except Exception:
                pass  # indexes are an optimisation
        _collection_ready = True
        return True
    except Exception as e:
        LAST_ERROR = f"ensure_collection: {type(e).__name__}: {str(e)[:200]}"
        return False


def upsert_chunks(items) -> int:
    """items: iterable of (chunk_id:int, vector:list[float], payload:dict).
    Idempotent (id-keyed). Returns how many points were written."""
    global LAST_ERROR
    c = _get_client()
    if c is None:
        return 0
    try:
        from qdrant_client import models as qm
        pts = [qm.PointStruct(id=int(i), vector=v, payload=p) for i, v, p in items if v]
        if not pts:
            return 0
        for i in range(0, len(pts), 128):
            c.upsert(collection_name=COLLECTION, points=pts[i:i + 128], wait=True)
        return len(pts)
    except Exception as e:
        LAST_ERROR = f"upsert: {type(e).__name__}: {str(e)[:200]}"
        return 0


def search(vector, subject=None, k=12):
    """→ list of (text, score), best first. [] on any failure."""
    global LAST_ERROR
    c = _get_client()
    if c is None or not vector:
        return []
    try:
        from qdrant_client import models as qm
        flt = None
        if subject:
            flt = qm.Filter(must=[qm.FieldCondition(key="subject", match=qm.MatchValue(value=subject))])
        res = c.query_points(collection_name=COLLECTION, query=vector,
                             query_filter=flt, limit=int(k), with_payload=True)
        return [((p.payload or {}).get("text") or "", float(p.score or 0.0))
                for p in res.points if (p.payload or {}).get("text")]
    except Exception as e:
        LAST_ERROR = f"search: {type(e).__name__}: {str(e)[:200]}"
        return []


def existing_ids(ids):
    """Which of these chunk ids are already stored? → set of ints."""
    c = _get_client()
    if c is None or not ids:
        return set()
    try:
        got = c.retrieve(collection_name=COLLECTION, ids=[int(i) for i in ids],
                         with_payload=False, with_vectors=False)
        return {int(p.id) for p in got}
    except Exception:
        return set()


def delete_source(source_id: int) -> bool:
    global LAST_ERROR
    c = _get_client()
    if c is None:
        return False
    try:
        from qdrant_client import models as qm
        c.delete(collection_name=COLLECTION, points_selector=qm.FilterSelector(
            filter=qm.Filter(must=[qm.FieldCondition(key="source_id",
                                                     match=qm.MatchValue(value=int(source_id)))])))
        return True
    except Exception as e:
        LAST_ERROR = f"delete_source: {type(e).__name__}: {str(e)[:200]}"
        return False


def count():
    c = _get_client()
    if c is None:
        return None
    try:
        return int(c.count(collection_name=COLLECTION, exact=True).count)
    except Exception:
        return None
