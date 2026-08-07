"""
mission_api.py — backend fulfilment of the FROZEN Mission API contract (mission_api.md).

Composes the event-sourced System-A pieces (mission_engine, learner_projection,
mission_outcome, the question bank) into the EXACT JSON the AIMLoop module consumes
via RealMissionAPI. Each function takes a db session + user_id and returns a
contract-shaped dict; the main.py routes are thin wrappers over these, so the logic
is unit-testable against a plain SQLAlchemy session (like the M-series modules).

Anchored on System A because that is the mission system the planner (det-1.0/det-1.1)
drives — the interface the experiment measures. Additive: emits only the existing
ADR-007 events (MISSION_STARTED / MCQ_ATTEMPTED / MISSION_COMPLETED); no new event types.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

import learner_events as le
import learner_projection as lp
import mission_engine as me
import mission_outcome as mo
import experiment as ex
import models

API_VERSION = 1
EST_MIN_PER_Q = 2.4                 # honest estimate: ~12 min for 5 questions
RETENTION_THRESHOLD = 0.6           # matches read_view "today" + mission_engine due gate


class MissionHasNoQuestions(Exception):
    """A mission's target resolves to zero servable questions — an invalid lifecycle
    state. Raised instead of returning 200 [] so the transport layer surfaces a
    structured 409 and the loop shows its error state rather than a silent, unwinnable
    mission. Pure signal: raising it never mutates mission state. Mission-specific by
    design — if unrelated modules ever raise it, the abstraction has drifted."""
    def __init__(self, mission_id: Optional[str], target: Optional[str]):
        self.mission_id = mission_id
        self.target = target
        super().__init__("mission %s target %r resolves to zero questions"
                         % (mission_id, target))


# ── helpers ──────────────────────────────────────────────────────────────────
def _concept_label(db, key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    row = (db.query(models.ConceptInventory)
           .filter(models.ConceptInventory.key == key).one_or_none())
    return (row.concept if row and getattr(row, "concept", None) else key)


def _view_and_payload(db, uid: int):
    row = lp.get_or_build(db, uid)
    payload = json.loads(row.payload or "{}")
    return lp.read_view(payload), payload


def _find_mission(db, uid: int, mid: str) -> Optional[Dict[str, Any]]:
    for m in me.mission_state(db, uid)["missions"]:
        if m["mission_id"] == mid:
            return m
    return None


def _servable_questions(db, target, n):
    """The ONE strict definition of a concept's servable questions: exact concept_key
    match against the canonical vocabulary (NO retired-label guessing). Shared by the
    answerability guard, the runner, and metadata so they can never drift."""
    if not target:
        return []
    return (db.query(models.Question)
              .filter(models.Question.concept_key == target)
              .order_by(models.Question.id.asc()).limit(n).all())


def _target_answerable(db, target) -> bool:
    """Answerability has ONE definition — mission_engine.is_answerable (me.question_count).
    Delegating keeps this guard, the planner, and the runner from ever diverging."""
    return me.is_answerable(db, target)


def _question_meta(db, key: Optional[str]):
    """Real subject + representative difficulty from the mission's question bank."""
    if not key:
        return (None, None)
    qs = _servable_questions(db, key, 30)
    if not qs:
        return ("General Studies", "Medium")
    subj = next((q.subject for q in qs if getattr(q, "subject", None)), "General Studies")
    diffs = [(q.difficulty or "").strip().capitalize() for q in qs if getattr(q, "difficulty", None)]
    diff = max(set(diffs), key=diffs.count) if diffs else "Medium"
    return (subj, diff)


def _selection_reason(view: Dict[str, Any], concept: Optional[str]) -> Dict[str, Any]:
    """STRUCTURED, machine-readable rationale (audit/evidence) — G1 layer 1."""
    ret = (view.get("retention") or {}).get(concept)
    gl = (view.get("growth_lever") or {})
    per = (view.get("per_concept") or {}).get(concept, {}) if concept else {}
    return {
        "lowest_mastery": gl.get("concept") == concept,
        "retention_due": ret is not None and ret < RETENTION_THRESHOLD,
        "mastery": per.get("mastery"),
        "attempts": per.get("attempts", 0),
    }


