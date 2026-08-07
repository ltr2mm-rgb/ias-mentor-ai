"""
mission_outcome.py — Mission Outcome projection (M5 Phase A, measurement only).

The evaluation layer's foundation: one **MissionOutcome** derived per mission from
the MISSION_* + MCQ_ATTEMPTED event streams (ADR-005/007), plus a deterministic
aggregation of those outcomes by `policy_version`. This is Phase A — outcomes and
aggregation ONLY. No scorecard, no promotion decision, no confidence intervals:
those consume this projection in later Phase-A steps once it is trusted.

Design invariants (why the evaluator can be trusted, mirroring M2):
  • PURE fold — the reducer depends only on (state, event) in `seq` order. No DB
    writes inside the fold, no HTTP/AI, no RNG, and NO wall-clock. The only times
    used are event-carried `seq`s (elapsed is a seq-span, not a clock reading).
  • Therefore the STORED payload is time-invariant, so an incremental update
    always equals a full rebuild from seq 0 (EQ-01), exactly as LearnerProjection
    guarantees for learner state (PR-01/02 / MG-04).
  • Aggregation groups strictly by the `policy_version` each MISSION_CREATED
    stamped; it is commutative (sums, then averages) so it is order-independent
    and deterministic (EQ-02).
  • Retention/other time-relative deltas are NOT stored here — they are read-time
    views (M2 `read_view` discipline) and never enter replay equality.

`outcome_version` is the reducer-algorithm version, independent of the event
`schema_version`; bumping it forces a rebuild without editing any event.

The module is free of FastAPI/web concerns so it is unit-testable against a plain
SQLAlchemy session, like learner_events / learner_projection / mission_engine.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import learner_events as le
import learner_projection as lp

OUTCOME_VERSION = "outcome-1.0"

MISSION_ACTIVITIES = ("MISSION_CREATED", "MISSION_STARTED", "MISSION_COMPLETED",
                      "MISSION_CANCELLED", "MISSION_EXPIRED")
_TERMINAL = ("COMPLETED", "CANCELLED", "EXPIRED")


# ── the accumulation state (fully captures the fold, so it can be persisted) ──
def new_state() -> Dict[str, Any]:
    return {
        "learner": lp.new_state(),   # running per-concept mastery accumulator (M2 reducer)
        "missions": {},              # mission_id -> outcome-in-progress (see _blank_outcome)
        "order": [],                 # mission_ids in creation order (stable output order)
    }


def _blank_outcome(mid: str) -> Dict[str, Any]:
    return {
        "mission_id": mid,
        "policy_version": None,
        "target": None,
        "created_from_seq": None,   # projection seq at creation (reproducibility)
        "created_seq": None,        # seq of the MISSION_CREATED event
        "started_seq": None,        # seq of the MISSION_STARTED event
        "terminal_seq": None,       # seq of the terminal MISSION_* event
        "state": "CREATED",
        "completed": False,
        "attempts_on_target": 0,    # concept-tagged MCQ attempts during the started mission
        "mastery_before": None,     # target mastery as of created_from_seq (deterministic)
        "mastery_after": None,      # target mastery at the terminal event (deterministic)
        "mastery_gain": None,       # after - before (None until a terminal state with a target)
        "elapsed_seq": None,        # terminal_seq - started_seq (seq-span, NOT wall-clock)
    }


def _target_mastery(learner_state: Dict[str, Any], target: Optional[str]) -> Optional[float]:
    if not target:
        return None
    m = learner_state.get("per_concept", {}).get(target)
    return float(m["mastery"]) if m else 0.0


def _active_started(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The single mission currently in STARTED (≤1 by ADR-007), latest by order."""
    found = None
    for mid in state["order"]:
        o = state["missions"][mid]
        if o["state"] == "STARTED":
            found = o
    return found


