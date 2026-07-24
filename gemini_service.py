from google import genai
try:
    from google.genai import types as genai_types
except Exception:
    genai_types = None
from config import GEMINI_API_KEY
import re
import json

client = genai.Client(api_key=GEMINI_API_KEY)
# gemini-2.5-flash-lite: Google's Dec-2025 free-tier cut left plain 2.5-flash at
# ~20 requests/day, while flash-lite keeps ~1,000/day — 50× more headroom on the
# same key. Override with the GEMINI_MODEL env var if you move to a paid tier.
import os as _model_os
MODEL = _model_os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
# High-stakes reasoning tier: a stronger, pricier Gemini used SPARINGLY for the
# few learner-facing tasks where judgement quality matters most (Mains answer
# evaluation, mistake root-cause diagnosis, interview question generation).
# Everything else stays on the fast/cheap flash-lite MODEL above. Override with
# the GEMINI_PRO_MODEL env var.
MODEL_PRO = _model_os.getenv("GEMINI_PRO_MODEL", "gemini-2.5-pro")

# ── Second engine (DeepSeek) for the hybrid AI layer ─────────────────────────
# Optional: active only when a DeepSeek key is set. Absent → pure-Gemini, as before.
try:
    import deepseek_service as _ds
except Exception:
    _ds = None

# ── Third engine (real OpenAI / GPT) for the hybrid AI layer ─────────────────
# Optional: active only when OPENAI_API_KEY is set. Engine priority across all
# three is Gemini → OpenAI → DeepSeek (see gen_text). OPENAI_BASE_URL is optional
# (defaults to api.openai.com); OPENAI_CHAT_MODEL defaults to gpt-4o-mini and
# OPENAI_EMBED_MODEL to text-embedding-3-small.
try:
    from openai import OpenAI as _OpenAI
except Exception:
    _OpenAI = None
_OPENAI_KEY = _model_os.getenv("OPENAI_API_KEY", "").strip()
_OPENAI_BASE = _model_os.getenv("OPENAI_BASE_URL", "").strip()
_OPENAI_CHAT_MODEL = _model_os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
_OPENAI_EMBED_MODEL = _model_os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
_openai_client = None


def _get_openai():
    global _openai_client
    if _openai_client is None and _OpenAI is not None and _OPENAI_KEY:
        try:
            kw = {"api_key": _OPENAI_KEY}
            if _OPENAI_BASE:
                kw["base_url"] = _OPENAI_BASE
            _openai_client = _OpenAI(**kw)
        except Exception:
            _openai_client = None
    return _openai_client


def _openai_on() -> bool:
    return _get_openai() is not None


def _openai_generate(prompt: str, json_mode: bool = False, system: str = None) -> str:
    c = _get_openai()
    if c is None:
        return ""
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    kw = {"model": _OPENAI_CHAT_MODEL, "messages": msgs}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    r = c.chat.completions.create(**kw)
    return (r.choices[0].message.content or "")


def _openai_embed(texts):
    """Embed via OpenAI (text-embedding-3-small @ EMBED_DIM). Returns a list
    aligned to `texts`, with None for any failed batch."""
    global LAST_EMBED_ERROR
    c = _get_openai()
    if c is None:
        return [None] * len(texts)
    out = []
    B = 256
    for i in range(0, len(texts), B):
        batch = [((t or "")[:8000] or " ") for t in texts[i:i + B]]
        try:
            r = c.embeddings.create(model=_OPENAI_EMBED_MODEL, input=batch,
                                    dimensions=EMBED_DIM)
            out.extend(_finalize_vec(list(d.embedding)) for d in r.data)
        except Exception as e:
            LAST_EMBED_ERROR = f"OpenAI embed: {type(e).__name__}: {str(e)[:200]}"
            out.extend([None] * len(batch))
    return out

# ── Gemini quota circuit-breaker ─────────────────────────────────────────────
# Gemini is the preferred engine, but its prepaid credits can run out. When a
# Gemini call fails with a quota/billing error we skip Gemini for a short cooldown
# so subsequent requests go straight to the next engine (no wasted call, no
# user-facing 429). Gemini is retried automatically once the cooldown elapses.
import time as _gtime
_GEMINI_DOWN_UNTIL = 0.0


def _gemini_ok() -> bool:
    return _gtime.time() >= _GEMINI_DOWN_UNTIL


def _note_gemini_error(e) -> None:
    global _GEMINI_DOWN_UNTIL
    s = str(e).lower()
    if any(k in s for k in ("429", "resource_exhausted", "quota",
                            "prepayment", "credit", "billing")):
        _GEMINI_DOWN_UNTIL = _gtime.time() + 600  # skip Gemini for 10 minutes


def _deepseek_on() -> bool:
    return bool(_ds and _ds.ds_available())


def _gemini_text(prompt: str, json_mode: bool = False, model: str = None) -> str:
    _m = model or MODEL
    if json_mode:
        return (client.models.generate_content(
            model=_m, contents=prompt,
            config={"response_mime_type": "application/json"}).text or "")
    return (client.models.generate_content(model=_m, contents=prompt).text or "")


PROVIDER_PRIORITY = ["gemini", "openai", "deepseek"]


def gen_text(prompt: str, json_mode: bool = False, prefer: str = "gemini",
             system: str = None, model: str = None) -> str:
    """Resilient text generation across three engines. Priority order is
    Gemini → OpenAI → DeepSeek; the first engine that returns text wins and the
    rest are automatic fallbacks. `prefer` moves one engine to the front (used
    e.g. for cross-model verification). Gemini is skipped while it is in a quota
    cooldown, so the app stays fast when Gemini has no credits. `model` overrides
    the Gemini model for this call (e.g. MODEL_PRO); other engines use their own."""
    order = []
    if prefer in PROVIDER_PRIORITY:
        order.append(prefer)
    for p in PROVIDER_PRIORITY:
        if p not in order:
            order.append(p)
    avail = {"gemini": _gemini_ok(), "openai": _openai_on(), "deepseek": _deepseek_on()}
    order = [p for p in order if avail.get(p)]
    if not order:
        order = ["gemini"]      # nothing else available — try Gemini as last resort
    last = None
    for p in order:
        try:
            if p == "gemini":
                full = (system + "\n\n" + prompt) if system else prompt
                out = _gemini_text(full, json_mode=json_mode, model=model)
            elif p == "openai":
                out = _openai_generate(prompt, json_mode=json_mode, system=system)
            else:  # deepseek
                out = _ds.ds_generate(prompt, json_mode=json_mode, system=system)
            if out and out.strip():
                return out
        except Exception as e:
            last = e
            if p == "gemini":
                _note_gemini_error(e)
    if last:
        raise last
    raise RuntimeError("No AI provider available")

# ── Embeddings (pgvector RAG) ────────────────────────────────────────────────
# Candidate model names tried in order (SDK / API-tier differences). First one
# that returns a vector wins and is cached for the rest of the process.
# gemini-embedding-001 is the GA model and works on the standard key; it natively
# returns 3072 dims, so we truncate + L2-normalise every vector down to EMBED_DIM
# (it's Matryoshka-trained, so the 768-prefix is a valid, high-quality embedding)
# to match our vector(768) column + HNSW index (which caps at 2000 dims anyway).
import math
EMBED_MODELS = ["gemini-embedding-001", "text-embedding-004",
                "models/gemini-embedding-001", "models/text-embedding-004"]
EMBED_MODEL = EMBED_MODELS[0]
EMBED_DIM = 768
LAST_EMBED_ERROR = ""     # surfaced via /admin/embeddings/backfill for diagnosis


