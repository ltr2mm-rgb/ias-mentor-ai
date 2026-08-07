"""
learner_projection.py — ADR-001 Learner Projection (M2).

Materialises the learner's current state from the LearnerEvent stream (ADR-003).
The projection is a DERIVED read-model, never a source of truth: deleting it and
replaying the events reconstructs an identical `payload`.

Design invariants (what makes replay trustworthy):
  • Reducers are PURE — reduce(state, event) depends only on (state, event).
    No DB writes, no HTTP, no AI, no randomness, and no wall-clock: the only
    timestamps used are the ones carried by the event (ts/ingested_at).
  • The STORED payload is therefore time-invariant, so a full rebuild always
    equals an incremental update (PR-01/02).
  • Time-relative views (retention "as of now", revision due-dates) are derived
    at READ time in `read_view()`, NOT stored — so they never break replay.

`projection_version` is the reducer-algorithm version, independent of the event
`schema_version`. Bumping it forces a rebuild without editing any event, which is
how future models (BKT, IRT, new retention curves) roll out.
"""
from __future__ import annotations

import json
import math
import datetime
from typing import Any, Dict, List, Optional

# learner_events imported lazily inside get_or_build/rebuild_from_replay (keeps this pure-reducer module importable without the DB stack)

PROJECTION_VERSION = "proj-1.0"

# concepts scored by these activities contribute to mastery
_MASTERY_ACTIVITIES = ("MCQ_ATTEMPTED", "ANSWER_EVALUATED", "REVISION_COMPLETED")
# retention half-life (days) used only at read time
_RETENTION_HALFLIFE_DAYS = 10.0


# ── pure reducers ────────────────────────────────────────────────────────────
def new_state() -> Dict[str, Any]:
    return {"n": 0, "counts": {}, "per_concept": {}}


def reduce(state: Dict[str, Any], ev: Dict[str, Any]) -> Dict[str, Any]:
    """Fold one event into the state. Pure: (state, event) -> state'."""
    state["n"] = state.get("n", 0) + 1
    at = ev.get("activity_type")
    counts = state.setdefault("counts", {})
    counts[at] = counts.get(at, 0) + 1

    # BASELINE_ESTABLISHED: a producer-agnostic evidence event (diagnostic today; an
    # adaptive CAT or imported history tomorrow). Its payload carries concept -> mastery,
    # already resolved by the producer's translator; this reducer only APPLIES evidence and
    # never learns where it came from. Baseline is a FLOOR: it seeds mastery only for
    # concepts with no attempt-backed evidence yet, so real attempts always win.
    if at == "BASELINE_ESTABLISHED":
        seq = ev.get("seq")
        ts = ev.get("timestamp") or ev.get("ingested_at")
        for c, mval in ((ev.get("metadata") or {}).get("concepts") or {}).items():
            m = state["per_concept"].get(c) or {
                "attempts": 0, "correct": 0, "mastery": 0.0,
                "last_seq": None, "last_ts": None,
            }
            if m.get("attempts", 0) == 0:
                m["mastery"] = round(float(mval), 4)
            m["last_seq"] = seq
            if ts:
                m["last_ts"] = ts
            state["per_concept"][c] = m
        return state

    if at in _MASTERY_ACTIVITIES:
        correct = 1 if (ev.get("score") or 0) > 0 else 0
        seq = ev.get("seq")
        ts = ev.get("timestamp") or ev.get("ingested_at")   # event-carried only
        for c in (ev.get("concept_ids") or []):
            m = state["per_concept"].get(c) or {
                "attempts": 0, "correct": 0, "mastery": 0.0,
                "last_seq": None, "last_ts": None,
            }
            m["attempts"] += 1
            m["correct"] += correct
            m["mastery"] = round(m["correct"] / m["attempts"], 4)
            m["last_seq"] = seq
            if ts:
                m["last_ts"] = ts
            state["per_concept"][c] = m
    return state


# ── deterministic derived summary (no time) ──────────────────────────────────
def _derive_readiness(state: Dict[str, Any]) -> Dict[str, Any]:
    pcs = state.get("per_concept", {})
    if not pcs:
        return {"value": None, "coverage": 0}
    masteries = [c["mastery"] for c in pcs.values()]
    return {"value": round(100.0 * sum(masteries) / len(masteries), 1),
            "coverage": len(pcs)}