def _reason_copy(struct: Dict[str, Any], label: Optional[str]) -> List[str]:
    """Learner-facing copy rendered from the structured reason — G1 layer 2.
    The endpoint returns THIS, never the raw mechanics, so the planner can evolve
    internally without changing UI copy."""
    out: List[str] = []
    if struct.get("lowest_mastery"):
        out.append("%s is currently your weakest area." % (label or "This concept"))
    if struct.get("retention_due"):
        out.append("It’s due for spaced revision.")
    if not out:
        out.append("This mission targets a concept you can strengthen now.")
    out.append("Strengthening it now improves long-term retention.")
    return out


def _pct(x: Optional[float]) -> Optional[int]:
    return None if x is None else int(round(x * 100))


def _answered_count(db, uid: int, target: Optional[str],
                    started_seq: Optional[int], total: int) -> int:
    """Count MCQ_ATTEMPTED on `target` with seq > started_seq, capped at total.
    SAME definition mission_engine.evaluate_completion uses (ADR-011) — so `answered`
    and 'complete' can never disagree. Not started (started_seq None) => 0."""
    if started_seq is None:
        return 0
    c = 0
    for ev in _all_events(db, uid):
        if ev.activity_type != "MCQ_ATTEMPTED":
            continue
        if ev.seq <= started_seq:
            continue
        cids = json.loads(ev.concept_ids) if ev.concept_ids else []
        if target is None or target in cids:
            c += 1
    return min(c, total)


def _progress(answered: int, total: int) -> Dict[str, Any]:
    """ADR-011 mission-owned progress read-model. Informational, not authoritative:
    completion stays with the mission engine; this never gates it."""
    return {"answered": answered, "total": total,
            "remaining": max(0, total - answered),
            "percent": int(round(answered / total * 100)) if total else 0}


# ── G0 + getCurrentMission (composite so RealMissionAPI stays a thin 1:1 fetch) ─
def current_mission(db, uid: int) -> Dict[str, Any]:
    """GET /me/mission/current — the dashboard payload. Ensures a mission exists
    (idempotent generate through the active experiment) then returns it + why + stats."""
    ms = me.mission_state(db, uid)
    if ms["active"] is None:
        ex.generate_if_enrolled(db, uid)          # idempotent: no-op if one is active
        ms = me.mission_state(db, uid)
    m = ms["active"]
    # Self-heal (docs/INVESTIGATION_mission_vocabulary.md): a stale active mission whose
    # target no longer resolves to any question (retired-vocabulary / pre-divergence data)
    # is retired and regenerated, so the learner gets a fresh answerable mission instead of
    # the 409 dead-end. Strict answerability only — no retired-label guessing.
    if m is not None and not _target_answerable(db, (m.get("target_concept_ids") or [None])[0]):
        import logging as _log
        _stale_t, _stale_mid = (m.get("target_concept_ids") or [None])[0], m.get("mission_id")
        _log.getLogger("aimarga").warning(
            "stale-mission self-heal: uid=%s mid=%s target=%r q=%d -> MISSION_CANCELLED(stale_vocabulary)",
            uid, _stale_mid, _stale_t, me.question_count(db, _stale_t))
        me.cancel(db, uid, _stale_mid, reason="stale_vocabulary")
        ex.generate_if_enrolled(db, uid)
        ms = me.mission_state(db, uid)
        m = ms["active"]
        _new_t = (m.get("target_concept_ids") or [None])[0] if m else None
        _log.getLogger("aimarga").warning(
            "stale-mission self-heal: uid=%s regenerated mid=%s target=%r q=%d",
            uid, (m.get("mission_id") if m else None), _new_t,
            me.question_count(db, _new_t) if _new_t else 0)
    view, payload = _view_and_payload(db, uid)
    if m is None:
        return {"mission_id": None, "state": "NONE", "version": API_VERSION,
                "started": False, "completed": False, "concept": None, "subject": None,
                "n_questions": 0, "difficulty": None, "est_minutes": 0,
                "mastery": None, "revision_due": 0, "reason": [], "progress": None}
    target = (m.get("target_concept_ids") or [None])[0]
    n = (m.get("steps") or [{}])[0].get("n", me.DEFAULT_STEPS_N)
    mastery = ((payload.get("per_concept") or {}).get(target, {}) or {}).get("mastery")
    subj, diff = _question_meta(db, target)
    label = _concept_label(db, target)
    revision_due = sum(1 for r in view.get("revision_schedule", []) if r["due"] in ("today", "soon"))
    answered = _answered_count(db, uid, target, m.get("started_seq"), n)
    return {
        "mission_id": m["mission_id"], "state": m["state"], "version": API_VERSION,
        "started": m.get("started_seq") is not None, "completed": m["state"] == "COMPLETED",
        "concept": label, "subject": subj, "n_questions": n, "difficulty": diff,
        "est_minutes": int(round(n * EST_MIN_PER_Q)), "mastery": _pct(mastery),
        "revision_due": revision_due,
        "reason": _reason_copy(_selection_reason(view, target), label),
        "progress": _progress(answered, n),
    }