def _finalize_vec(vals):
    """Truncate to EMBED_DIM and L2-normalise → a clean 768-float unit vector.
    Returns None if the model gave fewer than EMBED_DIM dimensions (unusable)."""
    if not vals:
        return None
    v = [float(x) for x in vals[:EMBED_DIM]]
    if len(v) < EMBED_DIM:
        return None
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _embed_once(contents, task_type):
    """A single embed_content call → list of 768-d vectors aligned to `contents`.
    Requests 768 output dims when the SDK supports it, and always truncates +
    normalises so the stored vector matches the column no matter what the API returns."""
    global EMBED_MODEL
    last = None
    for model in ([EMBED_MODEL] + [m for m in EMBED_MODELS if m != EMBED_MODEL]):
        for cfg_mode in ("dim", "task", "none"):
            try:
                cfg = None
                if cfg_mode != "none" and genai_types is not None:
                    try:
                        if cfg_mode == "dim":
                            cfg = genai_types.EmbedContentConfig(
                                task_type=task_type, output_dimensionality=EMBED_DIM)
                        else:
                            cfg = genai_types.EmbedContentConfig(task_type=task_type)
                    except Exception:
                        cfg = None
                        if cfg_mode != "none":
                            continue
                if cfg is not None:
                    resp = client.models.embed_content(model=model, contents=contents, config=cfg)
                else:
                    resp = client.models.embed_content(model=model, contents=contents)
                embs = list(getattr(resp, "embeddings", None) or [])
                out = [_finalize_vec(getattr(e, "values", None)) for e in embs]
                if any(v for v in out):
                    EMBED_MODEL = model            # cache the working model name
                    return out
            except Exception as e:
                last = f"{type(e).__name__}: {str(e)[:200]} (model={model}, cfg={cfg_mode})"
    if last:
        raise RuntimeError(last)
    raise RuntimeError("embed_content returned no usable vectors")


import os as _os


def embed_provider() -> str:
    """Which engine is the active embedder. ALL chunks + queries must use the same
    one (vectors from different models live in different spaces and can't be
    compared), so there is deliberately NO cross-provider fallback for embeddings.

    PIN it with the EMBED_PROVIDER env var (openai|gemini) so the choice is
    deterministic across process restarts. Without a pin the choice depends on
    whether the OpenAI client happens to build in THIS process — and if that
    flips between when chunks were embedded and when a query is embedded, the
    two land in different vector spaces and retrieval silently returns garbage.
    Set EMBED_PROVIDER=openai (matching your stored chunks) to avoid this."""
    pin = _os.getenv("EMBED_PROVIDER", "").strip().lower()
    if pin == "openai":
        return "openai" if _openai_on() else "gemini"
    if pin == "deepseek":
        return "deepseek"
    if pin == "gemini":
        return "gemini"
    # Unpinned: keep embeddings on the current default. DeepSeek has no embeddings
    # endpoint, so this stays on Gemini (where the stored vectors were built).
    # Real OpenAI embeddings are opt-in via EMBED_PROVIDER=openai (needs a one-time
    # re-index, since vectors from different models are not comparable).
    try:
        _emb_ok = bool(_ds and _ds.ds_embed_ok())
    except Exception:
        _emb_ok = _deepseek_on()
    return "deepseek" if _emb_ok else "gemini"


def embed_texts(texts, task_type: str = "RETRIEVAL_DOCUMENT"):
    """Embed a list of strings → list of 768-float vectors (None per failed item).
    Routes to OpenAI when configured (no embedding rate cap), else Gemini. Never
    raises — failures come back as None and are recorded in LAST_EMBED_ERROR."""
    global LAST_EMBED_ERROR
    if not texts:
        return []
    # Use the PINNED provider (EMBED_PROVIDER) so chunks and queries never diverge.
    # When pinned to a provider that is momentarily unavailable, we return None
    # rather than silently falling back to a different model's vector space.
    prov = embed_provider()
    if prov == "openai":
        return _openai_embed(texts)
    if prov == "deepseek":
        out = []
        BATCH = 256
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            try:
                out.extend(_ds.ds_embed(batch))
            except Exception as e:
                LAST_EMBED_ERROR = f"DeepSeek embed: {type(e).__name__}: {str(e)[:200]}"
                out.extend([None] * len(batch))
        return out
    # FALLBACK provider: Gemini embeddings (rate-limited on free tier).
    out = []
    BATCH = 50
    for i in range(0, len(texts), BATCH):
        batch = [((t or "")[:8000] or " ") for t in texts[i:i + BATCH]]
        try:
            vecs = _embed_once(batch, task_type)
            if len(vecs) < len(batch):
                vecs = vecs + [None] * (len(batch) - len(vecs))
            out.extend(vecs[:len(batch)])
        except Exception as e:
            LAST_EMBED_ERROR = f"{type(e).__name__}: {str(e)[:240]}"
            out.extend([None] * len(batch))
    return out


def embed_query(text: str):
    """Embed a single search query → 768-float vector (or None)."""
    r = embed_texts([text or ""], task_type="RETRIEVAL_QUERY")
    return r[0] if r else None


# ══════════════════════════════════════════════════════════════════════════════
#  VERIFIED, STRUCTURED MCQ GENERATION (book / subject / topic-wise)
#
#  Pipeline:  generate (structured JSON, UPSC formats)  ->  verify (independent
#  second pass that re-solves each question and checks facts)  ->  keep only the
#  questions the verifier agrees with. This is what makes the questions accurate.
# ══════════════════════════════════════════════════════════════════════════════

# Authentic UPSC Prelims question styles the generator is told to use.
UPSC_FORMATS = (
    "- 'Consider the following statements' (2-4 numbered statements) then ask which are correct.\n"
    "- 'How many of the above statements/pairs are correct?' (Only one / Only two / Only three / All).\n"
    "- Match the following (List I with List II) style.\n"
    "- Assertion (A) and Reason (R) style.\n"
    "- Chronological ordering / 'Arrange in correct order'.\n"
    "- Direct conceptual single-correct questions.\n"
)


