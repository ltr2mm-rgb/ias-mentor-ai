"""DeepSeek provider — the second engine in AIMENTORA's hybrid AI layer.

DeepSeek speaks the OpenAI wire format, so we use the `openai` client library to
talk to it (base URL = https://api.deepseek.com). It is OPTIONAL: everything is
gated on the DEEPSEEK_API_KEY environment variable. If the key is absent (or the
`openai` client package isn't installed), ds_available() returns False and the
app runs on Gemini alone — no regression.

Backward compatible: the env vars were historically named OPENAI_* (because the
client library is `openai`). This module reads the new DEEPSEEK_* names first and
falls back to the old OPENAI_* names, so existing deployments keep working.

Roles in the hybrid setup (see gemini_service for the routing):
  • Fallback     -> DeepSeek is the automatic backup when Gemini errors/rate-limits.
  • Bulk / verify-> DeepSeek does cheap bulk extraction + independent MCQ verification.
  • Vision OCR   -> Gemini PRIMARY, DeepSeek/OpenAI-compatible vision as backup.
Because DeepSeek talks the OpenAI format, you can also point DEEPSEEK_BASE_URL at
any other OpenAI-compatible provider (Groq, real OpenAI, etc.) if you ever switch.
"""
import os
import math

try:
    from openai import OpenAI          # the `openai` client lib is the OpenAI-format client
except Exception:                      # package not installed
    OpenAI = None


def _env(*names, default=""):
    """Read the first env var that is set, trying new names then legacy ones."""
    for n in names:
        v = os.getenv(n)
        if v not in (None, ""):
            return v
    return default


# New DEEPSEEK_* names, falling back to the legacy OPENAI_* names so existing
# secrets on the Space / Cloud Run keep working without any change.
DEEPSEEK_API_KEY = _env("DEEPSEEK_API_KEY", "OPENAI_API_KEY", default="")
# Base URL defaults to DeepSeek; override to use any other OpenAI-compatible API.
DEEPSEEK_BASE_URL = _env("DEEPSEEK_BASE_URL", "OPENAI_BASE_URL",
                         default="https://api.deepseek.com").strip()
DEEPSEEK_CHAT_MODEL = _env("DEEPSEEK_CHAT_MODEL", "OPENAI_CHAT_MODEL", default="deepseek-chat")
DEEPSEEK_EMBED_MODEL = _env("DEEPSEEK_EMBED_MODEL", "OPENAI_EMBED_MODEL",
                            default="text-embedding-3-small")
DEEPSEEK_EMBED_DIM = 768                # matches the vector(768) column + HNSW index

_client = None
LAST_DS_ERROR = ""


def _get_client():
    global _client
    if _client is None and OpenAI is not None and DEEPSEEK_API_KEY:
        try:
            kw = {"api_key": DEEPSEEK_API_KEY}
            if DEEPSEEK_BASE_URL:
                kw["base_url"] = DEEPSEEK_BASE_URL
            _client = OpenAI(**kw)
        except Exception:
            _client = None
    return _client


def ds_available() -> bool:
    """True only when a DeepSeek (OpenAI-format) key + client lib are present."""
    return _get_client() is not None


def ds_embed_ok() -> bool:
    """True when this client can be trusted for EMBEDDINGS. DeepSeek itself has no
    embeddings endpoint, so embeddings stay on Gemini unless the base URL is real
    OpenAI or the operator explicitly sets DEEPSEEK_EMBED_MODEL for a compatible
    provider that does support embeddings."""
    if _get_client() is None:
        return False
    if "api.openai.com" in DEEPSEEK_BASE_URL:
        return True
    return bool(_env("DEEPSEEK_EMBED_MODEL", "OPENAI_EMBED_MODEL"))


def ds_generate(prompt: str, json_mode: bool = False, system: str = None,
                model: str = None) -> str:
    """Single-prompt completion → text. Raises on failure (callers handle fallback)."""
    c = _get_client()
    if c is None:
        raise RuntimeError("DeepSeek not configured")
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    kw = {"model": model or DEEPSEEK_CHAT_MODEL, "messages": msgs}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    resp = c.chat.completions.create(**kw)
    return (resp.choices[0].message.content or "").strip()


def ds_generate_messages(system: str, messages: list, json_mode: bool = False,
                         model: str = None) -> str:
    """Multi-turn completion. `messages` = [{role: user|assistant, content}]."""
    c = _get_client()
    if c is None:
        raise RuntimeError("DeepSeek not configured")
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    for m in (messages or []):
        role = "assistant" if m.get("role") == "assistant" else "user"
        msgs.append({"role": role, "content": m.get("content", "")})
    kw = {"model": model or DEEPSEEK_CHAT_MODEL, "messages": msgs}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    resp = c.chat.completions.create(**kw)
    return (resp.choices[0].message.content or "").strip()


def ds_vision_ocr(img_bytes: bytes, mime_type: str = "image/png", model: str = None) -> str:
    """OCR an image via an OpenAI-format vision model. Used as the fallback when
    Gemini vision OCR fails. Returns '' if the provider isn't configured or the
    model has no vision support."""
    c = _get_client()
    if c is None or not img_bytes:
        return ""
    import base64
    b64 = base64.b64encode(img_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"
    resp = c.chat.completions.create(
        model=model or DEEPSEEK_CHAT_MODEL,
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


def ds_embed(texts, dims: int = DEEPSEEK_EMBED_DIM, model: str = None):
    """Embed a list of strings → list of unit-length `dims`-float vectors.
    Raises on failure. Only usable when the configured provider actually exposes
    an embeddings endpoint (DeepSeek does not; see ds_embed_ok)."""
    global LAST_DS_ERROR
    c = _get_client()
    if c is None:
        raise RuntimeError("DeepSeek not configured")
    out = []
    B = 256
    for i in range(0, len(texts), B):
        batch = [((t or "")[:8000] or " ") for t in texts[i:i + B]]
        try:
            resp = c.embeddings.create(model=model or DEEPSEEK_EMBED_MODEL,
                                       input=batch, dimensions=dims)
            for d in resp.data:
                out.append(_normalize(d.embedding))
        except Exception as e:
            LAST_DS_ERROR = f"{type(e).__name__}: {str(e)[:200]}"
            raise
    return out
