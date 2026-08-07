"""
mission_engine.py — ADR-007 Mission Lifecycle + ADR-005 generator (M4).

Missions live ENTIRELY as MISSION_* events on the event bus (ADR-003); mission
state is a replayable projection folded from those events. The generator reads
the Learner Projection and CREATES missions — it never writes learner state
(ADR-001/007: learner events create learner state; AI consumes it, never owns it).

Swappable policy: `mission-policy-det-1.0` (deterministic) and a stub
`mission-policy-llm-1.0` emit the SAME MISSION_CREATED contract; only the
selection step and `policy_version` differ (ADR-007 → MG-05).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text as _sql_text

import learner_events as le
import learner_projection as lp

MISSION_ACTIVITIES = ("MISSION_CREATED", "MISSION_STARTED", "MISSION_COMPLETED",
                      "MISSION_CANCELLED", "MISSION_EXPIRED")
ACTIVE_STATES = ("CREATED", "STARTED")
POLICY_DET = "mission-policy-det-1.0"
POLICY_LLM = "mission-policy-llm-1.0"
POLICY_DET_11 = "mission-policy-det-1.1"   # Phase B: spaced-repetition-aware (due gate)
DEFAULT_STEPS_N = 5

# det-1.1 due gate: a concept is "due for review" when its read-time retention has
# decayed below this line (aligns with read_view's "today" bucket). The ONLY thing
# that differs from det-1.0; everything else (contract, lifecycle, events,
# projection, evaluator, promotion) is identical.
RETENTION_DUE_THRESHOLD = 0.6


# ── read all of a user's events (paged) ──────────────────────────────────────
def _all_events(db, user_id: int):
    out, last = [], 0
    while True:
        batch = le.fetch_events(db, user_id, after_seq=last, limit=2000)
        if not batch:
            break
        out.extend(batch)
        last = batch[-1].seq
        if len(batch) < 2000:
            break
    return out


# ── mission-state projection (deterministic fold over MISSION_* events) ───────
def mission_state(db, user_id: int) -> Dict[str, Any]:
    missions: Dict[str, Any] = {}
    order: List[str] = []
    for ev in _all_events(db, user_id):
        at = ev.activity_type
        if at not in MISSION_ACTIVITIES:
            continue
        meta = json.loads(ev.meta) if ev.meta else {}
        mid = meta.get("mission_id")
        if not mid:
            continue
        if at == "MISSION_CREATED":
            if mid not in missions:
                missions[mid] = {
                    "mission_id": mid, "state": "CREATED",
                    "target_concept_ids": json.loads(ev.concept_ids) if ev.concept_ids else [],
                    "created_from_seq": meta.get("created_from_seq"),
                    "policy_version": meta.get("policy_version"),
                    "steps": meta.get("steps"),
                    "created_seq": ev.seq, "started_seq": None, "outcome": None,
                }
                order.append(mid)
            continue
        m = missions.get(mid)
        if not m:
            continue  # transition for an unknown mission — ignore
        st = m["state"]
        # legal transitions only; no state is ever reopened
        if at == "MISSION_STARTED" and st == "CREATED":
            m["state"] = "STARTED"; m["started_seq"] = ev.seq
        elif at == "MISSION_COMPLETED" and st == "STARTED":
            m["state"] = "COMPLETED"; m["outcome"] = meta.get("outcome")
        elif at == "MISSION_CANCELLED" and st in ("CREATED", "STARTED"):
            m["state"] = "CANCELLED"
        elif at == "MISSION_EXPIRED" and st in ("CREATED", "STARTED"):
            m["state"] = "EXPIRED"
        # else: illegal transition → ignored (idempotent, no reopen)
    active = None
    for mid in order:
        if missions[mid]["state"] in ACTIVE_STATES:
            active = missions[mid]
    return {"missions": [missions[m] for m in order], "active": active}


# ── selection policies (interchangeable; the ONLY thing that varies) ──────────
def _eligible(payload: Dict[str, Any], view: Dict[str, Any]) -> List[Dict[str, Any]]:
    per = payload.get("per_concept", {})
    ret = view.get("retention", {})
    return [{"concept": c, "mastery": m.get("mastery", 0.0), "retention": ret.get(c, 1.0)}
            for c, m in per.items()]


def _rank_det(elig):
    # lowest mastery → highest retention urgency (lowest retention) → stable concept asc
    return sorted(elig, key=lambda x: (x["mastery"], x["retention"], x["concept"]))


def _rank_llm(elig):
    # STUB (not a real LLM) — deliberately DIFFERENT ordering to prove the ADR-007
    # contract is policy-agnostic: highest retention urgency first.
    return sorted(elig, key=lambda x: (x["retention"], x["mastery"], x["concept"]))


def _rank_det_11(elig):
    # det-1.1 — spaced-repetition-aware. ONE planning hypothesis, one behavioral
    # difference from det-1.0: "interrupt acquisition only when spaced repetition
    # says a review is genuinely due."
    #   if any concept is DUE (retention < RETENTION_DUE_THRESHOLD):
    #        choose among the DUE set
    #   else:
    #        fall back ENTIRELY to det-1.0
    # Within either pool the ranking key is IDENTICAL to det-1.0
    # (lowest mastery → highest retention urgency → stable concept_id), so the
    # gate is the sole variable — a clean, interpretable A/B.
    due = [e for e in elig if e["retention"] < RETENTION_DUE_THRESHOLD]
    pool = due if due else elig
    return sorted(pool, key=lambda x: (x["mastery"], x["retention"], x["concept"]))


def _select(policy: str, elig):
    if policy == POLICY_LLM:
        ranked = _rank_llm(elig)
    elif policy == POLICY_DET_11:
        ranked = _rank_det_11(elig)
    else:
        ranked = _rank_det(elig)
    return ranked[0]["concept"] if ranked else None


def question_count(db, concept_key) -> int:
    """THE single definition of 'answerable': servable-question count for a concept
    (strict concept_key match against the canonical vocabulary; no retired-label guessing).
    Used by the planner (creation guard), the API (stale-mission recovery), and mirrored by
    the runner's row retrieval. See docs/INVESTIGATION_mission_vocabulary.md."""
    if not concept_key:
        return 0
    import models
    return (db.query(models.Question.id)
              .filter(models.Question.concept_key == concept_key).count())


