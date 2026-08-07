"""AIMENTORA adaptive diagnostic — measures knowledge level (GS) and comprehension/
reasoning (CSAT) to set an OBJECTIVE baseline that tailors the candidate's plan.

Stateless + server-authoritative: the client accumulates the answers it has given
and posts them each step; the server scores them (answer keys never leave here),
picks the next question at an adapted difficulty, and finalises the scores once the
short test (GS_TARGET + CSAT_TARGET questions) is complete.
"""
import json
import os
import random

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
    # Randomly choose among the items closest to the target difficulty, so the
    # assessment varies each attempt and can't be memorised by re-registering.
    best = min(abs(it.get("difficulty", 2) - difficulty) for it in pool)
    close = [it for it in pool if abs(it.get("difficulty", 2) - difficulty) == best]
    return random.choice(close)


# S7 AC-3 (02 S7): "The first question is one this learner, at their stated stage, is very
# likely to answer correctly." The floors below are 03's KNOWN calibration table, read against
# this bank's difficulty scale (1..3). Only the two stages 03 states explicitly are mapped;
# "full range" and the Mains track keep the existing default, so nothing is invented.
_OPENING_DIFFICULTY = {
    "I've just decided to prepare": 1,              # 03 KNOWN: "low difficulty floor"
    "I'm studying — haven't attempted yet": 2,      # 03 KNOWN: "moderate floor"
}


def next_question(answered, journey_stage=None):
    """Return the next adapted question (no answer key), or None when complete.

    `journey_stage` is the learner's S6 answer and calibrates the OPENING question only
    (02 S7 AC-3). It is optional: omitted, behaviour is exactly as before."""
    answered = answered or []
    asked_ids = {a.get("id") for a in answered}
    gs, csat = _kind_counts(answered)
    if gs >= GS_TARGET and csat >= CSAT_TARGET:
        return None
    want_gs = gs < GS_TARGET and (csat >= CSAT_TARGET or gs <= csat)
    kind = "gs" if want_gs else ("csat" if csat < CSAT_TARGET else "gs")
    _diff = _next_difficulty(answered, kind)
    if not answered and journey_stage in _OPENING_DIFFICULTY:   # opening question only
        _diff = _OPENING_DIFFICULTY[journey_stage]
    it = _pick(kind, _diff, asked_ids)
    if it is None:                       # pool exhausted → try the other kind
        other = "csat" if kind == "gs" else "gs"
        it = _pick(other, _diff if not answered else _next_difficulty(answered, other), asked_ids)
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
    count for more, so the score reflects the level actually reached.

    Also emits `by_subject`: the SAME difficulty-weighted score, grouped on the
    SUBJECT axis instead of the kind axis. The diagnostic owns the subject
    vocabulary, so it owns scoring against it — the subject->concept translator
    consumes this and must never re-score answers. Keys are the diagnostic's own
    raw subject labels (e.g. "Polity", "Environment"); NO normalisation to the
    concept vocabulary happens here (that is the translator's responsibility)."""
    answered = answered or []
    pairs = [(a, _BY_ID.get(a.get("id"))) for a in answered]

    def _score_items(items):
        denom = sum(it.get("difficulty", 2) for _a, it in items if it)
        num = sum(it.get("difficulty", 2) for a, it in items if it and _is_correct(a))
        correct = sum(1 for a, _it in items if _is_correct(a))
        return {"score": round(100 * num / denom) if denom else 0,
                "asked": len(items), "correct": correct}

    def kscore(kind):
        return _score_items([(a, it) for a, it in pairs if (it or {}).get("kind") == kind])

    gs = kscore("gs")
    csat = kscore("csat")

    by_subject = {}
    for _a, it in pairs:
        if not it:
            continue
        subj = it.get("subject")
        if not subj or subj in by_subject:
            continue
        by_subject[subj] = _score_items(
            [(a2, it2) for a2, it2 in pairs if it2 and it2.get("subject") == subj])

    return {"gs": gs["score"], "csat": csat["score"],
            "gs_detail": gs, "csat_detail": csat,
            "by_subject": by_subject, "answered": len(answered)}
