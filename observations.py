"""observations.py — S8 Reflection observation engine (M1, Phase 1).

Turns one run of ADR-001 `ASSESSMENT_ANSWERED` events into ranked, structured
observation candidates drawn from the library in `04_MENTOR_PERSONALITY_GUIDE.md` §11.

WHAT THIS MODULE IS
-------------------
A pure function. No database, no HTTP, no logging, no caching, no randomness, no
wall clock, no state. Given the same events it returns the same result, always —
which is what makes the reflection replay-safe and what keeps `01` Law 10 (never
contradict earlier advice) satisfiable.

It emits STRUCTURE ONLY: library index, family, valence, salience and the evidence
that produced it. No copy, no HTML, no learner-facing prose. Rendering is a later
phase and is canon's job, not this module's.

WHY IT CANNOT PRODUCE A CONTENT OBSERVATION
-------------------------------------------
`02` S8 AC-1: "The first observation is behavioural, not content. A content-first
reflection is a defect." That is enforced structurally rather than by discipline:
the only inputs are the run's events and the question bank. `diagnostic_gs`,
`diagnostic_csat`, `knowledge_level`, `comprehension_skill`, readiness, mastery,
projection, counts and growth_lever are not parameters and cannot be reached from
here. A content-based observation is not discouraged; it is unreachable.

WHY THE BANK IS INJECTED RATHER THAN IMPORTED
---------------------------------------------
The direction of an answer change — `04` §11's highest-value observation — needs the
answer key, which `diagnostic.py` keeps server-side by design ("answer keys never
leave here"). Passing the bank in as a parameter keeps this module importable and
testable without the application stack, and keeps the key where it belongs.

EVIDENCE THRESHOLDS (owner ruling D5)
-------------------------------------
Run-level behavioural pattern .... >= 2 supporting events
Subject observation ............. >= 3 supporting questions
Strong claim .................... >= 4 supporting data points
Insufficient evidence omits the observation. It is never weakened and never invented
(`01` Law 1, Law 2; `02` S8: "It never fabricates an observation to fill the screen").

REACHABLE LIBRARY ENTRIES
-------------------------
1-8 and 11-22 of the 38 in `04` §11. The rest are unreachable from data that exists,
and per owner ruling D6 nothing is inferred to reach them:
  9, 10     absolute pace          - needs a population baseline that does not exist,
                                     and comparison between learners is forbidden (Law 7)
  23-26     question construction  - the bank carries no pattern/question_type field
  27-30     confidence calibration - `04` §21 permits four questions in the whole
                                     relationship; a per-item confidence tag would be a fifth
  31-33     risk behaviour         - the screen has no skip control; every answer is forced
  34        distractor design      - no distractor metadata exists
  35-38     reading profile        - no current-affairs / static / map-based tagging exists
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Sequence

# ── families, in the precedence `04` §11 implies ────────────────────────────────
FAMILY_COMMITMENT = "COMMITMENT"   # second-guessing and commitment (obs 1-5)
FAMILY_TIME       = "TIME"         # time and triage (obs 6-12)
FAMILY_SHAPE      = "SHAPE"        # fatigue, warm-up and shape (obs 13-17)
FAMILY_STRUCTURE  = "STRUCTURE"    # the structure of what they know (obs 18-22)

# `04` §11 calls observation 1 "the highest-value observation in the library".
# Expressed as a family weight used ONLY to break ties at equal effect size.
_FAMILY_WEIGHT = {FAMILY_COMMITMENT: 4, FAMILY_TIME: 3, FAMILY_SHAPE: 2, FAMILY_STRUCTURE: 1}

# `02` S8 AC-1 — the first observation must be behavioural. STRUCTURE is about what
# they know, so it is excluded from beat 1 by construction.
BEHAVIOURAL_FAMILIES = (FAMILY_COMMITMENT, FAMILY_TIME, FAMILY_SHAPE)

POSITIVE = "POSITIVE"
NEGATIVE = "NEGATIVE"

# ── thresholds (owner ruling D5) ────────────────────────────────────────────────
MIN_RUN_SUPPORT   = 2   # run-level behavioural pattern
MIN_SUBJECT_ITEMS = 3   # subject observation
MIN_STRONG_CLAIM  = 4   # strong claim
MIN_ANSWERS       = 5   # `02` S8 entry condition / `03` OBSERVED
MAX_OBSERVATIONS  = 3   # `02` S8 AC-8; `04` §11 "two or three. Never more."

STATE_OK   = "OK"     # >= MIN_ANSWERS and at least one candidate
STATE_THIN = "THIN"   # fewer than MIN_ANSWERS answers  -> `02` S8 failure state
STATE_NONE = "NONE"   # enough answers, no candidate cleared threshold -> beats 4-5 only

_OUTLIER_MULTIPLE = 2.0   # an item-level claim needs the item to be a clear outlier


# ── normalisation ───────────────────────────────────────────────────────────────
def _answers(events: Sequence[Dict[str, Any]], bank: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Project ASSESSMENT_ANSWERED events into the flat table the observers read.

    Events are taken in `seq` order. `correct` is the server's recorded score;
    `first_correct` is computed against the bank's answer key, which is the only
    reason this engine runs server-side at all."""
    rows: List[Dict[str, Any]] = []
    ordered = sorted(events, key=lambda e: (e.get("seq") or 0))
    for e in ordered:
        if e.get("activity_type") != "ASSESSMENT_ANSWERED":
            continue
        m = e.get("metadata") or {}
        qid = m.get("question_id")
        item = bank.get(qid) or {}
        key = (item.get("answer") or "").strip().upper()[:1] or None
        sel = (m.get("selected") or "").strip().upper()[:1] or None
        first = (m.get("first_selected") or "").strip().upper()[:1] or None
        score = e.get("score")
        correct = bool(score) if score is not None else (sel is not None and sel == key)
        first_correct = (first is not None and key is not None and first == key)
        changed = int(m.get("changed_count") or 0)
        topics = e.get("topic_ids") or []
        rows.append({
            "position": m.get("position_in_run"),
            "question_id": qid,
            "subject": (topics[0] if topics else item.get("subject")),
            "kind": item.get("kind"),
            "difficulty": m.get("difficulty", item.get("difficulty")),
            "selected": sel,
            "first_selected": first,
            "changed_count": changed,
            "changed": changed > 0,
            "ms": e.get("duration"),
            "correct": correct,
            "first_correct": first_correct,
            "moved_away": changed > 0 and first_correct and not correct,
            "moved_toward": changed > 0 and (not first_correct) and correct,
        })
    return rows


