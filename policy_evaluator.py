"""
policy_evaluator.py — the Policy Evaluator (AIVORA OS, arch v1.4; review
recommendation "add a Policy Evaluator before any ML").

    Decision → Outcome → POLICY EVALUATOR → Engine Metrics

Read-only analytics over the evidence store (DecisionRecord ⋈ DecisionOutcome).
It **recommends nothing** and mutates nothing — it answers questions about how the
Decision Engine's own recommendations performed, so the engine can later be
improved from observed behavior instead of intuition:

  • Which recommendation types have the highest completion rate?
  • Which recommendations actually improve readiness (avg gain)?
  • Which are ignored?
  • How well-calibrated are the engine's *expected* gains vs. *actual*?
  • How do two policy versions (decision-v1.3 vs v1.4) compare? (A/B)

The last one is why every DecisionRecord carries `engine_version`: policies are
treated as experiments. Nothing here trains a model — it produces the metrics that
would justify (or refute) doing so later.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple


def _agg(pairs: List[Tuple[Any, Any]]) -> Dict[str, Any]:
    """Aggregate a list of (DecisionRecord, DecisionOutcome) into a metrics row."""
    n = len(pairs)
    executed_known = [o for _, o in pairs if o.executed is not None]
    executed = sum(1 for o in executed_known if o.executed)
    gains = [o.actual_gain for _, o in pairs if o.actual_gain is not None]
    expected = [d.expected_gain for d, _ in pairs if d.expected_gain is not None]
    ratings = [o.learner_rating for _, o in pairs if o.learner_rating is not None]

    avg_gain = round(sum(gains) / len(gains), 2) if gains else None
    avg_expected = round(sum(expected) / len(expected), 2) if expected else None
    return {
        "n": n,
        "completion_rate": round(executed / len(executed_known), 2) if executed_known else None,
        "ignored_rate": round(1 - executed / len(executed_known), 2) if executed_known else None,
        "avg_readiness_gain": avg_gain,
        "avg_expected_gain": avg_expected,
        # calibration: how far the hand-written expected gains sit from reality
        # (this is the number that later justifies replacing heuristics with learned estimates)
        "gain_vs_expected": (round(avg_gain - avg_expected, 2)
                             if (avg_gain is not None and avg_expected is not None) else None),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
    }


def metrics(db, since: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """Engine metrics from settled decisions. Empty-safe (returns zeros/None)."""
    import models
    q = (db.query(models.DecisionRecord, models.DecisionOutcome)
         .join(models.DecisionOutcome, models.DecisionOutcome.decision_id == models.DecisionRecord.id))
    pairs = [(d, o) for d, o in q.all() if (since is None or (d.created_at and d.created_at >= since))]

    by_action: Dict[str, List] = defaultdict(list)
    by_policy: Dict[str, List] = defaultdict(list)
    by_experiment: Dict[str, List] = defaultdict(list)
    for d, o in pairs:
        by_action[d.action or "unknown"].append((d, o))
        by_policy[d.engine_version or "unknown"].append((d, o))
        by_experiment[str(d.experiment_id) if d.experiment_id else "none"].append((d, o))

    total = db.query(models.DecisionRecord).count()
    settled = db.query(models.DecisionRecord).filter(models.DecisionRecord.settled == True).count()  # noqa: E712

    return {
        "overall": _agg(pairs),
        "by_recommendation": {k: _agg(v) for k, v in sorted(by_action.items())},
        "by_policy_version": {k: _agg(v) for k, v in sorted(by_policy.items())},
        "by_experiment": {k: _agg(v) for k, v in sorted(by_experiment.items())},
        "readiness_mae": _readiness_mae(pairs),          # PILOT_PLAN C3
        "coverage": {"decisions_total": total, "decisions_settled": settled,
                     "outcomes_measured": len(pairs)},
        "note": "read-only; joins decision_records ⋈ decision_outcomes; recommends nothing",
    }


def _readiness_mae(pairs: List[Tuple[Any, Any]]) -> Dict[str, Any]:
    """Readiness-prediction accuracy (PILOT_PLAN C3). The engine predicted a
    readiness gain (`expected_gain`); the realized gain is `actual_gain`. The
    per-decision forecast error is |expected − actual|; MAE is its mean over
    decisions the learner actually FOLLOWED (executed) — where the predicted gain
    is a fair comparison. Falls back to all settled if none are executed yet."""
    def errs(rows):
        return [abs(d.expected_gain - o.actual_gain) for d, o in rows
                if d.expected_gain is not None and o.actual_gain is not None]
    executed = [(d, o) for d, o in pairs if o.executed]
    e = errs(executed)
    basis = "executed"
    if not e:                                            # nobody followed advice yet
        e = errs(pairs)
        basis = "all_settled"
    return {"mae": round(sum(e) / len(e), 2) if e else None, "n": len(e), "basis": basis}
