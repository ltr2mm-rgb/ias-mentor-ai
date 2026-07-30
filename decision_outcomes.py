"""
decision_outcomes.py — the evidence architecture for decisions (review
recommendation: "for every recommendation, create a Decision Outcome record").

Turns every recommendation into a supervised-learning example:

    Decision (now)                          Outcome (horizon later)
    ─────────────────                       ────────────────────────
    action, target, reason,        →        executed?  readiness_change
    expected_gain, engine_version           actual_gain  learner_rating

So the Decision Engine can eventually answer with evidence — "learners like you
gained +3.2 readiness by revising first, only +1.1 by starting a new chapter" —
instead of relying on hand-written rules forever. This module only RECORDS and
SETTLES; it never decides.

Two calls:
  • open_decision(db, user_id, decision, baseline_readiness)  — log a recommendation
  • settle_decisions(db, user_id, now)  — close matured decisions into outcomes

`settle` is idempotent and cheap; call it opportunistically each pipeline run (and/
or from a daily job). It never fabricates data: readiness_change is only filled
when a post-decision readiness reading exists.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

DEFAULT_HORIZON_HOURS = 24


def open_decision(db, user_id: int, decision: Dict[str, Any],
                  baseline_readiness: Optional[float],
                  horizon_hours: int = DEFAULT_HORIZON_HOURS,
                  versions: Optional[Dict[str, str]] = None,
                  experiment_id: Optional[int] = None,
                  now: Optional[datetime.datetime] = None) -> Optional[int]:
    """Persist a recommendation as a DecisionRecord. `versions` stamps the exact
    engine/prediction/profile/explanation/planner versions and `experiment_id` the
    A/B arm, so the recommendation is fully reproducible months later. Returns its
    id (or None on failure — never raises into the caller's pipeline)."""
    import models
    try:
        primary = (decision or {}).get("primary", {}) or {}
        v = versions or {}
        rec = models.DecisionRecord(
            user_id=user_id,
            action=primary.get("action"),
            target=primary.get("target"),
            target_key=primary.get("target_key"),
            reason=(decision or {}).get("reason"),
            expected_gain=(primary.get("expected_impact") or {}).get("readiness_delta"),
            engine_version=(decision or {}).get("engine_version"),
            prediction_version=v.get("prediction_version"),
            profile_version=v.get("profile_version"),
            explanation_version=v.get("explanation_version"),
            planner_version=v.get("planner_version"),
            experiment_id=experiment_id,
            baseline_readiness=baseline_readiness,
            horizon_hours=horizon_hours,
            settled=False,
            created_at=now or datetime.datetime.utcnow(),
        )
        db.add(rec)
        db.commit()
        return rec.id
    except Exception:
        db.rollback()
        return None


def run_settlement_cycle(db, now: Optional[datetime.datetime] = None,
                         horizon_hours: Optional[int] = None) -> Dict[str, Any]:
    """Settle matured decisions for EVERY learner with open decisions — the
    scheduled counterpart to opportunistic per-request settlement. Idempotent
    (the `settled` flag guards re-settling), so it is safe to run hourly and keeps
    analytics fresh even when learners are inactive. Returns a run summary."""
    import models
    now = now or datetime.datetime.utcnow()
    try:
        user_ids = [row[0] for row in
                    db.query(models.DecisionRecord.user_id)
                    .filter(models.DecisionRecord.settled == False)  # noqa: E712
                    .distinct().all()]
    except Exception:
        return {"users_scanned": 0, "settled": 0, "error": "query failed"}
    settled_total = 0
    for uid in user_ids:
        settled_total += len(settle_decisions(db, uid, now, horizon_hours))
    return {"users_scanned": len(user_ids), "settled": settled_total,
            "ran_at": now.isoformat()}


def settle_decisions(db, user_id: int, now: Optional[datetime.datetime] = None,
                     horizon_hours: Optional[int] = None) -> List[int]:
    """Close every matured, unsettled decision into a DecisionOutcome. Returns the
    list of decision ids settled this call."""
    import models
    now = now or datetime.datetime.utcnow()
    settled: List[int] = []
    try:
        open_recs = (db.query(models.DecisionRecord)
                     .filter(models.DecisionRecord.user_id == user_id,
                             models.DecisionRecord.settled == False)  # noqa: E712
                     .all())
    except Exception:
        return settled

    for rec in open_recs:
        horizon = horizon_hours if horizon_hours is not None else (rec.horizon_hours or DEFAULT_HORIZON_HOURS)
        if rec.created_at and (now - rec.created_at) < datetime.timedelta(hours=horizon):
            continue                      # not matured yet

        # readiness AFTER the decision (first reading strictly after it)
        after = (db.query(models.PredictionHistory)
                 .filter(models.PredictionHistory.user_id == user_id,
                         models.PredictionHistory.metric == "readiness",
                         models.PredictionHistory.created_at > rec.created_at)
                 .order_by(models.PredictionHistory.id.desc()).first())
        readiness_change = None
        if after and after.value not in (None, "") and rec.baseline_readiness is not None:
            try:
                readiness_change = round(float(after.value) - float(rec.baseline_readiness), 1)
            except (TypeError, ValueError):
                readiness_change = None

        # executed? — did the learner touch this concept after the recommendation?
        executed = False
        if rec.target_key:
            executed = bool(db.query(models.ConceptAttempt)
                            .filter(models.ConceptAttempt.user_id == user_id,
                                    models.ConceptAttempt.concept_key == rec.target_key,
                                    models.ConceptAttempt.created_at > rec.created_at)
                            .first())

        try:
            db.add(models.DecisionOutcome(
                decision_id=rec.id, user_id=user_id, executed=executed,
                completion_rate=None,
                readiness_change=readiness_change,
                retention_change=None,
                learner_rating=None,
                actual_gain=readiness_change,          # the supervised label
                created_at=now))
            rec.settled = True
            db.commit()
            settled.append(rec.id)
        except Exception:
            db.rollback()
    return settled


def rate_decision(db, user_id: int, decision_id: int, rating: int) -> bool:
    """Attach a learner rating (1-5) to a decision's outcome (creating a partial
    outcome row if it hasn't settled yet). Optional signal for the eventual model."""
    import models
    try:
        out = (db.query(models.DecisionOutcome)
               .filter(models.DecisionOutcome.decision_id == decision_id,
                       models.DecisionOutcome.user_id == user_id).first())
        if out is None:
            out = models.DecisionOutcome(decision_id=decision_id, user_id=user_id,
                                         created_at=datetime.datetime.utcnow())
            db.add(out)
        out.learner_rating = int(rating)
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
