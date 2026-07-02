"""AIVORA adaptive diagnostic — measures knowledge level (GS) and comprehension/
reasoning (CSAT) to set an OBJECTIVE baseline that tailors the candidate's plan.

Stateless + server-authoritative: the client accumulates the answers it has given
and posts them each step; the server scores them (answer keys never leave here),
picks the next question at an adapted difficulty, and finalises the scores once the
short test (GS_TARGET + CSAT_TARGET questions) is complete.
"""
import json
import os

_BANK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diagnostic_bank.json")
GS_TARGET = 8          # knowledge questions
CSAT_TARGET = 6        # comprehension/reasoning questions
TOTAL = GS_TARGET + CSAT_TARGET


def _load():
    try:
        with open(_BANK_FILE, encoding="utf-8") as f:
            return json.load(f).get("items", [])
    except Exception:
        return []


_ITEMS = _load()
_BY_ID = {it["id"]: it for it in _ITEMS}


def _kind_counts(answered):
    gs = sum(1 for a in answered if (_BY_ID.get(a.get("id")) or {}).get("kind") == "gs")
    csat = sum(1 for a in answered if (_BY_ID.get(a.get("id")) or {}).get("kind") == "csat")
    return gs, csat


def _is_correct(a):
    it = _BY_ID.get(a.get("id"))
    return bool(it) and (str(a.get("selected", "")).upper() == it.get("answer"))


def _next_difficulty(answered, kind):
    """Adapt: harder after a correct answer of this kind, easier after a wrong one."""
    last = None
    for a in answered:
        it = _BY_ID.get(a.get("id"))
        if it and it.get("kind") == kind:
            last = a
    if not last:
        return 2
    d = (_BY_ID.get(last.get("id")) or {}).get("difficulty", 2)
    return min(3, d + 1) if _is_correct(last) else max(1, d - 1)


def _pick(kind, difficulty, asked_ids):
    pool = [it for it in _ITEMS if it.get("kind") == kind and it["id"] not in asked_ids]
    if not pool:
        return None
    pool.sort(key=lambda it: abs(it.get("difficulty", 2) - difficulty))
    return pool[0]


def next_question(answered):
    """Return the next adapted question (no answer key), or None when complete."""
    answered = answered or []
    asked_ids = {a.get("id") for a in answered}
    gs, csat = _kind_counts(answered)
    if gs >= GS_TARGET and csat >= CSAT_TARGET:
        return None
    want_gs = gs < GS_TARGET and (csat >= CSAT_TARGET or gs <= csat)
    kind = "gs" if want_gs else ("csat" if csat < CSAT_TARGET else "gs")
    it = _pick(kind, _next_difficulty(answered, kind), asked_ids)
    if it is None:                       # pool exhausted → try the other kind
        other = "csat" if kind == "gs" else "gs"
        it = _pick(other, _next_difficulty(answered, other), asked_ids)
    if it is None:
        return None
    q = {"id": it["id"], "kind": it["kind"], "subject": it.get("subject", ""),
         "difficulty": it.get("difficulty", 2), "text": it["text"], "options": it["options"],
         "index": len(answered) + 1, "total": TOTAL}
    if it.get("passage"):
        q["passage"] = it["passage"]
    return q


def score(answered):
    """Difficulty-weighted score (0-100) for each track. Harder correct answers
    count for more, so the score reflects the level actually reached."""
    answered = answered or []

    def kscore(kind):
        items = [(a, _BY_ID.get(a.get("id"))) for a in answered
                 if (_BY_ID.get(a.get("id")) or {}).get("kind") == kind]
        denom = sum(it.get("difficulty", 2) for _a, it in items if it)
        num = sum(it.get("difficulty", 2) for a, it in items if it and _is_correct(a))
        correct = sum(1 for a, _it in items if _is_correct(a))
        return {"score": round(100 * num / denom) if denom else 0,
                "asked": len(items), "correct": correct}

    gs = kscore("gs")
    csat = kscore("csat")
    return {"gs": gs["score"], "csat": csat["score"],
            "gs_detail": gs, "csat_detail": csat, "answered": len(answered)}
