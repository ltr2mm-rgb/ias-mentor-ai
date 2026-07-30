"""
prediction_engine.py — the Prediction Engine (AI Marga OS, arch v1.3 §4).

Owns FORECASTS. Given a Learning Profile it emits a Prediction contract:
    value + confidence + stability + horizon + engine_version + data_basis
        (INTELLIGENCE_LAYER_PLAN.md appendix, contract #3).

The load-bearing rule: this module stores nothing about the learner EXCEPT an
audit row in `prediction_history`. It reads state; it does not mutate it, and it
issues no commands.

Readiness lives here — NOT in the Learning Profile. This is the v1.3 correction
(§2): `readiness = 0.5·knowledge + 0.3·coverage + 0.2·recent_acc` used to sit
inside `prepos.compute_scores` (state); it is a forecast and belongs here. The
math is unchanged — only its home and its wrapper (confidence/stability/horizon/
version) are new. Algorithms may evolve to readiness-v2, v3…; the CONTRACT stays.
"""

from __future__ import annotations

import datetime
import enum
import json
from typing import Any, Dict, Optional, Union

import prepos

ENGINE_VERSION = "readiness-v1.3"


class PredictionType(str, enum.Enum):
    """Prediction metrics as an enum, not bare UI strings (review Suggestion 4) —
    so callers depend on a typed contract, not a spelling. `str` mixin keeps it
    JSON-serialisable and backward-compatible with the old string form."""
    READINESS = "readiness"
    PRELIMS_SCORE = "prelims_score"
    FORGETTING_DATE = "forgetting_date"
    TIME_TO_MASTERY = "time_to_mastery"


# Natural horizon per metric, in days (INTELLIGENCE_LAYER_PLAN §5.6).
HORIZON = {PredictionType.READINESS: 14, PredictionType.PRELIMS_SCORE: None,  # None → "to exam date"
           PredictionType.FORGETTING_DATE: 3, PredictionType.TIME_TO_MASTERY: 30}

# TODO (review Suggestion 3): when explanation_service is built, carry concrete
# evidence IDs (attempt_1832, review_221, mock_17) — not just concept labels — so
# every prediction/explanation is fully traceable back to the rows that moved it.

# Sample size at which a readiness forecast is considered firmly grounded
# (mirrors the forecast confidence bands in prepos.forecast: <150 low, <500 mid).
STABLE_N = 150


# ── PURE forecasting logic (no DB) ────────────────────────────────────────────

def readiness_value(knowledge: float, coverage: float, recent_acc: float) -> int:
    """The readiness formula — moved verbatim out of prepos.compute_scores (§2)."""
    return round(0.5 * knowledge + 0.3 * coverage + 0.2 * recent_acc)


def _stability(n: int, state: Dict[str, Dict[str, Any]]) -> float:
    """How firm is this prediction? Blend of evidence volume and how much of the
    Current State is actually measured (unknown dims → shakier forecast)."""
    volume = min(1.0, (n or 0) / STABLE_N)
    core = ["knowledge", "retention", "exam_skills"]
    measured = sum(1 for k in core
                   if isinstance((state.get(k) or {}).get("value"), (int, float)))
    coverage = measured / len(core)
    return round(0.6 * volume + 0.4 * coverage, 2)


def _next_evidence(n: int, state: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The cheapest evidence that would most raise stability — the actionable side
    of uncertainty (§5.2). Points at the lowest-confidence core dimension."""
    if n >= STABLE_N:
        return None
    core = ["knowledge", "retention", "exam_skills", "confidence"]
    ranked = sorted(
        core,
        key=lambda k: (state.get(k) or {}).get("confidence", 0.0)
        if isinstance((state.get(k) or {}).get("value"), (int, float)) else -1,
    )
    weakest = ranked[0]
    return {"dim": weakest, "n_items": max(10, STABLE_N - (n or 0))}


def _confidence_label(stability: float) -> str:
    return "High" if stability >= 0.75 else ("Medium" if stability >= 0.45 else "Low")


# ── DB-facing entry point ─────────────────────────────────────────────────────

def predict(db, user_id: int, profile: Dict[str, Any],
            metric: Union[PredictionType, str] = PredictionType.READINESS) -> Dict[str, Any]:
    """Produce a Prediction for `metric` from a profile dict (as returned by
    learner_kernel.recompute_profile) and append it to prediction_history.

    Supported v1.3 metrics: READINESS, PRELIMS_SCORE.
    """
    import models
    metric = PredictionType(metric)                     # accept enum OR legacy string
    state = profile["current_state"]
    ctx = profile.get("_context", {})
    n = ctx.get("answered") or 0
    stability = _stability(n, state)
    confidence = round(min(0.95, 0.1 + stability * 0.85), 2)

    if metric is PredictionType.READINESS:
        k = (state.get("knowledge") or {}).get("value")
        k = k if isinstance(k, (int, float)) else (ctx.get("recent_accuracy") or 0)
        value: Any = readiness_value(k, ctx.get("coverage_pct") or 0,
                                     ctx.get("recent_accuracy") or 0)
    elif metric is PredictionType.PRELIMS_SCORE:
        # reuse the evidence-tested band model in prepos.forecast
        fc = prepos.forecast({"recent_accuracy": ctx.get("recent_accuracy") or 0,
                              "answered": n}, "UPSC Prelims")
        value = {"base": fc["prelims_base"], "range": fc["prelims_range"]}
    else:
        raise ValueError(f"unknown metric: {metric}")

    pred = {
        "metric": metric.value,
        "value": value,
        "confidence": confidence,
        "confidence_label": _confidence_label(stability),
        "stability": stability,
        "next_evidence": _next_evidence(n, state),
        "horizon_days": HORIZON.get(metric),
        "engine_version": ENGINE_VERSION,
        "data_basis": ctx.get("data_basis", {}),
    }

    # audit trail — for pilots ("why did readiness jump on Tuesday?") — Suggestion 5
    db.add(models.PredictionHistory(
        user_id=user_id, metric=metric.value,
        value=json.dumps(value) if not isinstance(value, (int, float)) else str(value),
        confidence=confidence, stability=stability,
        horizon_days=pred["horizon_days"], engine_version=ENGINE_VERSION,
        data_basis_json=json.dumps(pred["data_basis"]),
        created_at=datetime.datetime.utcnow()))
    db.commit()
    return pred


if __name__ == "__main__":
    # DB-free smoke test of the pure forecasting logic.
    state = {"knowledge": {"value": 83, "confidence": 0.8},
             "retention": {"value": 71, "confidence": 0.8},
             "exam_skills": {"value": 64, "confidence": 0.6},
             "confidence": {"value": 88, "confidence": 0.5}}
    r = readiness_value(83, 60, 76)
    expected = round(0.5 * 83 + 0.3 * 60 + 0.2 * 76)     # the exact original prepos formula
    stab_hi = _stability(247, state)
    stab_lo = _stability(30, state)
    print("readiness =", r, "(expected", expected, ")")
    print("stability @247 =", stab_hi, _confidence_label(stab_hi))
    print("stability @30  =", stab_lo, _confidence_label(stab_lo),
          "→ next_evidence:", _next_evidence(30, state))
    assert r == expected, "readiness math must match the original prepos formula"
    assert stab_hi > stab_lo, "more evidence must mean higher stability"
    print("OK — readiness matches the original formula; stability rises with evidence.")