def _derive_growth_lever(state: Dict[str, Any]) -> Dict[str, Any]:
    pcs = state.get("per_concept", {})
    if not pcs:
        return {"concept": None, "mastery": None}
    concept, m = min(pcs.items(), key=lambda kv: (kv[1]["mastery"], kv[0]))
    return {"concept": concept, "mastery": m["mastery"]}


def materialized(state: Dict[str, Any]) -> Dict[str, Any]:
    """The stored, deterministic projection payload (state + derived summary)."""
    return {
        "n": state.get("n", 0),
        "counts": dict(state.get("counts", {})),
        "per_concept": {k: dict(v) for k, v in state.get("per_concept", {}).items()},
        "readiness": _derive_readiness(state),
        "growth_lever": _derive_growth_lever(state),
        "projection_version": PROJECTION_VERSION,
    }


def _state_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Recover the raw accumulation state (for incremental continuation)."""
    return {
        "n": payload.get("n", 0),
        "counts": dict(payload.get("counts", {})),
        "per_concept": {k: dict(v) for k, v in payload.get("per_concept", {}).items()},
    }


def project(events: List[Dict[str, Any]], state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fold a list of event dicts (in seq order) into accumulation state."""
    st = state if state is not None else new_state()
    for ev in events:
        reduce(st, ev)
    return st


# ── materialisation service (DB) ─────────────────────────────────────────────
def get_or_build(db, user_id: int, rebuild: bool = False, batch: int = 2000):
    """Return the up-to-date LearnerProjection row for a user, materialising
    incrementally from the last folded seq. A version change or `rebuild=True`
    forces a full rebuild from seq 0. Deterministic: full rebuild == incremental."""
    import models
    import learner_events as le
    row = (db.query(models.LearnerProjection)
           .filter(models.LearnerProjection.user_id == user_id).one_or_none())

    stale_version = (row is not None and row.projection_version != PROJECTION_VERSION)
    if row is None:
        row = models.LearnerProjection(user_id=user_id, last_seq=0,
                                       projection_version=PROJECTION_VERSION,
                                       payload=json.dumps(materialized(new_state())))
        db.add(row)

    if rebuild or stale_version or not row.payload:
        state = new_state()
        after = 0
    else:
        state = _state_from_payload(json.loads(row.payload))
        after = int(row.last_seq or 0)

    # incremental replay of everything newer than `after`
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
    row.projection_version = PROJECTION_VERSION
    row.payload = json.dumps(materialized(state))
    db.flush()
    return row


def rebuild_from_replay(db, user_id: int) -> Dict[str, Any]:
    """Full rebuild straight from the event log (recovery / validation path).
    Returns the materialised payload WITHOUT persisting — used to prove that a
    deleted projection is reconstructable and identical."""
    import learner_events as le
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


# ── read-time view (time-relative; NOT stored, NOT part of replay equality) ──
def _retention(mastery: float, days_since: Optional[float]) -> float:
    if days_since is None:
        return round(mastery, 4)
    decay = math.pow(0.5, days_since / _RETENTION_HALFLIFE_DAYS)
    return round(mastery * decay, 4)


def read_view(payload: Dict[str, Any], now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """Enrich the stored payload with time-relative fields (retention as of now,
    revision schedule). Computed at serve time; never persisted."""
    now = now or datetime.datetime.utcnow()
    retention = {}
    schedule = []
    for c, m in (payload.get("per_concept") or {}).items():
        days = None
        if m.get("last_ts"):
            try:
                last = datetime.datetime.fromisoformat(str(m["last_ts"]).replace("Z", "+00:00")).replace(tzinfo=None)
                days = max(0.0, (now - last).total_seconds() / 86400.0)
            except Exception:
                days = None
        ret = _retention(m.get("mastery", 0.0), days)
        retention[c] = ret
        schedule.append({"concept": c, "retention": ret,
                         "due": "today" if ret < 0.6 else "soon" if ret < 0.75 else "later"})
    schedule.sort(key=lambda r: r["retention"])
    return {**payload, "retention": retention, "revision_schedule": schedule}