def _timed(rows): return [r for r in rows if isinstance(r.get("ms"), (int, float)) and r["ms"] >= 0]
def _med(vals): return statistics.median(vals) if vals else None
def _cand(idx, family, valence, salience, qids, positions, facts):
    return {"library_index": idx, "family": family, "valence": valence,
            "salience": round(max(0.0, min(1.0, float(salience))), 6),
            "evidence": {"question_ids": list(qids), "positions": list(positions), "facts": dict(facts)}}


# ── observers · COMMITMENT (`04` §11 obs 1-5) ───────────────────────────────────
def _obs_commitment(rows):
    out = []
    ch = [r for r in rows if r["changed"]]
    if len(ch) >= MIN_RUN_SUPPORT:
        away = [r for r in ch if r["moved_away"]]
        toward = [r for r in ch if r["moved_toward"]]
        if len(away) == len(ch):
            out.append(_cand(1, FAMILY_COMMITMENT, NEGATIVE, min(1.0, len(away) / 3.0),
                             [r["question_id"] for r in away], [r["position"] for r in away],
                             {"changes": len(ch), "moved_away": len(away)}))
        elif len(toward) == len(ch):
            out.append(_cand(2, FAMILY_COMMITMENT, POSITIVE, min(1.0, len(toward) / 3.0),
                             [r["question_id"] for r in toward], [r["position"] for r in toward],
                             {"changes": len(ch), "moved_toward": len(toward)}))
        t = _timed(rows)
        if t and len(t) >= MIN_STRONG_CLAIM:
            med = _med([r["ms"] for r in t])
            slow_ids = {r["question_id"] for r in t if r["ms"] > med}
            if all(r["question_id"] in slow_ids for r in ch):
                out.append(_cand(4, FAMILY_COMMITMENT, POSITIVE, min(1.0, len(ch) / 3.0),
                                 [r["question_id"] for r in ch], [r["position"] for r in ch],
                                 {"changes": len(ch), "all_above_median_time": True}))
        easy = [r for r in ch if (r["difficulty"] or 2) <= 2]
        hard_unchanged = [r for r in rows if (r["difficulty"] or 2) >= 3 and not r["changed"]]
        if len(easy) == len(ch) and len(hard_unchanged) >= 1:
            out.append(_cand(5, FAMILY_COMMITMENT, NEGATIVE, min(1.0, len(easy) / 3.0),
                             [r["question_id"] for r in easy], [r["position"] for r in easy],
                             {"changes_on_easy": len(easy), "hard_left_alone": len(hard_unchanged)}))
    elif not ch and len(rows) >= MIN_STRONG_CLAIM:
        out.append(_cand(3, FAMILY_COMMITMENT, POSITIVE, min(1.0, len(rows) / 10.0),
                         [], [], {"changes": 0, "answers": len(rows)}))
    return out


