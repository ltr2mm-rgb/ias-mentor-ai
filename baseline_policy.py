"""
baseline_policy.py — the control policy for the pilot A/B (arch v1.4; PILOT_PLAN §4).

The Decision Engine's rule-based policy (`decision_engine.py`) is the *treatment*.
This is the *control*: the deliberately naïve "traditional" behavior AIMARGA claims
to beat — recommend the next revision that's due, ignoring learner state, growth
lever, prediction, and thresholds. It exists so C5 ("beats baseline") has a real
comparator; without a control, "better" is unmeasurable.

It emits the SAME Decision contract as the treatment (so the Mission Planner,
Outcomes, and Policy Evaluator all treat it identically) but stamps
`engine_version = "decision-baseline"`, so the Policy Evaluator separates the two
arms cleanly. It reasons about nothing — that's the point.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

ENGINE_VERSION = "decision-baseline"


def decide(profile: Dict[str, Any], prediction: Dict[str, Any],
           weak_concepts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Naïve control: revise the most-due item (lowest retention as a due proxy),
    always. No lever logic, no thresholds, no prediction, no mentor intervention,
    no alternative reasoning — the traditional 'do the next revision' behavior."""
    weak = weak_concepts or []
    if weak:
        target = weak[0]                      # already ordered weakest/most-due first
        primary = {"action": "revise", "target": target.get("name", "your next topic"),
                   "target_key": target.get("concept_key"),
                   "params": {}, "success_criteria": "revision completed",
                   "expected_impact": {"readiness_delta": 1.0, "confidence": "low"}}
        reason = f"Scheduled revision — {primary['target']} is next in your revision queue."
    else:
        primary = {"action": "practise", "target": "a mixed set", "target_key": None,
                   "params": {}, "success_criteria": "session completed",
                   "expected_impact": {"readiness_delta": 1.0, "confidence": "low"}}
        reason = "Scheduled practice — work through the next set."

    return {
        "primary": primary,
        "alternative": None,                  # control offers no reasoned alternative
        "reason": reason,
        "mentor_intervene": False,            # control never escalates
        "evidence_trace": ["baseline: next-due item, state ignored"],
        "engine_version": ENGINE_VERSION,
    }


if __name__ == "__main__":
    prof = {"current_state": {"knowledge": {"value": 83}}, "growth_lever": {"lever_key": "retention"}}
    weak = [{"name": "Parliament", "concept_key": "parliament", "retention": 58, "mastery": 66},
            {"name": "Federalism", "concept_key": "federalism", "retention": 79, "mastery": 82}]
    d = decide(prof, {"stability": 0.8}, weak)
    print("PRIMARY:", d["primary"]["action"], "→", d["primary"]["target"])
    print("REASON :", d["reason"], "| engine:", d["engine_version"])
    assert d["engine_version"] == "decision-baseline"
    assert d["primary"]["action"] == "revise" and d["alternative"] is None
    assert d["mentor_intervene"] is False
    print("OK — naïve control policy: revise the next-due item, no reasoning, distinct engine tag.")