def is_answerable(db, concept_key) -> bool:
    return question_count(db, concept_key) > 0


def answerable_keys(db, keys) -> set:
    """Batch form of is_answerable: the subset of `keys` with >=1 servable question (one query)."""
    keys = [k for k in keys if k]
    if not keys:
        return set()
    import models
    rows = (db.query(models.Question.concept_key)
              .filter(models.Question.concept_key.in_(keys)).distinct().all())
    return {r[0] for r in rows}


def _answerable_only(db, elig):
    """Planner creation guard: keep only candidates that are is_answerable (one definition)."""
    ok = answerable_keys(db, [e["concept"] for e in elig if e.get("concept")])
    return [e for e in elig if e.get("concept") in ok]


# ── generator ────────────────────────────────────────────────────────────────
def generate(db, user_id: int, policy: str = POLICY_DET,
             mission_id: Optional[str] = None) -> Dict[str, Any]:
    """Create the next mission IFF no active mission exists (one-active-mission,
    ADR-007). Emits MISSION_CREATED; returns the outcome. Idempotent by
    construction: a second call with no learner change finds the active mission
    and creates nothing."""
    # Concurrency: on Postgres, serialise generation per user so two simultaneous
    # requests can't both pass the active-check (belt). Re-entrant with the event
    # bus's own per-user lock; released on commit.
    if db.bind.dialect.name == "postgresql":
        db.execute(_sql_text("SELECT pg_advisory_xact_lock(:k)"), {"k": int(user_id)})

    ms = mission_state(db, user_id)
    if ms["active"]:
        return {"created": False, "reason": "active_mission_exists", "active": ms["active"]}

    row = lp.get_or_build(db, user_id)
    payload = json.loads(row.payload or "{}")
    view = lp.read_view(payload)
    target = _select(policy, _answerable_only(db, _eligible(payload, view)))
    if not target:
        return {"created": False, "reason": "no_answerable_concept"}

    # Deterministic id from (user, mission_count-at-this-snapshot): concurrent
    # generate() calls that both observe "no active mission" compute the SAME
    # event_id ("miscreate-<mid>"), so the event bus's unique-event_id constraint
    # dedupes to exactly one MISSION_CREATED — the one-active-mission policy holds
    # even under simultaneous requests (MG-06). The count is A-invariant: it can't
    # change without a MISSION_CREATED committing, which the active-check would see.
    # (created_from_seq below still records the projection state for reproducibility.)
    mid = mission_id or ("m-%s-%s" % (user_id, len(ms["missions"])))
    steps = [{"kind": "practise", "concept": target, "n": DEFAULT_STEPS_N}]
    ev = {"event_id": "miscreate-" + mid, "module": "ai_marga",
          "activity_type": "MISSION_CREATED",
          "concept_ids": [target] if target else [],
          "metadata": {"mission_id": mid, "created_from_seq": row.last_seq,
                       "policy_version": policy, "steps": steps, "target": target}}
    res = le.ingest(db, user_id, [ev], valid_keys=le._valid_concept_keys(db))
    return {"created": res.get("accepted") == 1, "mission_id": mid, "target": target,
            "policy_version": policy, "created_from_seq": row.last_seq,
            "steps": steps, "ingest": res}