# ── G2 GET /me/mission/{id} ──────────────────────────────────────────────────
def mission_detail(db, uid: int, mid: str) -> Optional[Dict[str, Any]]:
    m = _find_mission(db, uid, mid)
    if m is None:
        return None
    target = (m.get("target_concept_ids") or [None])[0]
    n = (m.get("steps") or [{}])[0].get("n", me.DEFAULT_STEPS_N)
    subj, diff = _question_meta(db, target)
    return {"concept": _concept_label(db, target), "subject": subj,
            "n_questions": n, "difficulty": diff, "est_minutes": int(round(n * EST_MIN_PER_Q))}


def _question_dto(q: "models.Question") -> Dict[str, Any]:
    """Single definition of the contract-shaped question payload — id, text, options.
    NEVER the correct option. One place to evolve if the payload grows (explanation,
    media, etc.)."""
    return {"id": str(q.id), "text": q.text,
            "options": [q.option_a, q.option_b, q.option_c, q.option_d]}


def ensure_mission_answerable(db, uid: int, m: Dict[str, Any]) -> List["models.Question"]:
    """Guarantee a mission is safe to start: return its servable question ROWS, or raise
    MissionHasNoQuestions if the target resolves to none.

    The lifecycle invariant lives HERE, not in any single endpoint: a mission must never
    enter STARTED unless it can serve at least one question. Both entry points — G3
    (GET .../questions) and POST .../start — go through this one guard. PURE: it queries
    but never starts or mutates the mission; the caller owns its MISSION_STARTED
    transition and any serialization of the rows returned."""
    target = (m.get("target_concept_ids") or [None])[0]
    n = (m.get("steps") or [{}])[0].get("n", me.DEFAULT_STEPS_N)
    qs = _servable_questions(db, target, n)
    if not qs:
        raise MissionHasNoQuestions(m.get("mission_id"), target)
    return qs


# ── G3 GET /me/mission/{id}/questions (+ MISSION_STARTED) ────────────────────
def mission_questions(db, uid: int, mid: str) -> Optional[List[Dict[str, Any]]]:
    m = _find_mission(db, uid, mid)
    if m is None:
        return None                                    # → 404 at the route
    # Resolve questions BEFORE transitioning CREATED→STARTED.
    # A mission must never enter STARTED unless it can serve at least one question;
    # resolving first means a zero-question target fails cleanly at CREATED instead of
    # leaving a STARTED-but-unanswerable mission. Do not reorder — this is the invariant.
    qs = ensure_mission_answerable(db, uid, m)         # raises MissionHasNoQuestions if empty
    if m["state"] == "CREATED":
        me.start(db, uid, mid)                         # begin only once answerable → MISSION_STARTED
    return [_question_dto(q) for q in qs]


# ── POST /me/mission/{id}/start — same invariant, same shared guard ──────────
def start_mission(db, uid: int, mid: str) -> Optional[Dict[str, Any]]:
    """Standalone start path — validates answerability through the SAME guard before
    transitioning, so /start honours the identical 'never STARTED unless answerable'
    rule as G3 (a system property, not a per-endpoint one)."""
    m = _find_mission(db, uid, mid)
    if m is None:
        return None                                    # → 404 at the route
    ensure_mission_answerable(db, uid, m)              # raises MissionHasNoQuestions if empty
    return me.start(db, uid, mid)                      # lifecycle transition → MISSION_STARTED


