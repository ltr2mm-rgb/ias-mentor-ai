"""
learning_pipeline.py — the event-driven adaptive loop (AI Marga OS, arch v1.3 §6).

One entry point, `process_event()`, runs the whole chain for ANY source event
(an MCQ answer today; a completed revision, a mock, a mentor session, an NCERT
read tomorrow) and publishes each stage on the EventBus so decoupled consumers
can react without knowing what triggered the change:

    <source>  →  ProfileUpdated  →  PredictionUpdated  →  StateDeltaCreated
              →  ExplanationCreated  →  MissionUpdated

The engines stay single-responsibility and separate (State / Prediction / Delta /
Explanation / Decision); this module only ORCHESTRATES them and emits events. It
is the thing endpoints call — so /me/attempt, and later /me/revise, /me/mock, …,
all share one consistent pipeline and return the same shape.

Returns:
  { profile, prediction, state_delta, explanation, decision, readiness_delta, events }
"""

from __future__ import annotations

import datetime
import json
import time
from typing import Any, Dict, List, Optional

import prepos
import learner_kernel
import prediction_engine
import state_delta as _sd
import explanation_service
import decision_engine
import baseline_policy
import experiment_registry
import mission_planner
import decision_outcomes
import engine_health
from events import Events, EventBus


def _date(x):
    if x is None:
        return None
    return x.date() if hasattr(x, "date") else x


def _weak_concepts(db, user_id: int, today: datetime.date, limit: int = 6) -> List[Dict[str, Any]]:
    """Knowledge context for the Decision Engine: per-concept retention (via the
    same forgetting curve the kernel uses), weakest-first."""
    import models
    rows = db.query(models.ConceptMastery).filter(models.ConceptMastery.user_id == user_id).all()
    out = []
    for c in rows:
        days = (today - _date(c.last_seen)).days if c.last_seen else None
        ret = prepos._retention((c.mastery or 0) * 100, days)
        out.append({"name": (c.concept_key or "concept").replace("-", " ").replace("_", " ").title(),
                    "concept_key": c.concept_key, "subject": c.subject,
                    "retention": ret, "mastery": round((c.mastery or 0) * 100),
                    "attempts": c.attempts or 0, "pattern": None})
    out.sort(key=lambda x: (x["retention"], x["mastery"]))
    return out[:limit]


