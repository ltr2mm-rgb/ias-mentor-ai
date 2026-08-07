"""
learner_kernel.py — the Learner Kernel (AIVORA OS, arch v1.3 §4).

Owns the **Learning Profile / Learner State** (`learning_profile` row): the single
source of truth for *who the learner is and how they're doing right now*.

The load-bearing rule (AI_MARGA_OS.md §4): this module owns STATE only.
  • It issues no commands  (that's the Decision Engine).
  • It makes no forecasts   (that's prediction_engine.py).
  • Readiness / success_probability are NOT stored here — they are Predictions.

Evidence source (INTELLIGENCE_LAYER_PLAN §3): the Current State is derived from the
LIVE AML tables — ConceptMastery, SkillMastery, ConceptAttempt — the same rows
`POST /me/attempt` updates on every answer. So one answer genuinely moves the
profile (and, downstream, readiness). It reuses the evidence-tested retention decay
in `prepos._retention` rather than inventing a new curve.

Structure: each dimension is a small, independently-testable REDUCER over evidence.
  TODO (post-pilot, review Suggestion 1): promote these into a formal reducer
  registry (KnowledgeReducer, RetentionReducer, …) so new evidence types (essays,
  mentor chats) plug in without growing one aggregation function. Not before pilot.

  TODO (post-pilot, review Suggestion 5): state/dna/growth_lever are JSON blobs —
  fine now. Normalize into columns ONLY the fields that become operationally
  important for indexing / filtering / analytics once the pilot says which.

Algorithms here are free to evolve (each dim carries its own `source` version, so
one dimension can improve without bumping the whole profile — review Suggestion 2);
the CONTRACT this emits (INTELLIGENCE_LAYER_PLAN appendix) is what stays stable.
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, List, Optional, Tuple

import prepos

# ── versioning ────────────────────────────────────────────────────────────────
PROFILE_VERSION = "profile-v1.3"          # bumps only on a structural change
# Per-dimension source versions (review Suggestion 2) — improve one in isolation.
DIM_VERSION = {
    "knowledge": "knowledge-v1.3", "retention": "retention-v1.3",
    "exam_skills": "exam-skills-v1.3", "confidence": "confidence-v1.3",
    "consistency": "consistency-v1.3", "learning_speed": "learning-speed-v1.3",
    "understanding": "understanding-v0", "reasoning": "reasoning-v0",
}

STATE_DIMS = list(DIM_VERSION.keys())

# ── Growth-Lever config (ENGINEERING_SPEC §4 — theory of constraints) ─────────
LEVER_TARGETS = {"knowledge": 70, "reasoning": 70, "retention": 70,
                 "exam_skills": 65, "understanding": 70, "confidence": 70}
LEVER_WEIGHTS = {"exam_skills": 1.3, "reasoning": 1.3, "retention": 1.2,
                 "knowledge": 1.0, "understanding": 1.0, "confidence": 1.0}


# ══════════════════════════════════════════════════════════════════════════════
#  PURE reducers (no DB) — this is where each dimension's algorithm lives.
#  Every reducer returns a dimension dict {value, confidence, source} or 'unknown'.
# ══════════════════════════════════════════════════════════════════════════════

def _conf(n: Optional[int]) -> float:
    """Backing-observation count → 0-1 confidence. Needs ~200 attempts for full."""
    if not n:
        return 0.0
    return round(min(0.9, 0.2 + (n / 200.0) * 0.7), 2)


def _dim(value: Optional[float], n: Optional[int], key: str) -> Dict[str, Any]:
    src = DIM_VERSION[key]
    if value is None:
        return {"value": "unknown", "confidence": 0.0, "source": src}
    return {"value": round(value), "confidence": _conf(n), "source": src}


def r_knowledge(masteries: List[Tuple[float, int]]) -> Dict[str, Any]:
    """Attempt-weighted mean of per-concept mastery (0-1 → 0-100). Moves every answer."""
    seen = [(m * 100, min(a or 0, 40)) for m, a in masteries if (a or 0) >= 1]
    if not seen:
        return _dim(None, 0, "knowledge")
    wsum = sum(w for _, w in seen)
    val = sum(v * w for v, w in seen) / wsum
    return _dim(val, sum((a or 0) for _, a in masteries), "knowledge")


def r_retention(concepts: List[Tuple[float, Optional[datetime.date], int]],
                today: datetime.date) -> Dict[str, Any]:
    """Forgetting-curve-adjusted mastery, weighted by attempts. Reuses prepos._retention."""
    num, wsum, ntot = 0.0, 0, 0
    for m, last, a in concepts:
        ntot += (a or 0)
        if (a or 0) < 3:
            continue
        days = (today - last).days if last else None
        ret = prepos._retention(m * 100, days)
        w = min(a or 0, 40)
        num += ret * w
        wsum += w
    if not wsum:
        return _dim(None, 0, "retention")
    return _dim(num / wsum, ntot, "retention")


def r_exam_skills(skills: List[Tuple[float, int]]) -> Dict[str, Any]:
    """Mean per-pattern skill mastery (elimination, statement-analysis, …)."""
    if not skills:
        return _dim(None, 0, "exam_skills")
    val = 100 * sum(m for m, _ in skills) / len(skills)
    return _dim(val, sum((a or 0) for _, a in skills), "exam_skills")


def r_confidence(tags: List[Tuple[Optional[str], bool]]) -> Dict[str, Any]:
    """1 − (sure-but-wrong share) over confidence-tagged attempts (calibration)."""
    tagged = [(c, ok) for c, ok in tags if c]
    if not tagged:
        return _dim(None, 0, "confidence")
    sure_wrong = sum(1 for c, ok in tagged if c == "sure" and not ok)
    return _dim(100 * (1 - sure_wrong / len(tagged)), len(tagged), "confidence")


def r_consistency(dates: List[Optional[datetime.date]], today: datetime.date,
                  window: int = 14) -> Dict[str, Any]:
    """Active-day ratio over the trailing window."""
    if not dates:
        return _dim(None, 0, "consistency")
    active = {d for d in dates if d and 0 <= (today - d).days < window}
    return _dim(100 * len(active) / window, len(dates), "consistency")


def r_learning_speed(response_ms: List[Optional[int]]) -> Dict[str, Any]:
    """Reading/processing speed band from response time (ideal ~45-75s).
    Same shape as prepos.compute_scores' reading_speed."""
    secs = [ms / 1000.0 for ms in response_ms if ms]
    if not secs:
        return _dim(None, 0, "learning_speed")
    avg = sum(secs) / len(secs)
    rs = min(100, round(60 + (75 - avg) * 0.8)) if avg <= 75 else max(35, round(60 - (avg - 75) * 0.6))
    return _dim(rs, len(secs), "learning_speed")


