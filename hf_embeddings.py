"""Local Hugging Face embeddings for RAG — runs INSIDE the app container.

Uses fastembed (ONNX runtime, no torch) with BAAI/bge-small-en-v1.5:
  - 384-dim vectors, top-tier retrieval quality for its size (~130MB)
  - CPU-friendly: hundreds of passages/second on the Space's 2 vCPU
  - completely free: no API keys, no rate limits, no external calls

Override the model with HF_EMBED_MODEL (any fastembed-supported model), and
keep HF_EMBED_DIM in sync if you do (bge-small/MiniLM = 384, bge-base = 768).
"""
import os
import threading

HF_EMBED_MODEL = os.getenv("HF_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM = int(os.getenv("HF_EMBED_DIM", "384"))

_model = None
_lock = threading.Lock()
LAST_ERROR = ""


def _get_model():
    """Lazy singleton — the ONNX model loads once (~2s) on first use."""
    global _model, LAST_ERROR
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    from fastembed import TextEmbedding
                    _model = TextEmbedding(model_name=HF_EMBED_MODEL)
                except Exception as e:
                    LAST_ERROR = f"model load: {type(e).__name__}: {str(e)[:200]}"
                    return None
    return _model


def available() -> bool:
    return _get_model() is not None


def embed_passages(texts):
    """Embed a list of document passages → list of 384-float lists.
    Returns [] on failure (callers keep their keyword fallback)."""
    global LAST_ERROR
    m = _get_model()
    if m is None or not texts:
        return []
    try:
        clean = [(t or " ")[:8000] for t in texts]
        return [v.tolist() for v in m.embed(clean, batch_size=32)]
    except Exception as e:
        LAST_ERROR = f"embed_passages: {type(e).__name__}: {str(e)[:200]}"
        return []


def embed_query(query: str):
    """Embed a search query. bge models want an instruction prefix on the QUERY
    side only — fastembed's query_embed applies it when the model defines one."""
    global LAST_ERROR
    m = _get_model()
    if m is None or not (query or "").strip():
        return None
    try:
        q = query[:2000]
        if hasattr(m, "query_embed"):
            vecs = list(m.query_embed([q]))
        else:
            vecs = list(m.embed([q]))
        return vecs[0].tolist() if vecs else None
    except Exception as e:
        LAST_ERROR = f"embed_query: {type(e).__name__}: {str(e)[:200]}"
        return None