def process_event(db, user_id: int, source_event: str = Events.ATTEMPT_RECORDED,
                  source_payload: Optional[Dict[str, Any]] = None,
                  bus: Optional[EventBus] = None,
                  today: Optional[datetime.date] = None) -> Dict[str, Any]:
    """Run the adaptive loop for one state-changing event. Best-effort per stage
    is the caller's concern (endpoints wrap this in try/except); here we let the
    bus isolate subscriber failures but run the core chain straight through."""
    today = today or datetime.date.today()
    bus = bus or EventBus()
    bus.publish(source_event, {"user_id": user_id, **(source_payload or {})})

    # OLD snapshot (before recompute) for the delta
    import models
    old_row = (db.query(models.LearningProfile)
               .filter(models.LearningProfile.user_id == user_id).first())
    old_profile = None
    if old_row and old_row.state_json:
        old_profile = {"current_state": json.loads(old_row.state_json),
                       "growth_lever": json.loads(old_row.growth_lever_json or "{}")}
    prior = (db.query(models.PredictionHistory)
             .filter(models.PredictionHistory.user_id == user_id,
                     models.PredictionHistory.metric == "readiness")
             .order_by(models.PredictionHistory.id.desc()).first())
    prior_val = None
    if prior and prior.value not in (None, ""):
        try:
            prior_val = float(prior.value)
        except (TypeError, ValueError):
            prior_val = None
    old_snap = _sd.snapshot(old_profile, prior_val)

    # ── timed, instrumented run (engine health telemetry) ──
    timings: Dict[str, float] = {}
    stage = None
    t_start = time.perf_counter()
    settle_ok: Optional[bool] = None
    try:
        # 1) ProfileUpdated
        stage = "kernel"; _t = time.perf_counter()
        profile = learner_kernel.recompute_profile(db, user_id, today)
        timings["kernel"] = round((time.perf_counter() - _t) * 1000, 2)
        bus.publish(Events.PROFILE_UPDATED, {"user_id": user_id, "profile": profile})

        # 2) PredictionUpdated
        stage = "prediction"; _t = time.perf_counter()
        prediction = prediction_engine.predict(
            db, user_id, profile, prediction_engine.PredictionType.READINESS)
        timings["prediction"] = round((time.perf_counter() - _t) * 1000, 2)
        bus.publish(Events.PREDICTION_UPDATED, {"user_id": user_id, "prediction": prediction})

        # 3) StateDeltaCreated
        stage = "delta"; _t = time.perf_counter()
        new_readiness = prediction.get("value") if isinstance(prediction.get("value"), (int, float)) else None
        delta = _sd.compute_delta(old_snap, _sd.snapshot(profile, new_readiness))
        timings["delta"] = round((time.perf_counter() - _t) * 1000, 2)
        bus.publish(Events.STATE_DELTA_CREATED, {"user_id": user_id, "state_delta": delta})

        # 4) ExplanationCreated
        stage = "explanation"; _t = time.perf_counter()
        explanation = explanation_service.explain_readiness(delta, profile)
        timings["explanation"] = round((time.perf_counter() - _t) * 1000, 2)
        bus.publish(Events.EXPLANATION_CREATED, {"user_id": user_id, "explanation": explanation})

        # 5) Decision — pick the policy for this learner's experiment arm.
        # Control runs the naïve baseline; treatment (and no-experiment) runs the
        # real Decision Engine. Both emit the same Decision contract.
        stage = "decision"; _t = time.perf_counter()
        weak = _weak_concepts(db, user_id, today)
        try:
            arm = experiment_registry.resolve(db, user_id)
        except Exception:
            arm = {"experiment_id": None, "policy_version": decision_engine.ENGINE_VERSION}
        if arm.get("policy_version") == baseline_policy.ENGINE_VERSION:
            decision = baseline_policy.decide(profile, prediction, weak)
        else:
            decision = decision_engine.decide(profile, prediction, weak)
        timings["decision"] = round((time.perf_counter() - _t) * 1000, 2)

        # 6) Mission Planner — compose the decision into Today's Mission
        stage = "mission"; _t = time.perf_counter()
        mission = mission_planner.plan(decision, profile, {"weak": weak})
        timings["mission"] = round((time.perf_counter() - _t) * 1000, 2)
    except Exception:
        timings["total"] = round((time.perf_counter() - t_start) * 1000, 2)
        engine_health.record(db, user_id, timings, ok=False, failed_stage=stage,
                             source_event=source_event, settle_ok=settle_ok)
        raise

    # Evidence architecture: log this recommendation version-stamped +
    # experiment-labelled (arm resolved above) for full reproducibility, and
    # settle any earlier decisions whose horizon has elapsed.
    versions = {"prediction_version": prediction.get("engine_version"),
                "profile_version": profile.get("profile_version"),
                "explanation_version": explanation.get("engine_version"),
                "planner_version": mission.get("planner_version")}
    decision_id = decision_outcomes.open_decision(
        db, user_id, decision, new_readiness, versions=versions,
        experiment_id=arm.get("experiment_id"))
    try:
        settled = decision_outcomes.settle_decisions(db, user_id)
        settle_ok = True
    except Exception:
        settled = []
        settle_ok = False

    bus.publish(Events.MISSION_UPDATED, {"user_id": user_id, "decision": decision,
                                         "mission": mission, "decision_id": decision_id})

    timings["total"] = round((time.perf_counter() - t_start) * 1000, 2)
    engine_health.record(db, user_id, timings, ok=True, source_event=source_event, settle_ok=settle_ok)

    return {
        "profile": {"current_state": profile["current_state"], "stage": profile["stage"],
                    "growth_lever": profile["growth_lever"]},
        "prediction": prediction,
        "state_delta": delta,
        "explanation": explanation,
        "decision": decision,
        "decision_id": decision_id,
        "mission": mission,
        "settled_decisions": settled,
        "readiness_delta": (delta.get("readiness") or {}).get("change"),
        "health": timings,
        "events": list(bus.log),
    }