# ── G4: the loop routes attempts through the EXISTING POST /me/attempt, NOT a
# forked endpoint — /me/attempt already emits MCQ_ATTEMPTED with the same idempotent
# event_id and updates the projection the loop reads, so a second attempt path would
# be a duplicate emitter (a drift source). This helper only supplies the field
# /me/attempt doesn't yet return, so its response becomes a superset of submitAnswer's
# contract shape {correct, correct_index, explanation}. ──────────────────────
def letter_index(letter) -> Optional[int]:
    """Map an answer letter (A–D) to its 0-based index; None if unrecognised."""
    if not letter:
        return None
    c = str(letter).strip().upper()[:1]
    return "ABCD".index(c) if c in "ABCD" else None


# ── G5 GET /me/mission/{id}/outcome ──────────────────────────────────────────
def _all_events(db, uid: int):
    out, last = [], 0
    while True:
        b = le.fetch_events(db, uid, after_seq=last, limit=2000)
        if not b:
            break
        out.extend(b); last = b[-1].seq
        if len(b) < 2000:
            break
    return out


def _accuracy(db, uid: int, target: Optional[str], lo: Optional[int], hi: Optional[int]):
    """correct/total over MCQ_ATTEMPTED on `target` with lo < seq <= hi (hi None = open)."""
    tot = cor = 0
    for ev in _all_events(db, uid):
        if ev.activity_type != "MCQ_ATTEMPTED":
            continue
        if lo is not None and ev.seq <= lo:
            continue
        if hi is not None and ev.seq > hi:
            continue
        cids = json.loads(ev.concept_ids) if ev.concept_ids else []
        if target is None or target in cids:
            tot += 1
            if (ev.score or 0) > 0:
                cor += 1
    return None if tot == 0 else int(round(cor / tot * 100))


def _revision_in_days(mastery: Optional[float]) -> int:
    """Days until retention decays below threshold, from the read-time retention model
    (half-life 10d). Honest model output, not a fabricated number."""
    if mastery is None or mastery <= RETENTION_THRESHOLD:
        return 0
    d = _RETENTION_HALFLIFE * math.log(mastery / RETENTION_THRESHOLD, 2)
    return max(1, int(round(d)))


_RETENTION_HALFLIFE = 10.0


def _next_recommendation(db, uid: int, just_done: Optional[str]) -> Optional[Dict[str, Any]]:
    """The planner's next pick: lowest-mastery eligible concept that isn't the one
    just completed (deterministic — literally what det-1.0 would choose next)."""
    _, payload = _view_and_payload(db, uid)
    per = payload.get("per_concept") or {}
    cands = sorted(((v.get("mastery", 0.0), k) for k, v in per.items() if k != just_done))
    if not cands:
        return None
    concept = cands[0][1]
    return {"concept": _concept_label(db, concept),
            "est_minutes": int(round(me.DEFAULT_STEPS_N * EST_MIN_PER_Q))}


def mission_outcome_view(db, uid: int, mid: str) -> Optional[Dict[str, Any]]:
    me.evaluate_completion(db, uid)               # emits MISSION_COMPLETED if step count reached
    row = mo.get_or_build(db, uid)
    o = next((x for x in json.loads(row.payload or "{}").get("outcomes", [])
              if x["mission_id"] == mid), None)
    if o is None:
        return None
    lo = o.get("created_seq")
    started, term = o.get("started_seq"), o.get("terminal_seq")
    return {
        "accuracy_before": _accuracy(db, uid, o.get("target"), None, lo),
        "accuracy_after": _accuracy(db, uid, o.get("target"), started, term),
        "mastery_before": _pct(o.get("mastery_before")),
        "mastery_after": _pct(o.get("mastery_after")),
        "revision_in_days": _revision_in_days(o.get("mastery_after")),
        "next_recommendation": _next_recommendation(db, uid, o.get("target")),
    }