# ── observers · TIME (`04` §11 obs 6-8, 11-12) ──────────────────────────────────
def _obs_time(rows):
    out = []
    t = _timed(rows)
    right = [r for r in t if r["correct"]]
    wrong = [r for r in t if not r["correct"]]
    if len(right) >= MIN_RUN_SUPPORT and len(wrong) >= MIN_RUN_SUPPORT:
        mr, mw = _med([r["ms"] for r in right]), _med([r["ms"] for r in wrong])
        if mr and mw:
            if mw >= mr * 1.5:
                out.append(_cand(6, FAMILY_TIME, POSITIVE, min(1.0, (mw / mr - 1.5) / 1.5),
                                 [r["question_id"] for r in right + wrong],
                                 [r["position"] for r in right + wrong],
                                 {"median_ms_correct": mr, "median_ms_incorrect": mw}))
            elif mr >= mw * 1.5:
                out.append(_cand(7, FAMILY_TIME, NEGATIVE, min(1.0, (mr / mw - 1.5) / 1.5),
                                 [r["question_id"] for r in right + wrong],
                                 [r["position"] for r in right + wrong],
                                 {"median_ms_correct": mr, "median_ms_incorrect": mw}))
    if len(t) >= MIN_STRONG_CLAIM:
        vals = [r["ms"] for r in t]
        med = _med(vals)
        if med and med > 0:
            cv = statistics.pstdev(vals) / med
            if cv <= 0.25:
                out.append(_cand(8, FAMILY_TIME, NEGATIVE, min(1.0, (0.25 - cv) / 0.25),
                                 [r["question_id"] for r in t], [r["position"] for r in t],
                                 {"coefficient_of_variation": round(cv, 4)}))
    if len(t) >= MIN_STRONG_CLAIM:
        med = _med([r["ms"] for r in t])
        longest = max(t, key=lambda r: (r["ms"], r["position"] or 0))
        if med and longest["ms"] >= med * _OUTLIER_MULTIPLE:
            idx, val = (11, POSITIVE) if longest["correct"] else (12, NEGATIVE)
            out.append(_cand(idx, FAMILY_TIME, val, min(1.0, (longest["ms"] / med - _OUTLIER_MULTIPLE) / 2.0),
                             [longest["question_id"]], [longest["position"]],
                             {"item_ms": longest["ms"], "run_median_ms": med, "correct": longest["correct"]}))
    return out