def assemble_state(dims: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Collect reducers into the Current-State contract. Readiness is absent by
    construction — it's a Prediction, never state (§2)."""
    out = {k: dims.get(k, _dim(None, 0, k)) for k in STATE_DIMS}
    out["understanding"] = _dim(None, 0, "understanding")   # needs typed items (ENG_SPEC §2)
    out["reasoning"] = _dim(None, 0, "reasoning")           # needs a CSAT probe
    return out


def growth_lever(state: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The ONE dimension whose lift is predicted to move readiness most
    (drag = weight × shortfall/target). Only MEASURED dims qualify (ENG_SPEC §4)."""
    best_key, best_drag, drags = None, 0.0, {}
    for key, target in LEVER_TARGETS.items():
        val = (state.get(key) or {}).get("value")
        if not isinstance(val, (int, float)):
            continue
        drag = LEVER_WEIGHTS.get(key, 1.0) * max(0, target - val) / target
        drags[key] = round(drag, 3)
        if drag > best_drag:
            best_key, best_drag = key, drag
    if best_key is None:
        return {"lever_key": None, "drag": 0.0,
                "rationale": "Not enough measured signal yet to name a Growth Lever."}
    return {"lever_key": best_key, "drag": round(best_drag, 3), "all_drags": drags,
            "rationale": f"{best_key.replace('_', ' ').title()} is furthest below target "
                         f"weighted by impact — improving it is expected to lift readiness most."}


def stage_of(state: Dict[str, Dict[str, Any]]) -> str:
    k = (state.get("knowledge") or {}).get("value")
    if not isinstance(k, (int, float)):
        return "Foundation"
    return "Advanced" if k >= 70 else ("Intermediate" if k >= 45 else "Foundation")


# ══════════════════════════════════════════════════════════════════════════════
#  DB orchestration — load evidence, run reducers, upsert the row
# ══════════════════════════════════════════════════════════════════════════════

def _date(x):
    if x is None:
        return None
    return x.date() if hasattr(x, "date") else x


def recompute_profile(db, user_id: int, today: Optional[datetime.date] = None) -> Dict[str, Any]:
    """Recompute and PERSIST the learner's `learning_profile` row from live AML
    evidence, then return it. Call after any evidence event (§6 cascade step 3).
    Returns the profile dict; stashes prediction context under `_context`."""
    import models
    import syllabus_tracker_data
    today = today or datetime.date.today()

    cms = db.query(models.ConceptMastery).filter(models.ConceptMastery.user_id == user_id).all()
    sms = db.query(models.SkillMastery).filter(models.SkillMastery.user_id == user_id).all()

    # recent attempts (confidence / speed / recent-accuracy); total for volume
    recent = (db.query(models.ConceptAttempt)
                .filter(models.ConceptAttempt.user_id == user_id)
                .order_by(models.ConceptAttempt.id.desc()).limit(300).all())
    total = (db.query(models.ConceptAttempt)
               .filter(models.ConceptAttempt.user_id == user_id).count())
    since = today - datetime.timedelta(days=14)
    day_rows = (db.query(models.ConceptAttempt.created_at)
                  .filter(models.ConceptAttempt.user_id == user_id,
                          models.ConceptAttempt.created_at >= since).all())

    dims = {
        "knowledge":   r_knowledge([(c.mastery, c.attempts) for c in cms]),
        "retention":   r_retention([(c.mastery, _date(c.last_seen), c.attempts) for c in cms], today),
        "exam_skills": r_exam_skills([(s.mastery, s.attempts) for s in sms]),
        "confidence":  r_confidence([(a.confidence, bool(a.correct)) for a in recent]),
        "consistency": r_consistency([_date(d[0]) for d in day_rows], today),
        "learning_speed": r_learning_speed([a.response_ms for a in recent]),
    }
    state = assemble_state(dims)
    lever = growth_lever(state)
    stage = stage_of(state)

    last200 = recent[:200]
    recent_acc = round(100 * sum(1 for a in last200 if a.correct) / len(last200)) if last200 else 0
    syl_done = (db.query(models.SyllabusProgress)
                  .filter(models.SyllabusProgress.user_id == user_id).count())
    coverage_pct = round(100 * syl_done / max(1, syllabus_tracker_data.total_topics()))

    row = (db.query(models.LearningProfile)
             .filter(models.LearningProfile.user_id == user_id).first())
    if row is None:
        row = models.LearningProfile(user_id=user_id)
        db.add(row)
    row.state_json = json.dumps(state)
    if not row.dna_json:
        row.dna_json = json.dumps({})          # Learning DNA (§5.7) — stub until traits modelled
    row.stage = stage
    row.growth_lever_json = json.dumps(lever)
    row.profile_version = PROFILE_VERSION
    row.updated_at = datetime.datetime.utcnow()
    db.commit()

    return {
        "user_id": user_id, "current_state": state, "learning_dna": json.loads(row.dna_json or "{}"),
        "stage": stage, "growth_lever": lever, "profile_version": PROFILE_VERSION,
        "_context": {"coverage_pct": coverage_pct, "recent_accuracy": recent_acc, "answered": total,
                     "data_basis": {"mcqs": total,
                                    "revisions": sum(1 for a in recent if a.attempt_context == "revision"),
                                    "sessions": len({a.session_id for a in recent if a.session_id}),
                                    "mocks": sum(1 for a in recent if a.attempt_context == "mock")}},
    }


if __name__ == "__main__":
    # DB-free smoke test of the reducers (real numbers, no database).
    today = datetime.date(2026, 7, 27)
    masteries = [(0.86, 20), (0.74, 15), (0.61, 9)]      # (mastery 0-1, attempts)
    concepts = [(0.86, datetime.date(2026, 7, 25), 20),
                (0.74, datetime.date(2026, 7, 18), 15),
                (0.61, datetime.date(2026, 7, 10), 9)]
    dims = {
        "knowledge":   r_knowledge(masteries),
        "retention":   r_retention(concepts, today),
        "exam_skills": r_exam_skills([(0.64, 120)]),
        "confidence":  r_confidence([("sure", True), ("sure", False), ("guess", False)]),
        "consistency": r_consistency([today, today - datetime.timedelta(days=2)], today),
        "learning_speed": r_learning_speed([52000, 61000, 70000]),
    }
    state = assemble_state(dims)
    for k, v in state.items():
        print(f"  {k:14} {v}")
    print("STAGE:", stage_of(state), "| LEVER:", growth_lever(state)["lever_key"])
    assert "readiness" not in state
    assert state["knowledge"]["value"] == 77 and state["knowledge"]["source"] == "knowledge-v1.3"
    assert state["retention"]["value"] <= state["knowledge"]["value"]   # decay only lowers
    assert state["understanding"]["value"] == "unknown"
    print("OK — reducers produce sourced dims; retention ≤ knowledge; readiness absent.")