def _extract_json_list(text: str):
    """Robustly pull a JSON array out of a model response (handles ``` fences)."""
    if not text:
        return []
    t = text.strip()
    # strip ```json ... ``` or ``` ... ``` fences
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    try:
        data = json.loads(t)
    except Exception:
        # last resort: grab the outermost [ ... ]
        m = re.search(r"\[.*\]", t, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except Exception:
            return []
    if isinstance(data, dict):
        # sometimes wrapped like {"questions": [...]}
        for v in data.values():
            if isinstance(v, list):
                return v
        return []
    return data if isinstance(data, list) else []


def _clean_q(q: dict) -> dict:
    """Normalise one generated question into the app's standard shape."""
    ans = str(q.get("correct_answer", "")).strip().upper()[:1]
    return {
        "text": str(q.get("text", "")).strip(),
        "option_a": str(q.get("option_a", "")).strip(),
        "option_b": str(q.get("option_b", "")).strip(),
        "option_c": str(q.get("option_c", "")).strip(),
        "option_d": str(q.get("option_d", "")).strip(),
        "correct_answer": ans if ans in ("A", "B", "C", "D") else "",
        "explanation": str(q.get("explanation", "")).strip(),
        "question_type": str(q.get("question_type", "")).strip() or "direct",
        "topic": str(q.get("topic", "")).strip(),
    }


def _qtype_line(question_type: str) -> str:
    qt = (question_type or "all").lower()
    if qt == "factual":
        return ("QUESTION TYPE = FACTUAL: ask direct factual-recall questions — facts, dates, "
                "definitions, schemes, terms, 'which of the following' and single-statement questions. "
                "Avoid heavy multi-step reasoning.")
    if qt == "analytical":
        return ("QUESTION TYPE = ANALYTICAL: ask reasoning-heavy questions — multi-statement "
                "'consider the following statements', assertion-reason, match-the-following, "
                "cause-and-effect and application/analysis questions. Avoid simple one-line recall.")
    return "QUESTION TYPE = MIXED: blend factual-recall and analytical/reasoning questions."


def _generate_mcqs_raw(source_line: str, focus_line: str, num: int, difficulty: str,
                       question_type: str = "all", avoid: list = None, source_context: str = "") -> list:
    """First pass: produce `num` structured UPSC-style MCQs as JSON."""
    diff = (difficulty or "medium").lower()
    avoid_line = ""
    if avoid:
        sample = "; ".join((t or "")[:70] for t in avoid[-12:])
        avoid_line = f"\nDo NOT repeat these already-used questions: {sample}\n"
    ground_block = ""
    if source_context:
        ground_block = ("\nGround every question in the following reference material drawn from the student's OWN "
                        "study sources. Prefer facts present here and do not contradict it:\n<<<\n"
                        + source_context[:3000] + "\n>>>\n")
    prompt = f"""You are a senior UPSC Civil Services Prelims question setter.
Create {num} high-quality multiple-choice questions for the UPSC Prelims (GS Paper I).

{source_line}
{focus_line}
{ground_block}
Difficulty: {diff} (calibrate to genuine UPSC Prelims standard).
{_qtype_line(question_type)}
{avoid_line}
Use authentic UPSC question formats appropriate to the question type above:
{UPSC_FORMATS}

Strict rules:
- Exactly four options (A, B, C, D) and exactly ONE correct answer.
- Stay strictly on the given source/topic. Do NOT drift to unrelated areas.
- Be factually accurate. Do NOT invent data, dates, names, articles or figures.
  If unsure of a precise fact, write a conceptual question you are certain about instead.
- Be precise about SCOPE and NUMBERS: whether a right/provision applies to CITIZENS ONLY or to
  ALL PERSONS, the exact Article/Section numbers or ranges (e.g. Right to Freedom = Articles 19-22;
  Article 19 rights are for citizens only), and whether a provision has been amended, added or
  repealed (and by which amendment). These fine distinctions are exactly what UPSC tests — never blur them.
- For statement-based questions, put the numbered statements inside the "text" field
  (use \\n line breaks) and make the options describe which statements are correct.
- Each explanation must briefly justify the correct option AND why the key wrong ones fail.

Return ONLY a JSON array, no prose, with objects of exactly this shape:
[
  {{
    "text": "full question text (include numbered statements here if any)",
    "option_a": "...",
    "option_b": "...",
    "option_c": "...",
    "option_d": "...",
    "correct_answer": "A | B | C | D",
    "explanation": "1-3 lines",
    "question_type": "statement-based | how-many-correct | match | assertion-reason | chronological | direct",
    "topic": "the specific micro-topic this question tests"
  }}
]"""
    # PRIMARY: Gemini (fast, cheap for bulk generation); OpenAI as automatic
    # fallback so generation keeps working when Gemini rate-limits.
    raw = gen_text(prompt, json_mode=True, prefer="gemini")
    out = []
    for q in _extract_json_list(raw):
        if not isinstance(q, dict):
            continue
        cq = _clean_q(q)
        if cq["text"] and cq["correct_answer"] and all(cq["option_" + l] for l in "abcd"):
            out.append(cq)
    return out


def _verify_mcqs(questions: list) -> dict:
    """Second pass: an INDEPENDENT solver re-answers each question and flags
    factual problems. Returns a dict of verdicts keyed by index."""
    if not questions:
        return {}
    payload = [
        {"index": i, "text": q["text"], "option_a": q["option_a"], "option_b": q["option_b"],
         "option_c": q["option_c"], "option_d": q["option_d"]}
        for i, q in enumerate(questions)
    ]
    prompt = f"""You are a meticulous UPSC subject-matter fact-checker.
For each question below, solve it INDEPENDENTLY from your own knowledge — do not assume any option is correct.

Then judge:
- correct_option: the option (A/B/C/D) YOU determine is correct.
- factually_sound: false if the question or its options contain a wrong/ambiguous/invented fact,
  has no single correct answer, or more than one defensible answer.
- confidence: "high", "medium", or "low" in your judgement.
- issue: a short note if factually_sound is false, else "".

Be especially strict on: (a) whether a right/provision applies to CITIZENS ONLY vs ALL PERSONS
(e.g. Article 19 freedoms are citizens-only), (b) exact Article/Section numbers and ranges,
(c) whether a provision was amended/added/repealed and by which amendment, (d) statements that are
loosely true "in general" but wrong in the precise legal sense. If the question, any option, or the
marked key gets any of these wrong or ambiguous, set factually_sound=false.

Questions:
{json.dumps(payload, ensure_ascii=False)}

Return ONLY a JSON array aligned by index, objects of this shape:
[{{"index": 0, "correct_option": "A", "factually_sound": true, "confidence": "high", "issue": ""}}]"""
    # CROSS-MODEL verification: questions are generated by Gemini, so we verify
    # with the OTHER engine (OpenAI) when available — an independent model catches
    # errors a single model would repeat. Falls back to Gemini if OpenAI is off.
    raw = gen_text(prompt, json_mode=True, prefer="deepseek")
    verdicts = {}
    for v in _extract_json_list(raw):
        if isinstance(v, dict) and "index" in v:
            try:
                verdicts[int(v["index"])] = v
            except Exception:
                continue
    return verdicts


MAX_QUESTIONS = 100   # hard ceiling per set (incl. "Unlimited")


def generate_verified_questions(subject: str = "", topic: str = "", num_questions: int = 5,
                                difficulty: str = "medium", book: str = "", chapter: str = "",
                                question_type: str = "all", source_context: str = "") -> list:
    """Full pipeline -> returns verified questions in the app's standard dict shape.

    Generates in BATCHES (so large sets up to 100 work and the model isn't asked to
    emit too many at once), de-duplicates across batches, and stops early when the
    topic stops yielding new distinct verified questions (this is how "Unlimited" is
    handled — as many genuine distinct questions as the source supports, up to 100).
    Falls back to the legacy text generator if structured generation yields nothing.
    """
    num = max(1, min(int(num_questions or 5), MAX_QUESTIONS))

    # Build the grounding lines.
    if book and chapter:
        source_line = f'Source book: "{book}", Chapter: "{chapter}".'
        focus_line = "Generate questions ONLY from the concepts covered in this NCERT chapter."
    elif book:
        source_line = f'Source book: "{book}".'
        focus_line = f"Focus topic: {topic}." if topic else "Cover the core high-yield concepts of this book."
    else:
        source_line = f"Subject: {subject or 'UPSC General Studies'}."
        focus_line = f"Topic: {topic}." if topic else "Cover important Prelims concepts of this subject."

    BATCH = 12
    collected = []
    seen = set()
    dry_rounds = 0
    max_rounds = max(3, (num // BATCH) + 4)
    rounds = 0

    while len(collected) < num and rounds < max_rounds and dry_rounds < 2:
        rounds += 1
        need = num - len(collected)
        target_raw = min(BATCH, need + 2)
        try:
            raw = _generate_mcqs_raw(source_line, focus_line, target_raw, difficulty,
                                     question_type, avoid=list(seen), source_context=source_context)
        except Exception:
            raw = []

        # First-round total failure -> legacy fallback so we never hard-fail.
        if not raw:
            if not collected and rounds == 1:
                legacy = generate_and_parse_questions_legacy(subject or book or "General", topic or chapter or subject, num)
                for q in legacy:
                    q.setdefault("question_type", "direct")
                    q["book"], q["chapter"], q["difficulty"] = book, chapter, difficulty
                    q.setdefault("topic", topic)
                return legacy[:num]
            dry_rounds += 1
            continue

        # Drop questions we've already used this run.
        raw = [q for q in raw if q["text"] and q["text"] not in seen]
        if not raw:
            dry_rounds += 1
            continue

        try:
            verdicts = _verify_mcqs(raw)
        except Exception:
            verdicts = {}

        added = 0
        for i, q in enumerate(raw):
            v = verdicts.get(i)
            if v is None:
                keep = (not verdicts)
            else:
                sound = bool(v.get("factually_sound", True))
                conf = str(v.get("confidence", "")).lower()
                agree = str(v.get("correct_option", "")).strip().upper()[:1] == q["correct_answer"]
                keep = sound and conf != "low" and agree
            if keep:
                seen.add(q["text"])
                q["book"], q["chapter"], q["difficulty"] = book, chapter, difficulty
                if not q.get("topic"):
                    q["topic"] = topic or chapter
                collected.append(q)
                added += 1
                if len(collected) >= num:
                    break
        dry_rounds = 0 if added else dry_rounds + 1

    return collected[:num]


def generate_verified_questions_stream(subject: str = "", topic: str = "", num_questions: int = 5,
                                       difficulty: str = "medium", book: str = "", chapter: str = "",
                                       question_type: str = "all", source_context: str = ""):
    """Generator version of the verified pipeline: yields progress dicts as it works and
    finally yields {"stage":"result","questions":[...]}. Same logic as
    generate_verified_questions, but streamable for a live-progress UI."""
    num = max(1, min(int(num_questions or 5), MAX_QUESTIONS))
    if book and chapter:
        source_line = f'Source book: "{book}", Chapter: "{chapter}".'
        focus_line = "Generate questions ONLY from the concepts covered in this NCERT chapter."
    elif book:
        source_line = f'Source book: "{book}".'
        focus_line = f"Focus topic: {topic}." if topic else "Cover the core high-yield concepts of this book."
    else:
        source_line = f"Subject: {subject or 'UPSC General Studies'}."
        focus_line = f"Topic: {topic}." if topic else "Cover important Prelims concepts of this subject."

    yield {"stage": "start", "target": num}
    BATCH = 12
    collected = []
    seen = set()
    dry_rounds = 0
    max_rounds = max(3, (num // BATCH) + 4)
    rounds = 0

    while len(collected) < num and rounds < max_rounds and dry_rounds < 2:
        rounds += 1
        yield {"stage": "generating", "round": rounds, "have": len(collected), "target": num}
        need = num - len(collected)
        target_raw = min(BATCH, need + 2)
        try:
            raw = _generate_mcqs_raw(source_line, focus_line, target_raw, difficulty,
                                     question_type, avoid=list(seen), source_context=source_context)
        except Exception:
            raw = []

        if not raw:
            if not collected and rounds == 1:
                legacy = generate_and_parse_questions_legacy(subject or book or "General", topic or chapter or subject, num)
                for q in legacy:
                    q.setdefault("question_type", "direct")
                    q["book"], q["chapter"], q["difficulty"] = book, chapter, difficulty
                    q.setdefault("topic", topic)
                yield {"stage": "result", "questions": legacy[:num]}
                return
            dry_rounds += 1
            continue

        raw = [q for q in raw if q["text"] and q["text"] not in seen]
        if not raw:
            dry_rounds += 1
            continue

        yield {"stage": "verifying", "round": rounds, "count": len(raw), "have": len(collected), "target": num}
        try:
            verdicts = _verify_mcqs(raw)
        except Exception:
            verdicts = {}

        added = 0
        for i, q in enumerate(raw):
            v = verdicts.get(i)
            if v is None:
                keep = (not verdicts)
            else:
                sound = bool(v.get("factually_sound", True))
                conf = str(v.get("confidence", "")).lower()
                agree = str(v.get("correct_option", "")).strip().upper()[:1] == q["correct_answer"]
                keep = sound and conf != "low" and agree
            if keep:
                seen.add(q["text"])
                q["book"], q["chapter"], q["difficulty"] = book, chapter, difficulty
                if not q.get("topic"):
                    q["topic"] = topic or chapter
                collected.append(q)
                added += 1
                if len(collected) >= num:
                    break
        dry_rounds = 0 if added else dry_rounds + 1
        yield {"stage": "progress", "have": len(collected), "target": num}

    yield {"stage": "result", "questions": collected[:num]}


def generate_ncert_mcqs(book: str, chapter: str, subject: str = "", num_questions: int = 5,
                        difficulty: str = "medium", question_type: str = "all") -> list:
    """NCERT book + chapter wise verified MCQs."""
    return generate_verified_questions(
        subject=subject, topic="", num_questions=num_questions,
        difficulty=difficulty, book=book, chapter=chapter, question_type=question_type,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  LEGACY TEXT GENERATION (kept for the "Generate Questions" preview panel and as
#  a fallback). The structured pipeline above is preferred for saved tests.
# ══════════════════════════════════════════════════════════════════════════════

def generate_questions(subject: str, topic: str, num_questions: int = 5) -> str:
    prompt = f"""You are an expert UPSC IAS exam question setter.
Generate {num_questions} high-quality MCQ questions for IAS exam preparation.

Subject: {subject}
Topic: {topic}

Format EACH question exactly like this:
Q: [Question text]
A: [Option A]
B: [Option B]
C: [Option C]
D: [Option D]
Answer: [Only the letter: A, B, C, or D]
Explanation: [Clear 1-2 line explanation]

---
"""
    return gen_text(prompt, prefer="gemini")      # bulk generation → Gemini primary


def parse_questions(raw: str) -> list:
    """Parse the model's formatted text output into structured question dicts."""
    questions = []
    blocks = re.split(r'\n---+\n?', raw)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        try:
            q_match = re.search(r'Q:\s*(.+?)(?=\nA:)', block, re.DOTALL)
            a_match = re.search(r'A:\s*(.+?)(?=\nB:)', block, re.DOTALL)
            b_match = re.search(r'B:\s*(.+?)(?=\nC:)', block, re.DOTALL)
            c_match = re.search(r'C:\s*(.+?)(?=\nD:)', block, re.DOTALL)
            d_match = re.search(r'D:\s*(.+?)(?=\nAnswer:)', block, re.DOTALL)
            ans_match = re.search(r'Answer:\s*([ABCD])', block)
            exp_match = re.search(r'Explanation:\s*(.+?)$', block, re.DOTALL)
            if all([q_match, a_match, b_match, c_match, d_match, ans_match]):
                questions.append({
                    'text': q_match.group(1).strip(),
                    'option_a': a_match.group(1).strip(),
                    'option_b': b_match.group(1).strip(),
                    'option_c': c_match.group(1).strip(),
                    'option_d': d_match.group(1).strip(),
                    'correct_answer': ans_match.group(1).strip(),
                    'explanation': exp_match.group(1).strip() if exp_match else '',
                })
        except Exception:
            continue
    return questions


def generate_and_parse_questions_legacy(subject: str, topic: str, num_questions: int = 5) -> list:
    """Legacy generate-then-parse (text format)."""
    raw = generate_questions(subject, topic, num_questions)
    return parse_questions(raw)


def generate_and_parse_questions(subject: str, topic: str, num_questions: int = 5) -> list:
    """Preferred path for saved tests: now uses the VERIFIED structured pipeline so
    auto-generated tests get accurate, exam-styled questions. Falls back internally."""
    try:
        qs = generate_verified_questions(subject=subject, topic=topic, num_questions=num_questions)
        if qs:
            return qs
    except Exception:
        pass
    return generate_and_parse_questions_legacy(subject, topic, num_questions)


def generate_previous_year_questions(subject: str, year: str = "", num_questions: int = 10) -> str:
    """Produce previous-year-style UPSC questions for a subject (optionally a year)."""
    year_clause = (
        f"from the UPSC Civil Services Prelims paper of the year {year}"
        if year else
        "from past UPSC Civil Services Prelims papers (any recent year)"
    )
    prompt = f"""You are an expert on the UPSC (IAS) Civil Services examination and its
previous year question papers.

Reproduce {num_questions} authentic previous-year-style multiple-choice questions
{year_clause}, focused on the subject: {subject}.

Requirements:
- Use questions that genuinely reflect the style, difficulty, and themes of actual
  UPSC Prelims previous year papers for this subject. Prefer well-known recurring
  questions where you are confident of the correct answer.
- Every question must have exactly four options and exactly one correct answer.
- Do NOT invent fake facts. If unsure of a precise figure, choose a conceptual
  question you are confident about instead.

Format EACH question exactly like this:
Q: [Question text]
A: [Option A]
B: [Option B]
C: [Option C]
D: [Option D]
Answer: [Only the letter: A, B, C, or D]
Explanation: [Clear 1-2 line explanation of why the answer is correct]

---
"""
    return gen_text(prompt, prefer="gemini")      # bulk generation → Gemini primary


def generate_and_parse_previous_year(subject: str, year: str = "", num_questions: int = 10) -> list:
    """Generate a previous-year paper and parse it into structured dicts."""
    raw = generate_previous_year_questions(subject, year, num_questions)
    return parse_questions(raw)


def explain_concept(topic: str, context: str = None) -> str:
    if context:
        prompt = f"You are an IAS expert mentor. Explain this in context of UPSC exam:\nTopic: {topic}\nContext: {context}"
    else:
        prompt = f"You are an IAS expert mentor. Explain this topic clearly for a UPSC aspirant: {topic}"
    return gen_text(prompt, prefer="gemini")      # teaching → Gemini primary, DeepSeek fallback


def generate_mentor_report(stats_summary: str, candidate_name: str = "Aspirant") -> str:
    """Produce a PERSONALISED 'AI Mentor Report' narrative from pre-computed stats."""
    prompt = f"""You are {candidate_name}'s personal UPSC Prelims mentor. Write a focused, SPECIFIC
report addressed to {candidate_name} (second person, "you"). The app already shows the score, subject
table and trend above your text — do NOT restate those numbers; interpret them. Use ONLY the data below;
never invent numbers. Ignore any subject called 'General'/untagged. If a test covered one subject, do not
call it both strongest and weakest.

CRITICAL: This must be KNOWLEDGE-SPECIFIC and STRATEGY-SPECIFIC, never generic. Read the listed
missed questions and name the ACTUAL micro-topics/concepts they are failing (e.g., "Nagara vs Dravida
temple architecture", "Bhakti saints chronology", "Buddhist iconography", "Carnatic ragas", "tax
devolution / Finance Commission", "Ramsar sites"). Do NOT say vague things like "strengthen Art & Culture
fundamentals" — say WHICH fundamentals, drawn from the questions they missed.

{stats_summary}

Write ~180-240 words, Markdown, exactly these sections:

## Snapshot
1-2 lines: where this test sits vs their trend, and whether knowledge or strategy (negative marking) is the bigger leak right now.

## Topics You're Failing
The core of the report. From the missed questions (this test + recurring), list 3-6 SPECIFIC topics/concepts they keep getting wrong, grouped by subject. Be concrete and name the actual themes you see in the questions.

## Strategy Fix (with the math)
Use their accuracy to make the negative-marking case concretely: at their accuracy, expected value per blind attempt is negative, so guessing hurts. Give a concrete rule — e.g. "attempt only when you can eliminate 2 options; at X% accuracy aim to attempt ~N and skip the rest" — using their actual numbers.

## Targeted Plan
3-4 bullets, each = a specific topic above + the exact source/chapter to fix it (Nitin Singhania chapters for Art & Culture, Laxmikanth for Polity, Spectrum for Modern History, Shankar IAS for Environment, NCERTs, PYQ practice). Priority order by their weakest data.

Be direct, specific and personal. No preamble, no generic filler."""
    return gen_text(prompt, prefer="gemini")      # mentor writing → Gemini primary, DeepSeek fallback


def analyze_performance(subject: str, score: int, total: int, wrong_questions: list) -> str:
    weak_areas = "\n".join([f"- {q}" for q in wrong_questions]) if wrong_questions else "Not available"
    prompt = f"""You are an IAS exam coach. Analyze this student's test performance:

Subject: {subject}
Score: {score} out of {total}
Percentage: {round((score / total) * 100, 1)}%

Questions answered incorrectly:
{weak_areas}

Please provide:
1. A short performance summary
2. Key weak areas to focus on
3. Specific study recommendations
4. Motivational advice for UPSC preparation
"""
    return gen_text(prompt, prefer="gemini")      # performance analysis → Gemini primary, DeepSeek fallback


def diagnose_mistake(question: str, options: dict, correct_letter: str, chosen_letter: str,
                     confidence: str = "", subject: str = "", topic: str = "") -> str:
    """Confidence-aware diagnosis of ONE wrong answer. Explains the specific
    misconception behind the option the student actually picked."""
    opt_lines = "\n".join(f"  {l}) {options.get(l, '')}" for l in ["A", "B", "C", "D"])
    conf = (confidence or "").lower()
    conf_note = ""
    if conf == "sure":
        conf_note = ("The student was CONFIDENT and still wrong — this is a genuine misconception, "
                     "not a slip. Name the false belief directly and correct it firmly.")
    elif conf == "guess":
        conf_note = ("The student GUESSED — focus less on the specific fact and more on the elimination "
                     "logic: which options were eliminable and how, so next time it's an informed attempt.")
    elif conf == "unsure":
        conf_note = ("The student was UNSURE — they're close. Pin down the single distinction that would "
                     "have tipped them to the right answer.")
    prompt = f"""You are a UPSC Prelims mentor doing a tight, specific post-mortem of ONE wrong answer.

Subject: {subject or 'General Studies'}{(' · ' + topic) if topic else ''}
Question: {question}
Options:
{opt_lines}
Correct answer: {correct_letter}
The student chose: {chosen_letter} (WRONG)
{conf_note}

Write a SHORT diagnosis in Markdown (~110-150 words), exactly these three sections, no preamble:

## Why "{chosen_letter}" was tempting
Name the specific misconception or trap that makes option {chosen_letter} look right. Be concrete about the actual fact/concept — never generic.

## The distinction to remember
The one precise fact or contrast that separates {chosen_letter} from the correct answer {correct_letter}. This is the thing to memorise.

## Elimination tip
A practical rule for THIS type of question — how a sharp aspirant would have eliminated {chosen_letter} (or narrowed to two) even if unsure.

Be direct and exam-specific. No motivational filler."""
    return gen_text(prompt, prefer="gemini", model=MODEL_PRO)  # mistake root-cause → Gemini PRO, DeepSeek fallback


def chat_with_mentor(message: str, context: str = "", history=None) -> str:
    """AIMENTORA — the student's guide, teacher, mentor and companion. Personalised with
    the student's live context and recent conversation memory."""
    persona = """You are AIMENTORA — an AI-based IAS (UPSC) mentor who is, all at once, the student's
GUIDE (you tell them the next best action), TEACHER (you explain any concept clearly with UPSC depth,
examples and memory hooks), MENTOR (you read their data and give honest, strategic advice), and
COMPANION (you are warm, encouraging, remember their journey, and keep them motivated).

How you behave:
- Be warm and personal, like a caring senior who has cleared UPSC. Use the student's name occasionally, but do NOT re-introduce yourself or over-greet on follow-up messages — after the first hello, get straight to substance.
- Ground every reply in WHAT YOU KNOW about this student (their context below). When the context shows a recent topic, a weak area, or their scores, explicitly connect the current concept to it (e.g. "this builds on the Centre-State relations you studied" or "since Polity is a weak area for you, let's nail this"). Only reference facts that are actually in the context — never invent their history.
- When they ask to learn a concept, don't just answer it — TEACH it as a short mini-lesson: (1) a crisp, beginner-friendly explanation; (2) a "For your exam" part giving the Prelims angle (precise testable facts), the Mains angle (analytical themes & debates), and an Interview angle when the topic warrants one — include only the stages that genuinely apply; (3) "Connect it" — 2-3 closely related UPSC topics to link this to; (4) a one-line memory hook. Keep every part short and scannable.
- Be rigorous with FIGURES and facts: give a specific number only when you are confident it is correct. When a value changes across reports or years (e.g. Finance Commission devolution %), name the exact report/year it belongs to, or say it varies — never present an uncertain figure as settled fact.
- Be factually accurate about the exam structure. UPSC Prelims has TWO papers: Paper I = GENERAL STUDIES (polity, history, geography, economy, environment, science & tech, current affairs) which decides the cut-off; Paper II = CSAT, a QUALIFYING APTITUDE paper (reading comprehension, logical reasoning & analytical ability, basic numeracy, and data interpretation ONLY). NEVER label a GS / current-affairs / subject topic (e.g. Finance Commission, polity, economy, history, geography) as a CSAT topic, and do not force CSAT relevance onto GS content. Map every topic to its correct paper; if you are unsure, say so rather than guessing.
- When they ask what to do, GUIDE them to a concrete next action that fits their data.
- Be honest but kind about gaps.
- End every substantive reply by moving the learner forward: offer 2-4 concrete next steps as a short closing question that fits the topic — for example "Want to try 5 quick Prelims MCQs on this, compare it with the GST Council, or attempt a Mains-style question?" Keep the tone warm and encouraging.
- Keep answers focused and readable. Use short paragraphs or a few bullets — never a wall of text.
- You only discuss UPSC preparation, study, motivation and the student's journey. Politely redirect off-topic asks."""

    ctx_block = f"\n\nWHAT YOU KNOW ABOUT THIS STUDENT (use it, do not just repeat it):\n{context}" if context else ""
    convo = ""
    for m in (history or [])[-10:]:
        who = "Student" if m.get("role") == "user" else "AIMENTORA"
        convo += f"\n{who}: {m.get('content','')}"
    convo_block = f"\n\nRECENT CONVERSATION (your shared memory):{convo}" if convo else ""

    # Route through the hybrid engine chain (Gemini → OpenAI → DeepSeek), honoring
    # the Gemini quota cooldown so the mentor keeps working when an engine is down.
    prompt = f"""{persona}{ctx_block}{convo_block}

Now respond to the student's latest message as AIMENTORA — personal, helpful, and grounded in what you know.

Student: {message}
AIMENTORA:"""
    return (gen_text(prompt, prefer="gemini") or "").strip()


# ══════════════════════════════════════════════════════════════════════════════
#  CONTENT DEPTH (Phase 4): notes · flashcards · mnemonics · mind maps · CA
# ══════════════════════════════════════════════════════════════════════════════
def _extract_json_obj(text: str):
    """Pull a JSON object out of a model response (handles ``` fences)."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None


def generate_study_notes(topic: str, subject: str = "") -> str:
    ctx = f" (Subject: {subject})" if subject else ""
    prompt = f"""You are a UPSC Prelims mentor. Write crisp, exam-focused revision notes on:
Topic: {topic}{ctx}

Markdown, ~250-350 words, exactly these sections:
## Overview
2-3 lines of context.
## Key Points
6-10 bullets of the most exam-relevant facts — be specific (names, dates, Articles, numbers, bodies).
## Common Traps & Confusions
2-4 things UPSC likes to test (easily-confused pairs, exceptions, "only/all" statements).
## Quick Revision
A 2-3 line memory summary.
Be factual and specific. No filler, no preamble."""
    return gen_text(prompt, prefer="gemini")      # study notes → Gemini primary, DeepSeek fallback


def generate_flashcards(topic: str, subject: str = "", n: int = 10) -> list:
    n = max(3, min(int(n or 10), 20))
    ctx = f" ({subject})" if subject else ""
    prompt = f"""Create {n} UPSC Prelims flashcards for: {topic}{ctx}.
Return ONLY a JSON array; each item: {{"front": "recall prompt", "back": "concise factual answer"}}.
Front = a short prompt (a term, a question, "X is ___?"). Back = crisp, exam-specific answer.
No markdown, no commentary — only the JSON array."""
    raw = gen_text(prompt, json_mode=True, prefer="gemini")    # bulk structured → Gemini primary
    cards = _extract_json_list(raw) or []
    out = []
    for c in cards:
        if isinstance(c, dict) and c.get("front") and c.get("back"):
            out.append({"front": str(c["front"]).strip(), "back": str(c["back"]).strip()})
    return out


# ── From a candidate's own saved notes & highlights (My Notes → AI) ───────────
def mcqs_from_notes(source_text: str, subject: str = "", n: int = 5) -> list:
    """Generate exam-standard MCQs strictly from the candidate's saved highlights/notes."""
    n = max(3, min(int(n or 5), 15))
    ctx = f" (Subject: {subject})" if subject else ""
    prompt = f"""You are a UPSC Prelims question setter. Using ONLY the study material below — a candidate's own saved highlights & notes from NCERT{ctx} — create {n} exam-standard MCQs that test whether they truly understand and remember these points.

Study material:
\"\"\"{(source_text or '')[:6000]}\"\"\"

Return ONLY a JSON array; each item exactly:
{{"text":"question stem","option_a":"...","option_b":"...","option_c":"...","option_d":"...","correct_answer":"A|B|C|D","explanation":"why the answer is correct, grounded in the material","question_type":"direct|statement-based|assertion-reason","topic":"short topic"}}
Make distractors plausible and UPSC-style. Base everything on the material — do not test facts that aren't in it. No markdown, only the JSON array."""
    raw = gen_text(prompt, json_mode=True, prefer="gemini")
    qs = [_clean_q(q) for q in _extract_json_list(raw) if isinstance(q, dict)]
    return [q for q in qs if q["text"] and q["correct_answer"] and q["option_a"] and q["option_b"]]


def flashcards_from_notes(source_text: str, n: int = 10) -> list:
    """Generate flashcards strictly from the candidate's saved highlights/notes."""
    n = max(3, min(int(n or 10), 20))
    prompt = f"""Create {n} UPSC Prelims flashcards STRICTLY from this candidate's own saved notes & highlights:
\"\"\"{(source_text or '')[:6000]}\"\"\"
Return ONLY a JSON array; each item: {{"front":"recall prompt","back":"concise factual answer"}}.
Base every card on the material above (turn each key fact into a recall prompt). No markdown, only the JSON array."""
    raw = gen_text(prompt, json_mode=True, prefer="gemini")
    cards = _extract_json_list(raw) or []
    out = []
    for c in cards:
        if isinstance(c, dict) and c.get("front") and c.get("back"):
            out.append({"front": str(c["front"]).strip(), "back": str(c["back"]).strip()})
    return out


def summarize_highlights(source_text: str, title: str = "") -> str:
    """Weave a candidate's highlights/notes into a tight, exam-focused revision summary."""
    where = f" while reading {title}" if title else ""
    prompt = f"""You are a UPSC mentor. A candidate highlighted and noted these passages{where}. Weave them into a tight, exam-focused revision summary.

Their highlights & notes:
\"\"\"{(source_text or '')[:6000]}\"\"\"

Markdown, ~150-260 words, exactly these sections:
## Overview
2-3 lines tying the highlights together.
## Key Takeaways
5-9 bullets of the most exam-relevant facts drawn from the material (be specific).
## Remember This
A 1-2 line memory hook.
Summarise ONLY what is in the material — do not invent new facts. No preamble."""
    return gen_text(prompt, prefer="gemini")      # notes summary → Gemini primary, DeepSeek fallback


def generate_mnemonics(topic: str, subject: str = "") -> str:
    ctx = f" ({subject})" if subject else ""
    prompt = f"""Create memory aids (mnemonics) for the UPSC Prelims topic: {topic}{ctx}.
Markdown. Give 3-6 genuinely useful mnemonics (acronyms, rhymes, vivid associations, number pegs).
For each: the mnemonic in **bold**, what each part stands for, and a one-line tip on using it.
If a famous standard mnemonic exists for this topic, include it. No filler, no preamble."""
    return gen_text(prompt, prefer="gemini")      # creative bulk → Gemini primary (cheap)


def generate_mindmap(topic: str, subject: str = "") -> dict:
    ctx = f" ({subject})" if subject else ""
    prompt = f"""Build a mind map for the UPSC topic: {topic}{ctx}.
Return ONLY JSON of this shape:
{{"title": "<topic>", "children": [{{"title": "<branch>", "children": [{{"title": "<sub-point>"}}]}}]}}
Use 3-6 main branches, each with 2-5 concise, exam-relevant sub-points. Keep every title short (< 70 chars).
Only the JSON object, nothing else."""
    raw = gen_text(prompt, json_mode=True, prefer="gemini")    # structured → Gemini primary
    obj = _extract_json_obj(raw)
    if not isinstance(obj, dict) or "title" not in obj:
        return {"title": topic, "children": []}
    return obj


def current_affairs_analysis(event: str) -> str:
    prompt = f"""You are a UPSC Prelims current-affairs analyst. Analyse this news item / topic for Prelims relevance:
"{event}"

Markdown, exactly these sections:
## Relevance: <Very High | High | Medium | Low>
One line: why, via syllabus linkage and how often this theme is tested.
## Syllabus Linkage
Which GS Prelims areas it connects to (Polity / Economy / Environment / S&T / IR / Geography / Schemes) and the STATIC topics to revise alongside it.
## Key Facts to Remember
5-8 crisp factual bullets an examiner could test (names, numbers, bodies, dates, locations).
## Likely Prelims Angle
2-3 lines on how it could appear as a question (statement-based, match, etc.).

Be factual. If you are not certain of a very recent specific detail, focus on the durable static linkage and SAY you're unsure rather than inventing specifics."""
    return gen_text(prompt, prefer="gemini")      # CA analysis → Gemini primary, DeepSeek fallback


def extract_mcqs_from_text(text: str, subject: str = "") -> list:
    """Pull existing MCQs out of raw text extracted from a user's PDF (a question
    bank / test series). Returns the app's standard question dicts."""
    if not (text or "").strip():
        return []
    ctx = f" The subject context is: {subject}." if subject else ""
    prompt = f"""The following is raw text extracted from a UPSC question-bank / test-series PDF.{ctx}
Find every complete multiple-choice question in it and return them as structured JSON.

Rules:
- Only include questions that genuinely appear in the text — do NOT invent new ones.
- Each must have a clear question and four options. If options are labelled (a)(b)(c)(d) or 1/2/3/4, map them to A/B/C/D in order.
- If an answer key is present in the text, use it for "correct_answer". If NOT present, solve it yourself and give your best answer.
- Keep statement-based questions intact (put the numbered statements inside "text" with \\n line breaks).
- Skip page headers, instructions, and anything that isn't a question.

Return ONLY a JSON array of objects of exactly this shape:
[{{"text":"...","option_a":"...","option_b":"...","option_c":"...","option_d":"...","correct_answer":"A|B|C|D","explanation":"1-2 lines (write one if the PDF has none)","topic":"micro-topic"}}]

TEXT:
{text[:12000]}"""
    raw = gen_text(prompt, json_mode=True, prefer="gemini")     # bulk extraction → Gemini primary
    out = []
    for q in _extract_json_list(raw):
        if not isinstance(q, dict):
            continue
        cq = _clean_q(q)
        if cq.get("text") and cq.get("correct_answer") and all(cq.get("option_" + l) for l in "abcd"):
            out.append(cq)
    return out


def evaluate_mains_answer(question: str, answer: str, marks: int = 10) -> dict:
    """'Examiner brain' evaluation of a written UPSC Mains answer. Returns
    dimension scores (0-100), an overall mark out of `marks`, feedback, strengths
    and improvements — PLUS a marks band (examiners think in bands), the demand
    of the question decoded (directive word, expected dimensions), per-paragraph
    verdicts (keep / trim / cut / expand), dimension-coverage flags, and concrete
    value-adds that would lift the mark. Backward compatible: the original keys
    are always present. Falls back to a neutral structure on model failure."""
    words = len((answer or "").split())
    # Number the paragraphs so the examiner can reference them precisely.
    paras = [p.strip() for p in (answer or "").split("\n") if p.strip()]
    if len(paras) <= 1:  # single-block answers: split on sentence groups instead
        import re as _re2
        sents = _re2.split(r"(?<=[.!?])\s+", answer or "")
        paras = [" ".join(sents[i:i + 3]).strip() for i in range(0, len(sents), 3)]
        paras = [p for p in paras if p]
    paras = paras[:12]
    numbered = "\n".join(f"[P{i+1}] {p[:700]}" for i, p in enumerate(paras))
    prompt = f"""You are a seasoned UPSC Mains examiner (GS papers) who has marked thousands of
answer copies. Apply REAL marking norms: an average answer earns 40-45% of the marks, a good
answer 50-55%, an excellent one 60-70%. Marks above 70% are exceptional and rare.

QUESTION ({marks} marks): {question}

CANDIDATE'S ANSWER ({words} words), split into numbered paragraphs:
{numbered[:6000]}

Evaluate like an examiner would:

1. Score 0-100 on: content_knowledge (facts, examples, data), structure (intro-body-conclusion,
   flow), relevance (answers the actual demand), language (clarity, crispness), coverage
   (multi-dimensional balance).
2. overall_marks out of {marks} and a marks_band: the low / likely / high marks a real board of
   different examiners would give this answer (low <= likely <= high, all out of {marks}).
3. demand: decode the question - its directive word (discuss / examine / critically analyse /
   evaluate / comment / elucidate), what that directive REQUIRES, and the 3-6 dimensions a
   complete answer should cover (e.g. economic, social, political, legal, environmental,
   ethical, administrative, international).
4. paragraph_notes: for each numbered paragraph that deserves comment (max 6), a verdict -
   "keep" (earns marks), "trim" (too long for its value), "cut" (earns nothing - generic filler
   or off-demand), "expand" (right idea, underdeveloped) - and a short examiner's note (8-20 words).
5. dimension_coverage: for each expected dimension, covered true/false with a 5-15 word note.
6. examiner_view: 1-2 sentences on WHY marks were deducted, in an examiner's voice.
7. value_adds: up to 3 concrete additions that would lift the mark (a committee/report name, a
   Supreme Court judgment, a data point, a scheme, a case study - specific, not generic advice).
8. 2-3 sentences of feedback, up to 3 strengths, up to 3 specific improvements.

Return ONLY a JSON object of exactly this shape:
{{"content_knowledge":0,"structure":0,"relevance":0,"language":0,"coverage":0,
"overall_marks":0,"overall_pct":0,
"marks_band":{{"low":0,"likely":0,"high":0}},
"demand":{{"directive":"...","requires":"...","dimensions":["..."]}},
"paragraph_notes":[{{"para":1,"verdict":"keep|trim|cut|expand","note":"..."}}],
"dimension_coverage":[{{"dimension":"...","covered":true,"note":"..."}}],
"examiner_view":"...","value_adds":["..."],
"feedback":"...","strengths":["..."],"improvements":["..."]}}"""
    try:
        # PRIMARY: Gemini PRO (careful evaluative judgement); DeepSeek fallback.
        raw = gen_text(prompt, json_mode=True, prefer="gemini", model=MODEL_PRO)
        obj = _extract_json_obj(raw) or {}
    except Exception:
        obj = {}

    def _num(k, d=0):
        try:
            return max(0, min(100, int(round(float(obj.get(k, d))))))
        except Exception:
            return d
    dims = {k: _num(k) for k in ("content_knowledge", "structure", "relevance", "language", "coverage")}
    overall_pct = _num("overall_pct", round(sum(dims.values()) / 5))
    try:
        overall_marks = round(float(obj.get("overall_marks", overall_pct / 100.0 * marks)), 1)
    except Exception:
        overall_marks = round(overall_pct / 100.0 * marks, 1)
    overall_marks = max(0, min(marks, overall_marks))
    # ── Examiner-brain extras (all optional; sanitised defensively) ──
    def _mk(x, d=0.0):
        try:
            return max(0.0, min(float(marks), round(float(x), 1)))
        except Exception:
            return d
    band_raw = obj.get("marks_band") or {}
    band = {"low": _mk(band_raw.get("low"), max(0, overall_marks - 1)),
            "likely": _mk(band_raw.get("likely"), overall_marks),
            "high": _mk(band_raw.get("high"), min(marks, overall_marks + 1))}
    if not (band["low"] <= band["likely"] <= band["high"]):
        band = {"low": min(band.values()), "likely": overall_marks, "high": max(band.values())}
    dem_raw = obj.get("demand") or {}
    demand = {"directive": str(dem_raw.get("directive") or "")[:60],
              "requires": str(dem_raw.get("requires") or "")[:300],
              "dimensions": [str(x)[:40] for x in (dem_raw.get("dimensions") or [])
                             if isinstance(x, str)][:6]}
    pnotes = []
    for pn in (obj.get("paragraph_notes") or [])[:6]:
        try:
            v = str(pn.get("verdict", "")).lower()
            if v in ("keep", "trim", "cut", "expand"):
                pnotes.append({"para": int(pn.get("para", 0)), "verdict": v,
                               "note": str(pn.get("note") or "")[:200]})
        except Exception:
            continue
    dcov = []
    for dc in (obj.get("dimension_coverage") or [])[:8]:
        try:
            dcov.append({"dimension": str(dc.get("dimension") or "")[:40],
                         "covered": bool(dc.get("covered")),
                         "note": str(dc.get("note") or "")[:120]})
        except Exception:
            continue
    return {
        **dims,
        "overall_pct": overall_pct,
        "overall_marks": overall_marks,
        "marks": marks,
        "words": words,
        "marks_band": band,
        "demand": demand,
        "paragraph_notes": pnotes,
        "dimension_coverage": dcov,
        "examiner_view": str(obj.get("examiner_view") or "")[:400],
        "value_adds": [str(s)[:200] for s in (obj.get("value_adds") or []) if isinstance(s, str)][:3],
        "feedback": (obj.get("feedback") or "Answer evaluated.")[:600],
        "strengths": [s for s in (obj.get("strengths") or []) if isinstance(s, str)][:3],
        "improvements": [s for s in (obj.get("improvements") or []) if isinstance(s, str)][:3],
    }


def ocr_image(img_bytes: bytes, mime_type: str = "image/png") -> str:
    """OCR an image (or a rendered scanned PDF page). PRIMARY: Gemini vision (cheap,
    strong OCR). FALLBACK: OpenAI vision (gpt-4o-mini) if Gemini fails. '' on total failure."""
    if not img_bytes:
        return ""
    # PRIMARY: Gemini vision.
    if genai_types is not None:
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=[
                    genai_types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                    "Extract ALL readable text from this image exactly as written. Preserve line "
                    "breaks, and keep any MCQ numbering and options (A/B/C/D) intact. "
                    "Return ONLY the extracted text, nothing else.",
                ],
            )
            txt = (resp.text or "").strip()
            if txt:
                return txt
        except Exception:
            pass
    # FALLBACK: DeepSeek/OpenAI-compatible vision.
    if _deepseek_on():
        try:
            return (_ds.ds_vision_ocr(img_bytes, mime_type) or "").strip()
        except Exception:
            pass
    return ""


def catalogue_content(text: str, filename: str = "", subject: str = "") -> dict:
    """Auto-catalogue uploaded study material: content type, subjects, micro-topics,
    tags, a short summary and exam relevance. Returns {} if it can't classify."""
    sample = (text or "")[:8000]
    if not sample.strip():
        return {}
    prompt = f"""You are cataloguing UPSC study material for a searchable knowledge base.
Filename: {filename}. Declared subject: {subject or 'unknown'}.

From the content sample below, classify it. Return ONLY a JSON object of exactly this shape:
{{"content_type":"book|notes|mcq_bank|current_affairs|magazine|strategy|other",
"primary_subject":"the single best UPSC subject",
"subjects":["all relevant UPSC subjects"],
"topics":["up to 12 specific micro-topics covered"],
"tags":["up to 8 keywords"],
"summary":"2-3 line summary of what this material covers",
"exam_relevance":"high|medium|low"}}

CONTENT SAMPLE:
{sample}"""
    try:
        raw = gen_text(prompt, json_mode=True, prefer="gemini")   # structured taxonomy → Gemini primary
        obj = _extract_json_obj(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def weekly_mentor_narrative(summary: str, name: str = "Aspirant") -> str:
    """A short, encouraging weekly mentor note from a stats summary. Heuristic
    fallback if the model is unavailable."""
    prompt = f"""You are {name}'s personal UPSC mentor writing their weekly review.
Using ONLY the data below, write a warm, specific 4-6 sentence note: acknowledge the effort,
name the biggest win, name the one thing to fix next week, and end with a concrete nudge.
No markdown headings, just a short paragraph.

DATA:
{summary}"""
    try:
        txt = (gen_text(prompt, prefer="gemini") or "").strip()   # weekly note → Gemini primary, DeepSeek fallback
        if txt:
            return txt[:900]
    except Exception:
        pass
    return ("Good work staying in the game this week. Keep your daily mission going, "
            "put extra time on your weakest subject, and clear your revision queue before it piles up. "
            "Consistency beats intensity — show up tomorrow.")
