"""
learner_events.py — ADR-003 Learning Event Bus (M1).

The single append-only write-path for all learner evidence. Every module emits
LearnerEvents here; nothing writes the Learner Projection directly.

Guarantees implemented:
  • Idempotency      — insert is a no-op on a repeated `event_id`.
  • Sequencing       — `seq` is server-assigned, monotonic and gap-free PER user
                       (Postgres: pg_advisory_xact_lock; any DB: retry on the
                       (user_id, seq) uniqueness constraint).
  • Validation       — required envelope fields, known schema_version, and
                       (STRICT_CONCEPTS) concept_ids that exist in the taxonomy.
  • Batch semantics  — per-event SAVEPOINTs so one bad event never rolls back the
                       whole batch; returns {accepted, duplicates, rejected[]}.
  • Replay           — fetch a user's events ordered by `seq` to rebuild any
                       projection (see `project`, the M2 seed).

This module is intentionally free of FastAPI/web concerns so it is unit-testable
against a plain SQLAlchemy session.
"""
from __future__ import annotations

import re
import json
import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError

# ── policy knobs ────────────────────────────────────────────────────────────
SUPPORTED_SCHEMA_VERSIONS = {1}
STRICT_CONCEPTS = True          # unknown concept_ids are rejected (ADR-004);
                                # set False to accept and flag under metadata._unknown_concepts
REQUIRED_FIELDS = ("event_id", "module", "activity_type")
_MAX_SEQ_RETRIES = 6


# ── concept-key normalisation (shared by producer AND seeder so they never drift) ─
_WS = re.compile(r"\s+")
def canon_concept_key(x):
    """Canonical form of a concept key: trim + collapse internal whitespace,
    case preserved. The MCQ producer and the topic seeder BOTH pass keys through
    this so a whitespace variant can never fragment mastery or break matching."""
    if x is None:
        return ""
    return _WS.sub(" ", str(x).strip())