# ── observers · SHAPE (`04` §11 obs 13-17) ──────────────────────────────────────
def _obs_shape(rows):
    out = []
    n = len(rows)
    if n >= 6:
        half = n // 2
        a, b = rows[:half], rows[half:]
        if len(a) >= 3 and len(b) >= 3:
            fa = sum(1 for r in a if r["correct"]) / len(a)
            fb = sum(1 for r in b if r["correct"]) / len(b)
            if fa - fb >= 0.25:
                out.append(_cand(13, FAMILY_SHAPE, NEGATIVE, min(1.0, (fa - fb - 0.25) / 0.5),
                                 [r["question_id"] for r in rows], [r["position"] for r in rows],
                                 {"first_half_accuracy": round(fa, 4), "second_half_accuracy": round(fb, 4)}))
            elif fb - fa >= 0.25:
                out.append(_cand(14, FAMILY_SHAPE, POSITIVE, min(1.0, (fb - fa - 0.25) / 0.5),
                                 [r["question_id"] for r in rows], [r["position"] for r in rows],
                                 {"first_half_accuracy": round(fa, 4), "second_half_accuracy": round(fb, 4)}))
    if n >= MIN_STRONG_CLAIM and not rows[0]["correct"]:
        streak = 0
        for r in rows[1:]:
            if r["correct"]: streak += 1
            else: break
        if streak >= 3:
            ids = [rows[0]["question_id"]] + [r["question_id"] for r in rows[1:1 + streak]]
            out.append(_cand(15, FAMILY_SHAPE, POSITIVE, min(1.0, streak / 6.0),
                             ids, list(range(1, streak + 2)), {"opening_miss": True, "then_correct": streak}))
    for i, r in enumerate(rows):
        if (r["difficulty"] or 2) >= 3 and i + 2 < len(rows):
            nxt = rows[i + 1:i + 3]
            if all((x["difficulty"] or 2) <= 2 and not x["correct"] for x in nxt):
                out.append(_cand(16, FAMILY_SHAPE, NEGATIVE, 0.6,
                                 [r["question_id"]] + [x["question_id"] for x in nxt],
                                 [r["position"]] + [x["position"] for x in nxt],
                                 {"after_hard_item": r["question_id"], "following_missed": len(nxt)}))
                break
    t = _timed(rows)
    if len(t) >= MIN_STRONG_CLAIM + 2:
        tail, head = t[-2:], t[:-2]
        mt, mh = _med([r["ms"] for r in tail]), _med([r["ms"] for r in head])
        if mh and mt and mt <= mh * 0.5:
            out.append(_cand(17, FAMILY_SHAPE, NEGATIVE, min(1.0, (0.5 - mt / mh) / 0.5),
                             [r["question_id"] for r in tail], [r["position"] for r in tail],
                             {"median_ms_last_two": mt, "median_ms_rest": mh}))
    return out


# ── observers · STRUCTURE (`04` §11 obs 18-22) ──────────────────────────────────
def _obs_structure(rows):
    out = []
    by_subject: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if r["subject"]:
            by_subject.setdefault(r["subject"], []).append(r)
    for subject in sorted(by_subject):                      # sorted -> deterministic
        items = by_subject[subject]
        if len(items) < MIN_SUBJECT_ITEMS:                  # D5 subject threshold
            continue
        hard_right = [r for r in items if (r["difficulty"] or 2) >= 3 and r["correct"]]
        easy_wrong = [r for r in items if (r["difficulty"] or 2) <= 1 and not r["correct"]]
        if hard_right and easy_wrong:
            ids = [r["question_id"] for r in hard_right + easy_wrong]
            out.append(_cand(18, FAMILY_STRUCTURE, NEGATIVE, 0.6, ids,
                             [r["position"] for r in hard_right + easy_wrong],
                             {"subject": subject, "hard_correct": len(hard_right), "easy_incorrect": len(easy_wrong)}))
            continue
        diffs = {r["difficulty"] for r in items}
        if len(diffs) >= 2 and all(r["correct"] for r in items):
            out.append(_cand(19, FAMILY_STRUCTURE, POSITIVE, min(1.0, len(items) / 5.0),
                             [r["question_id"] for r in items], [r["position"] for r in items],
                             {"subject": subject, "items": len(items), "all_correct": True}))
        elif 0 < sum(1 for r in items if r["correct"]) < len(items):
            acc = sum(1 for r in items if r["correct"]) / len(items)
            out.append(_cand(20, FAMILY_STRUCTURE, NEGATIVE, min(1.0, 1.0 - abs(acc - 0.5) * 2),
                             [r["question_id"] for r in items], [r["position"] for r in items],
                             {"subject": subject, "items": len(items), "accuracy": round(acc, 4)}))
    gs = [r for r in rows if r["kind"] == "gs"]
    cs = [r for r in rows if r["kind"] == "csat"]
    if len(gs) >= MIN_STRONG_CLAIM and len(cs) >= MIN_STRONG_CLAIM:
        ag = sum(1 for r in gs if r["correct"]) / len(gs)
        ac = sum(1 for r in cs if r["correct"]) / len(cs)
        if ag - ac >= 0.25:
            out.append(_cand(21, FAMILY_STRUCTURE, NEGATIVE, min(1.0, (ag - ac - 0.25) / 0.5),
                             [r["question_id"] for r in gs + cs], [r["position"] for r in gs + cs],
                             {"factual_accuracy": round(ag, 4), "applied_accuracy": round(ac, 4)}))
        elif ac - ag >= 0.25:
            out.append(_cand(22, FAMILY_STRUCTURE, POSITIVE, min(1.0, (ac - ag - 0.25) / 0.5),
                             [r["question_id"] for r in gs + cs], [r["position"] for r in gs + cs],
                             {"factual_accuracy": round(ag, 4), "applied_accuracy": round(ac, 4)}))
    return out


