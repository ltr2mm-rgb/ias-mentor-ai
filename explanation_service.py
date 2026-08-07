"""
explanation_service.py — the Explanation Service (AIVORA OS, arch v1.3 §5.4).

The ONE place any "Why?" is generated. Consumes a State Delta (state_delta.py)
plus the new profile, and emits the Explanation contract that every UI surface
renders — so "Why?" is identical everywhere (Mission Control readiness modal,
Answer Intelligence, mission why, revision why).

Deterministic by design: the same delta always yields the same explanation. No
LLM call here — a template over the structured delta keeps it fast, cheap, and
traceable (an LLM can later *polish* the text, but the facts come from the delta).

    TODO (review Suggestion 3): attach concrete evidence IDs (attempt_1832,
    review_221) to each factor once they're threaded through the cascade, so an
    explanation is fully drillable down to the rows that moved the number.

Contract (INTELLIGENCE_LAYER_PLAN appendix, contract #6):
    { kind, claim, message,
      factors: [ {label, contribution, direction, evidence_ref} ],
      evidence: [ ... ],
      engine_version }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

ENGINE_VERSION = "explain-v1.3"

# tunable target line per dimension (kept in sync with decision_engine / ENG_SPEC §4)
DIM_TARGET = {"knowledge": 70, "retention": 70, "exam_skills": 65,
              "confidence": 70, "understanding": 70, "reasoning": 70}

# Human labels for internal dimension keys.
DIM_LABEL = {
    "knowledge": "Knowledge", "retention": "Retention (memory)",
    "exam_skills": "Exam skills", "confidence": "Confidence",
    "consistency": "Consistency", "learning_speed": "Learning speed",
    "understanding": "Understanding", "reasoning": "Reasoning",
}


def _phrase(label: str, change: float) -> str:
    verb = "improved" if change > 0 else "declined"
    return f"{label} {verb} {abs(change):.0f} pt{'s' if abs(change) != 1 else ''}"


def _val(profile: Optional[Dict[str, Any]], dim: str) -> Optional[float]:
    v = ((profile or {}).get("current_state", {}).get(dim) or {}).get("value")
    return v if isinstance(v, (int, float)) else None


def _lever_clause(delta: Dict[str, Any], profile: Optional[Dict[str, Any]]) -> str:
    """Behavioral wording for a Growth-Lever shift: name the threshold crossed,
    not just the transition (review: 'because retention dropped below 65% while
    knowledge remained above target')."""
    gl = delta.get("growth_lever", {})
    new_k, old_k = gl.get("new"), gl.get("old")
    if not new_k:
        return ""
    new_l = DIM_LABEL.get(new_k, str(new_k).title())
    nv, tgt = _val(profile, new_k), DIM_TARGET.get(new_k, 70)
    clause = f"your Growth Lever shifted to {new_l}"
    if isinstance(nv, (int, float)):
        clause += f" as it fell below its {tgt}% target ({nv}%)"
    ov = _val(profile, old_k) if old_k else None
    old_tgt = DIM_TARGET.get(old_k, 70) if old_k else 70
    if isinstance(ov, (int, float)) and ov >= old_tgt:
        clause += f" while {DIM_LABEL.get(old_k, str(old_k).title())} held above target"
    return clause


def explain_readiness(delta: Dict[str, Any],
                      profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Turn a readiness change into an Explanation. Returns a well-formed object
    even when nothing moved (so callers never special-case it)."""
    r = delta.get("readiness") or {}
    change = r.get("change")
    new_val = r.get("new")

    # rank the dimensions that moved, biggest absolute mover first
    moved = sorted(
        [(k, v) for k, v in (delta.get("dims") or {}).items()
         if isinstance(v.get("change"), (int, float)) and v["change"] != 0],
        key=lambda kv: abs(kv[1]["change"]), reverse=True,
    )
    factors: List[Dict[str, Any]] = [
        {"label": DIM_LABEL.get(k, k.title()),
         "contribution": v["change"],
         "direction": "+" if v["change"] > 0 else "-",
         "evidence_ref": None}                       # Suggestion 3: fill with real IDs later
        for k, v in moved
    ]

    if change is None:
        claim = f"Readiness is {new_val}%." if new_val is not None else "Readiness updated."
        message = claim
    else:
        verb = "rose" if change > 0 else ("dropped" if change < 0 else "held steady")
        claim = (f"Readiness {verb} {abs(change):.0f} pts to {new_val}%"
                 if change else f"Readiness held steady at {new_val}%")
        reasons = [_phrase(f["label"], f["contribution"]) for f in factors[:2]]
        if delta.get("growth_lever_changed"):
            reasons.append(_lever_clause(delta, profile))
        message = claim + (" because " + " and ".join(r for r in reasons if r) if reasons else ".")

    return {
        "kind": "readiness_change",
        "claim": claim,
        "message": message,
        "factors": factors,
        "evidence": [],
        "engine_version": ENGINE_VERSION,
    }


def explain_lever(lever_key: Optional[str], profile: Optional[Dict[str, Any]] = None) -> str:
    """Behavioral, standalone Growth-Lever explanation for a UI surface."""
    if not lever_key:
        return "All measured dimensions are near target — no single constraint right now."
    label = DIM_LABEL.get(lever_key, str(lever_key).title())
    v, tgt = _val(profile, lever_key), DIM_TARGET.get(lever_key, 70)
    if isinstance(v, (int, float)):
        return (f"{label} is your Growth Lever because it sits {tgt - v:.0f} pts below its "
                f"{tgt}% target ({v}%) — improving it is expected to lift readiness most.")
    return f"{label} is your Growth Lever — improving it is expected to lift readiness most."


def explain_revision(concept: str, retention: float,
                     predicted_days: Optional[float] = None, risk: int = 60) -> str:
    """Behavioral 'why is this revision scheduled' line (review example)."""
    if predicted_days is not None and predicted_days <= 1:
        return (f"Scheduled because {concept} retention is predicted to fall below "
                f"{risk}% within a day.")
    if isinstance(retention, (int, float)) and retention < risk:
        return f"Scheduled because {concept} retention ({retention}%) is already below the {risk}% risk line."
    horizon = f"in ~{int(predicted_days)} days" if predicted_days else "soon"
    return f"Scheduled to reinforce {concept} before retention decays {horizon}."


if __name__ == "__main__":
    import state_delta
    old = state_delta.snapshot({"current_state": {"knowledge": {"value": 69}, "retention": {"value": 63}},
                                "growth_lever": {"lever_key": "knowledge"}}, 48)
    new = state_delta.snapshot({"current_state": {"knowledge": {"value": 83}, "retention": {"value": 61}},
                                "growth_lever": {"lever_key": "retention"}}, 58)
    profile = {"current_state": {"knowledge": {"value": 83}, "retention": {"value": 61}}}
    exp = explain_readiness(state_delta.compute_delta(old, new), profile)
    print("MESSAGE:", exp["message"])
    print("LEVER  :", explain_lever("retention", profile))
    print("REVISE :", explain_revision("Parliament", 58, predicted_days=1))
    assert "rose 10 pts to 58%" in exp["claim"]
    assert "fell below its 70% target" in exp["message"] and "held above target" in exp["message"]
    assert "below its 70% target (61%)" in explain_lever("retention", profile)
    assert "within a day" in explain_revision("Parliament", 58, predicted_days=1)
    print("OK — behavioral, threshold-based explanations for readiness, lever, and revision.")