# ── request normalisation ───────────────────────────────────────────────────
def normalize_payload(payload: Any) -> List[Dict[str, Any]]:
    """Accept a single event object or a batch ({"events":[...]} or a bare list)."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("events"), list):
            return [e for e in payload["events"] if isinstance(e, dict)]
        return [payload]
    return []


# ── helpers ─────────────────────────────────────────────────────────────────
def _valid_concept_keys(db) -> set:
    import models
    return {k for (k,) in db.query(models.ConceptInventory.key).all() if k}


def _next_seq(db, user_id: int) -> int:
    """Next monotonic seq for this user. On Postgres a per-user transaction-scoped
    advisory lock serialises concurrent writers; on other backends the caller's
    retry loop resolves the rare (user_id, seq) collision."""
    import models
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int(user_id)})
    cur = (db.query(func.coalesce(func.max(models.LearnerEvent.seq), 0))
           .filter(models.LearnerEvent.user_id == user_id).scalar())
    return int(cur or 0) + 1


def _parse_ts(v) -> Optional[datetime.datetime]:
    if not v:
        return None
    try:
        return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _exists(db, event_id: str) -> bool:
    import models
    return db.query(models.LearnerEvent.id).filter(
        models.LearnerEvent.event_id == event_id).first() is not None


# ── ingest ──────────────────────────────────────────────────────────────────
def ingest(db, user_id: int, events: List[Dict[str, Any]],
           valid_keys: Optional[set] = None) -> Dict[str, Any]:
    """Append events for `user_id`. Idempotent, ordered, validated. Does NOT
    commit — the caller commits (so the whole request is one transaction)."""
    import models
    if valid_keys is None and STRICT_CONCEPTS:
        valid_keys = _valid_concept_keys(db)
    accepted = 0
    duplicates = 0
    rejected: List[Dict[str, Any]] = []

    for e in events:
        eid = (e or {}).get("event_id")

        # 1) envelope validation
        missing = [f for f in REQUIRED_FIELDS if not e.get(f)]
        if missing:
            rejected.append({"event_id": eid, "reason": "missing fields: " + ",".join(missing)})
            continue

        # 2) schema version (additive-only; unknown/newer-breaking is rejected)
        sv = e.get("schema_version", 1)
        if sv not in SUPPORTED_SCHEMA_VERSIONS:
            rejected.append({"event_id": eid, "reason": "unsupported schema_version %r" % sv})
            continue

        # 3) idempotency — duplicate event_id is a no-op (also dedupes within a batch)
        if _exists(db, eid):
            duplicates += 1
            continue

        # 4) concept validation (ADR-004)
        cids = e.get("concept_ids") or []
        meta = e.get("metadata")
        if cids and STRICT_CONCEPTS:
            unknown = [c for c in cids if c not in valid_keys]
            if unknown:
                rejected.append({"event_id": eid, "reason": "unknown concept_ids: %s" % unknown})
                continue
        elif cids and not STRICT_CONCEPTS:
            unknown = [c for c in cids if c not in (valid_keys or set())]
            if unknown:
                meta = dict(meta or {})
                meta["_unknown_concepts"] = unknown

        # 5) assign seq + insert, retrying on seq contention (not on dup event_id)
        inserted = False
        for _ in range(_MAX_SEQ_RETRIES):
            seq = _next_seq(db, user_id)
            row = models.LearnerEvent(
                event_id=eid, user_id=user_id, seq=seq,
                ts_client=_parse_ts(e.get("timestamp")),
                module=e.get("module"), activity_type=e.get("activity_type"),
                concept_ids=json.dumps(cids) if cids else None,
                topic_ids=json.dumps(e.get("topic_ids")) if e.get("topic_ids") else None,
                duration=e.get("duration"), score=e.get("score"),
                confidence=e.get("confidence"), schema_version=sv,
                meta=json.dumps(meta) if meta is not None else None,
            )
            try:
                with db.begin_nested():
                    db.add(row)
                    db.flush()
                accepted += 1
                inserted = True
                break
            except IntegrityError:
                # event_id race → duplicate; otherwise a seq collision → retry
                if _exists(db, eid):
                    duplicates += 1
                    inserted = True
                    break
                db.expire_all()
                continue
        if not inserted:
            rejected.append({"event_id": eid, "reason": "sequence contention"})

    return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


# ── replay ──────────────────────────────────────────────────────────────────
def fetch_events(db, user_id: int, after_seq: int = 0, limit: int = 1000):
    import models
    return (db.query(models.LearnerEvent)
            .filter(models.LearnerEvent.user_id == user_id,
                    models.LearnerEvent.seq > after_seq)
            .order_by(models.LearnerEvent.seq.asc())
            .limit(limit).all())


def to_dict(ev) -> Dict[str, Any]:
    return {
        "event_id": ev.event_id, "seq": ev.seq, "user_id": ev.user_id,
        "module": ev.module, "activity_type": ev.activity_type,
        "concept_ids": json.loads(ev.concept_ids) if ev.concept_ids else [],
        "topic_ids": json.loads(ev.topic_ids) if ev.topic_ids else [],
        "duration": ev.duration, "score": ev.score, "confidence": ev.confidence,
        "schema_version": ev.schema_version,
        "metadata": json.loads(ev.meta) if ev.meta else {},
        "timestamp": ev.ts_client.isoformat() if ev.ts_client else None,
        "ingested_at": ev.ingested_at.isoformat() if ev.ingested_at else None,
    }


# ── projection (M2 seed) ─────────────────────────────────────────────────────
# A deterministic fold of the event stream into a minimal Learner Projection.
# Pure function of (events) — no wall-clock, no RNG — so replay is reproducible
# and incremental application equals a full rebuild. The full ADR-001 projection
# (retention decay, readiness) lands in M2; this seed proves the invariant.
def _reduce(state: Dict[str, Any], ev: Dict[str, Any]) -> None:
    state["n"] += 1
    at = ev.get("activity_type")
    state["counts"][at] = state["counts"].get(at, 0) + 1
    if at in ("MCQ_ATTEMPTED", "ANSWER_EVALUATED"):
        correct = 1 if (ev.get("score") or 0) > 0 else 0
        for c in (ev.get("concept_ids") or []):
            m = state["per_concept"].get(c) or {"attempts": 0, "correct": 0, "mastery": 0.0}
            m["attempts"] += 1
            m["correct"] += correct
            m["mastery"] = round(m["correct"] / m["attempts"], 4)
            state["per_concept"][c] = m


def new_state() -> Dict[str, Any]:
    return {"n": 0, "counts": {}, "per_concept": {}}


def project(events: List[Dict[str, Any]], state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fold events (dicts, in seq order) into projection state. Deterministic."""
    st = state if state is not None else new_state()
    for ev in events:
        _reduce(st, ev)
    return st


def emit(db, user_id, event, payload, valid_keys=None):
    """Producer-facing emit (M7 dependency reversal). Producers pass an authoritative
    events_registry.Event plus a payload WITHOUT `activity_type`; the migration bridge
    (canonical id -> stored activity_type) lives HERE, once. When storage migrates to
    the dotted id, flip `event.legacy or event.id` to `event.id` and no producer changes.
    Thin wrapper over ingest(): identical idempotency / validation / best-effort semantics."""
    envelope = dict(payload)
    envelope["activity_type"] = event.legacy or event.id
    return ingest(db, user_id, [envelope], valid_keys=valid_keys)