# ── pure reducer — fold ONE event (learner + mission streams share the bus) ──
def reduce(state: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    at = ev.get("activity_type")
    seq = ev.get("seq")

    if at == "MCQ_ATTEMPTED":
        # attribute the attempt to an active started mission BEFORE advancing
        # learner mastery, so counting and mastery use the same event exactly once.
        act = _active_started(state)
        if act is not None and (seq is None or act["started_seq"] is None or seq > act["started_seq"]):
            tgt = act["target"]
            cids = ev.get("concept_ids") or []
            if tgt is None or tgt in cids:
                act["attempts_on_target"] += 1
        lp.reduce(state["learner"], ev)          # advance running mastery
        return state

    if at not in MISSION_ACTIVITIES:
        # any other learner activity still advances mastery (keeps before/after honest)
        lp.reduce(state["learner"], ev)
        return state

    meta = ev.get("metadata") or {}
    mid = meta.get("mission_id")
    if not mid:
        return state

    if at == "MISSION_CREATED":
        if mid not in state["missions"]:
            o = _blank_outcome(mid)
            o["policy_version"] = meta.get("policy_version")
            cids = ev.get("concept_ids") or []
            o["target"] = meta.get("target") if meta.get("target") is not None else (cids[0] if cids else None)
            o["created_from_seq"] = meta.get("created_from_seq")
            o["created_seq"] = seq
            # mastery_before = target mastery as of created_from_seq. The learner
            # accumulator here reflects every event with seq < this MISSION_CREATED
            # (which is created_from_seq + 1), i.e. exactly the creation snapshot.
            o["mastery_before"] = _target_mastery(state["learner"], o["target"])
            state["missions"][mid] = o
            state["order"].append(mid)
        return state

    o = state["missions"].get(mid)
    if not o:
        return state                              # transition for unknown mission — ignore
    st = o["state"]
    # legal transitions only; a terminal state is never reopened (idempotent)
    if at == "MISSION_STARTED" and st == "CREATED":
        o["state"] = "STARTED"; o["started_seq"] = seq
    elif at == "MISSION_COMPLETED" and st == "STARTED":
        o["state"] = "COMPLETED"; o["completed"] = True; o["terminal_seq"] = seq
        o["mastery_after"] = _target_mastery(state["learner"], o["target"])
        if o["mastery_before"] is not None and o["mastery_after"] is not None:
            o["mastery_gain"] = round(o["mastery_after"] - o["mastery_before"], 4)
        if o["started_seq"] is not None and seq is not None:
            o["elapsed_seq"] = seq - o["started_seq"]
    elif at == "MISSION_CANCELLED" and st in ("CREATED", "STARTED"):
        o["state"] = "CANCELLED"; o["terminal_seq"] = seq
    elif at == "MISSION_EXPIRED" and st in ("CREATED", "STARTED"):
        o["state"] = "EXPIRED"; o["terminal_seq"] = seq
    # else: illegal transition → ignored
    return state


def outcomes(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The list of MissionOutcomes in stable creation order — one per mission."""
    return [dict(state["missions"][mid]) for mid in state["order"]]


def materialized(state: Dict[str, Any]) -> Dict[str, Any]:
    """The stored, deterministic projection payload.

    `_acc_learner` is the running learner-mastery accumulator AS OF this
    projection's `last_seq` — persisted so an incremental resume co-folds mastery
    from the exact same point the outcomes stopped, never from a learner state at
    a different seq. It is internal accumulation state (like LearnerProjection's
    per_concept), not part of the outcomes artifact; consumers read `outcomes`."""
    ls = state["learner"]
    return {
        "outcomes": outcomes(state),
        "count": len(state["order"]),
        "outcome_version": OUTCOME_VERSION,
        "_acc_learner": {
            "n": ls.get("n", 0),
            "counts": dict(ls.get("counts", {})),
            "per_concept": {k: dict(v) for k, v in ls.get("per_concept", {}).items()},
        },
    }


def _state_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Recover the FULL accumulation state for incremental continuation, entirely
    from our own stored payload: outcomes (mission accumulators) + `_acc_learner`
    (the mastery accumulator at the same seq). Self-contained → exact resume."""
    st = new_state()
    la = payload.get("_acc_learner") or {}
    st["learner"] = {
        "n": la.get("n", 0),
        "counts": dict(la.get("counts", {})),
        "per_concept": {k: dict(v) for k, v in la.get("per_concept", {}).items()},
    }
    for o in payload.get("outcomes", []):
        st["missions"][o["mission_id"]] = dict(o)
        st["order"].append(o["mission_id"])
    return st


def project(events: List[Dict[str, Any]], state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fold event dicts (in seq order) into the accumulation state. Deterministic."""
    st = state if state is not None else new_state()
    for ev in events:
        reduce(st, ev)
    return st


# ── materialisation service (DB) — incremental, with a full-rebuild path ─────
def get_or_build(db, user_id: int, rebuild: bool = False, batch: int = 2000):
    """Return the up-to-date MissionOutcomeProjection row, materialising
    incrementally from the last folded seq. `rebuild=True` or a version change
    forces a full rebuild from seq 0. Deterministic: incremental == full rebuild
    (EQ-01). The learner accumulator is co-folded so mastery_before/after are
    exact snapshots without a second pass."""
    import models
    row = (db.query(models.MissionOutcomeProjection)
           .filter(models.MissionOutcomeProjection.user_id == user_id).one_or_none())

    stale = (row is not None and row.outcome_version != OUTCOME_VERSION)
    if row is None:
        row = models.MissionOutcomeProjection(
            user_id=user_id, last_seq=0, outcome_version=OUTCOME_VERSION,
            payload=json.dumps(materialized(new_state())))
        db.add(row)

    if rebuild or stale or not row.payload:
        state = new_state()
        after = 0
    else:
        # resume entirely from our OWN payload (outcomes + `_acc_learner`), so the
        # mastery accumulator continues from the exact seq the outcomes stopped at.
        state = _state_from_payload(json.loads(row.payload))
        after = int(row.last_seq or 0)

    last = after
    while True:
        evs = le.fetch_events(db, user_id, after_seq=last, limit=batch)
        if not evs:
            break
        for ev in evs:
            reduce(state, le.to_dict(ev))
            last = ev.seq
        if len(evs) < batch:
            break

    row.last_seq = last
    row.outcome_version = OUTCOME_VERSION
    row.payload = json.dumps(materialized(state))
    db.flush()
    return row


def rebuild_from_replay(db, user_id: int) -> Dict[str, Any]:
    """Full rebuild straight from the event log (recovery / validation path).
    Returns the materialised payload WITHOUT persisting — used to prove a deleted
    projection is reconstructable and identical (EQ-01)."""
    state = new_state()
    last = 0
    while True:
        evs = le.fetch_events(db, user_id, after_seq=last, limit=2000)
        if not evs:
            break
        for ev in evs:
            reduce(state, le.to_dict(ev))
            last = ev.seq
        if len(evs) < 2000:
            break
    return materialized(state)


# ── aggregation by policy_version (EQ-02) — deterministic, order-independent ──
def aggregate_by_policy(outcome_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Group MissionOutcomes by `policy_version` and compute per-policy summary
    stats. Commutative reduction (sums first, averages last) so the result does
    not depend on input order. Output keys are sorted for a stable artifact.

    Phase A reports counts + the deterministic per-mission measures only. The
    scorecard, promotion decision, and confidence intervals are later Phase-A
    steps that consume this aggregate — they are deliberately NOT computed here."""
    groups: Dict[str, Dict[str, Any]] = {}
    for o in outcome_list:
        pol = o.get("policy_version") or "unknown"
        g = groups.setdefault(pol, {
            "policy_version": pol, "missions": 0, "completed": 0, "cancelled": 0,
            "expired": 0, "_gain_sum": 0.0, "_gain_n": 0,
            "_attempts_sum": 0, "_elapsed_sum": 0, "_elapsed_n": 0,
        })
        g["missions"] += 1
        state = o.get("state")
        if state == "COMPLETED":
            g["completed"] += 1
        elif state == "CANCELLED":
            g["cancelled"] += 1
        elif state == "EXPIRED":
            g["expired"] += 1
        if o.get("mastery_gain") is not None:
            g["_gain_sum"] += float(o["mastery_gain"]); g["_gain_n"] += 1
        g["_attempts_sum"] += int(o.get("attempts_on_target") or 0)
        if o.get("elapsed_seq") is not None:
            g["_elapsed_sum"] += int(o["elapsed_seq"]); g["_elapsed_n"] += 1

    out: Dict[str, Any] = {}
    for pol in sorted(groups):
        g = groups[pol]
        n = g["missions"]
        out[pol] = {
            "policy_version": pol,
            "missions": n,
            "completed": g["completed"],
            "cancelled": g["cancelled"],
            "expired": g["expired"],
            "completion_rate": round(g["completed"] / n, 4) if n else None,
            "avg_mastery_gain": round(g["_gain_sum"] / g["_gain_n"], 4) if g["_gain_n"] else None,
            "avg_attempts_on_target": round(g["_attempts_sum"] / n, 4) if n else None,
            "avg_elapsed_seq": round(g["_elapsed_sum"] / g["_elapsed_n"], 4) if g["_elapsed_n"] else None,
        }
    return out