# ── lifecycle transitions (idempotent via deterministic event_ids) ───────────
def _emit(db, user_id, mission_id, activity, concept_ids=None, extra_meta=None):
    meta = {"mission_id": mission_id}
    if extra_meta:
        meta.update(extra_meta)
    prefix = {"MISSION_STARTED": "misstart-", "MISSION_COMPLETED": "miscomplete-",
              "MISSION_CANCELLED": "miscancel-", "MISSION_EXPIRED": "misexpire-"}[activity]
    ev = {"event_id": prefix + mission_id, "module": "ai_marga",
          "activity_type": activity, "concept_ids": concept_ids or [], "metadata": meta}
    return le.ingest(db, user_id, [ev], valid_keys=le._valid_concept_keys(db))


def _find(db, user_id, mission_id):
    return next((m for m in mission_state(db, user_id)["missions"]
                 if m["mission_id"] == mission_id), None)


def start(db, user_id, mission_id):
    m = _find(db, user_id, mission_id)
    if not m:
        return {"ok": False, "reason": "unknown_mission"}
    if m["state"] != "CREATED":
        return {"ok": False, "reason": "not_in_CREATED", "state": m["state"]}
    return {"ok": True, "ingest": _emit(db, user_id, mission_id, "MISSION_STARTED",
                                        concept_ids=m["target_concept_ids"])}


def cancel(db, user_id, mission_id, reason="cancelled"):
    m = _find(db, user_id, mission_id)
    if not m or m["state"] not in ACTIVE_STATES:
        return {"ok": False, "reason": "not_active"}
    return {"ok": True, "ingest": _emit(db, user_id, mission_id, "MISSION_CANCELLED",
                                        concept_ids=m["target_concept_ids"],
                                        extra_meta={"reason": reason})}


# ── completion evaluator ─────────────────────────────────────────────────────
def evaluate_completion(db, user_id: int) -> Dict[str, Any]:
    """A STARTED mission on concept C with n practise steps is COMPLETE when the
    learner has produced n MCQ_ATTEMPTED events tagged with C at/after the
    mission's MISSION_STARTED seq. Emits MISSION_COMPLETED idempotently. Mastery
    moved via the underlying MCQ_ATTEMPTED events — the mission records only."""
    m = mission_state(db, user_id)["active"]
    if not m or m["state"] != "STARTED":
        return {"completed": False, "reason": "no_started_mission"}
    target = (m["target_concept_ids"] or [None])[0]
    started = m.get("started_seq") or 0
    steps = m.get("steps") or [{"n": DEFAULT_STEPS_N}]
    need = steps[0].get("n", DEFAULT_STEPS_N)
    cnt = 0
    for ev in _all_events(db, user_id):
        if ev.seq <= started or ev.activity_type != "MCQ_ATTEMPTED":
            continue
        cids = json.loads(ev.concept_ids) if ev.concept_ids else []
        if target is None or target in cids:
            cnt += 1
    if cnt >= need:
        res = _emit(db, user_id, m["mission_id"], "MISSION_COMPLETED",
                    concept_ids=m["target_concept_ids"],
                    extra_meta={"outcome": {"attempts_on_target": cnt}})
        return {"completed": True, "attempts": cnt, "ingest": res}
    return {"completed": False, "attempts": cnt, "needed": need}


# ── view for Mission Control (current mission, thin) ─────────────────────────
def current_mission_view(db, user_id: int) -> Dict[str, Any]:
    ms = mission_state(db, user_id)
    a = ms["active"]
    return {"active": a,
            "completed": [m for m in ms["missions"] if m["state"] == "COMPLETED"][-5:]}