_OBSERVERS = (_obs_commitment, _obs_time, _obs_shape, _obs_structure)


# If this observation could have been written before the learner answered the diagnostic, reject it.
def rank(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Total, stable order. Effect size decides; family weight breaks ties at equal
    effect (`04` §11 names observation 1 the highest-value in the library). Every
    remaining tie is broken by fixed data, never by input order, so the same run
    always yields the same reflection — which `01` Law 10 requires."""
    def key(c):
        ev = c["evidence"]
        return (-c["salience"],
                -_FAMILY_WEIGHT.get(c["family"], 0),
                c["library_index"],
                min([p for p in ev["positions"] if p is not None], default=10 ** 6),
                min(ev["question_ids"], default=""))
    return sorted(candidates, key=key)


def select(ranked: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The five-beat sequence of `02` S8. Beats 4 (the honest limit) and 5 (the
    forward) are fixed canonical copy and are not this engine's business.

    beat 1  the surprise          - behavioural families only (AC-1)
    beat 2  the strength          - genuine positive, or omitted (never invented)
    beat 3  the one that matters  - one gap, and only once a positive has landed
    """
    beats: List[Dict[str, Any]] = []
    used_families, used_qids = set(), set()

    def take(c):
        beats.append(c)
        used_families.add(c["family"])
        used_qids.update(c["evidence"]["question_ids"])

    def free(c):
        return (c["family"] not in used_families
                and not (used_qids & set(c["evidence"]["question_ids"])))

    # Beat 1 — the surprise. `02` S8 AC-1: "The first observation is behavioural,
    # not content. A content-first reflection is a defect." If nothing behavioural
    # cleared the threshold there is no reflection to lead with, and STRUCTURE is
    # not promoted to fill the gap — the screen falls back to beats 4-5.
    for c in ranked:
        if c["family"] in BEHAVIOURAL_FAMILIES:
            take(c); break
    if not beats:
        return []

    # Beat 2 — the strength. A real positive or none; never invented (`02` S8:
    # "It never fabricates an observation to fill the screen").
    for c in ranked:
        if c["valence"] == POSITIVE and free(c):
            take(c); break

    # Beat 3 — the one that matters. `04` §12: "Never more than one negative
    # before a positive lands." When beat 1 was itself a gap and no genuine
    # strength was found, the second gap is withheld rather than stacked on it.
    if beats[-1]["valence"] != NEGATIVE:
        for c in ranked:
            if c["valence"] == NEGATIVE and free(c):
                take(c); break
    return beats[:MAX_OBSERVATIONS]


def reflect(events: Sequence[Dict[str, Any]], bank: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """One run of ASSESSMENT_ANSWERED events -> structured observation candidates.

    Pure: no I/O, no clock, no randomness, no state. Emits no copy — rendering is a
    later phase. Returns `beats` (<= 3, in `02` S8 order) and the full ranked
    `candidates` list so any observation can be audited back to its evidence (AC-2).
    """
    rows = _answers(events, bank)
    if len(rows) < MIN_ANSWERS:
        return {"state": STATE_THIN, "answered": len(rows), "beats": [], "candidates": []}
    found: List[Dict[str, Any]] = []
    for observer in _OBSERVERS:
        found.extend(observer(rows))
    ranked = rank(found)
    beats = select(ranked)
    return {"state": STATE_OK if beats else STATE_NONE,
            "answered": len(rows), "beats": beats, "candidates": ranked}
