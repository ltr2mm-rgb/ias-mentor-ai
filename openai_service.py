"""OpenAI (ChatGPT) provider — the second engine in AIVORA's hybrid AI layer.

It is OPTIONAL: everything is gated on the OPENAI_API_KEY environment variable.
If the key is absent (or the `openai` package isn't installed), oai_available()
returns False and the app runs exactly as before on Gemini alone — no regression.

Roles in the hybrid setup (see gemini_service for the routing):
  • Embeddings  -> OpenAI PRIMARY  (text-embedding-3-small @ 768 dims) — removes
                   the Gemini free-tier embedding cap that was blocking RAG.
  • Mentor chat -> OpenAI PRIMARY  (gpt-4o-mini) with Gemini as automatic backup.
  • Mains eval  -> OpenAI PRIMARY  with Gemini backup.
  • MCQ / OCR   -> Gemini PRIMARY  with OpenAI as backup.
"""
import os
import math

try:
    from openai import OpenAI
except Exception:                      # package not installed
    OpenAI = None

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
OPENAI_EMBED_DIM = 768                 # matches the vector(768) column + HNSW index

_client = None
LAST_OAI_ERROR = ""


def _get_client():
    global _client
    if _client is None and OpenAI is not None and OPENAI_API_KEY:
        try:
            _client = OpenAI(api_key=OPENAI_API_KEY)
        except Exception:
            _client = None
    return _client


def oai_available() -> bool:
    """True only when an OpenAI key + SDK are present."""
    return _get_client() is not None


def oai_generate(prompt: str, json_mode: bool = False, system: str = None,
                 model: str = None) -> str:
    """Single-prompt completion → text. Raises on failure (callers handle fallback)."""
    c = _get_client()
    if c is None:
        raise RuntimeError("OpenAI not configured")
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    kw = {"model": model or OPENAI_CHAT_MODEL, "messages": msgs}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    resp = c.chat.completions.create(**kw)
    return (resp.choices[0].message.content or "").strip()


def oai_generate_messages(system: str, messages: list, json_mode: bool = False,
                          model: str = None) -> str:
    """Multi-turn completion. `messages` = [{role: user|assistant, content}]."""
    c = _get_client()
    if c is None:
        raise RuntimeError("OpenAI not configured")
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    for m in (messages or []):
        role = "assistant" if m.get("role") == "assistant" else "user"
        msgs.append({"role": role, "content": m.get("content", "")})
    kw = {"model": model or OPENAI_CHAT_MODEL, "messages": msgs}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    resp = c.chat.completions.create(**kw)
    return (resp.choices[0].message.content or "").strip()


def oai_vision_ocr(img_bytes: bytes, mime_type: str = "image/png", model: str = None) -> str:
    """OCR an image via OpenAI vision (gpt-4o-mini supports images). Used as the
    fallback when Gemini vision OCR fails. Returns '' if OpenAI isn't configured."""
    c = _get_client()
    if c is None or not img_bytes:
        return ""
    import base64
    b64 = base64.b64encode(img_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"
    resp = c.chat.completions.create(
        model=model or OPENAI_CHAT_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Extract ALL readable text from this image exactly as written. "
             "Preserve line breaks and keep any MCQ numbering and options (A/B/C/D) intact. "
             "Return ONLY the extracted text."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    )
    return (resp.choices[0].message.content or "").strip()


def _normalize(vals):
    v = [float(x) for x in vals]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def oai_embed(texts, dims: int = OPENAI_EMBED_DIM, model: str = None):
    """Embed a list of strings → list of unit-length `dims`-float vectors.
    Raises on failure. Batches internally (OpenAI accepts large batches; we cap
    at 256 to keep request sizes reasonable)."""
    global LAST_OAI_ERROR
    c = _get_client()
    if c is None:
        raise RuntimeError("OpenAI not configured")
    out = []
    B = 256
    for i in range(0, len(texts), B):
        batch = [((t or "")[:8000] or " ") for t in texts[i:i + B]]
        try:
            resp = c.embeddings.create(model=model or OPENAI_EMBED_MODEL,
                                       input=batch, dimensions=dims)
            for d in resp.data:
                out.append(_normalize(d.embedding))
        except Exception as e:
            LAST_OAI_ERROR = f"{type(e).__name__}: {str(e)[:200]}"
            raise
    return out
