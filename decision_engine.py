"""
decision_engine.py — the Decision Engine (AIVORA OS §4; ENGINEERING_SPEC §6).

The ONE component allowed to answer "what should happen next?":
  • what to study / revise next        • revise vs. introduce new content
  • whether difficulty should change   • whether the AI Mentor should intervene
  • whether today's mission changes

Once every surface (Mission Control, AI Mentor, Revision Center, Adaptive Practice)
takes its recommendation from HERE, they stay consistent automatically — that's
what turns a set of intelligent features into one adaptive loop.

Load-bearing rule (AI_MARGA_OS §4): the Decision Engine owns CHOICES and stores no
learner data. It reads State + Prediction + the Knowledge context, simulates simple
candidate actions, and returns the highest expected-gain one WITH its reason and an
evidence trace. v1 is rule-based and interpretable (every default is tunable); an
evidence-trained policy can replace the internals later without changing the
Decision contract (freeze the contracts, not the algorithms).

Decision contract (INTELLIGENCE_LAYER_PLAN appendix, #4 / §5.8):
  { primary:{action,target,params,expected_impact,success_criteria},
    alternative:{action,target,expected_impact},
    reason, mentor_intervene, evidence_trace, engine_version }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

ENGINE_VERSION = "decision-v1.4"   # pilot baseline treatment policy (Platform 1.0)

# tunable thresholds (ENGINEERING_SPEC §11 open knobs)
RETENTION_RISK = 65        # below this, memory is fading → revise
MASTERY_TARGET = 70        # below this on the lever concept → teach/learn
EXAM_TARGET = 65
MASTERY_STRETCH = 85       # above this + stable → push difficulty up
STABILITY_MIN = 0.45       # below this, prediction is too shaky to trust a big move

# learner-facing action labels
ACTION_LABEL = {
    "revise": "Revise", "practise": "Practise", "teach": "Learn",
    "increase_difficulty": "Level up", "checkpoint": "Checkpoint",
    "re_measure": "Re-assess",
}


def _impact(action: str) -> float:
    """Heuristic expected readiness gain per action (v1; replace with trained
    estimates as evidence accrues — ENGINEERING_SPEC §5)."""
    return {"revise": 1.1, "practise": 1.4, "teach": 2.0,
            "increase_difficulty": 0.6, "checkpoint": 0.3, "re_measure": 0.0}.get(action, 0.8)


def _candidate_from_lever(lever: Optional[str], weak: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Translate the current Growth Lever into a concrete action on a concept."""
    target = weak[0] if weak else None
    tname = target["name"] if target else "your weakest area"
    if lever == "exam_skills":
        patt = (target or {}).get("pattern") or "statement-based"
        return {"action": "practise", "target": tname,
                "params": {"pattern": patt},
                "success_criteria": "pattern accuracy ≥ 80%"}
    if lever == "retention":
        return {"action": "revise", "target": tname, "params": {},
                "success_criteria": "retention ≥ 75%"}
    if lever in ("knowledge", "understanding", "reasoning", None):
        return {"action": "teach", "target": tname, "params": {},
                "success_criteria": "mastery ≥ 85%"}
    return {"action": "practise", "target": tname, "params": {},
            "success_criteria": "accuracy ≥ 80%"}


def decide(profile: Dict[str, Any], prediction: Dict[str, Any],
           weak_concepts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Choose the next best action.

    weak_concepts: [{name, subject, retention(0-100), mastery(0-100), pattern, attempts}]
                   ordered weakest-first (lowest retention). May be empty.
    """
    weak = weak_concepts or []
    state = profile.get("current_state", {})
    lever = (profile.get("growth_lever") or {}).get("lever_key")
    stability = prediction.get("stability", 1.0)

    def dim(k):
        v = (state.get(k) or {}).get("value")
        return v if isinstance(v, (int, float)) else None

    # ---- candidate actions, each with a behavioral reason ----
    at_risk = [c for c in weak if isinstance(c.get("retention"), (int, float))
               and c["retention"] < RETENTION_RISK]
    stretch = [c for c in weak if isinstance(c.get("mastery"), (int, float))
               and c["mastery"] >= MASTERY_STRETCH]

    reason = ""
    evidence: List[str] = []

    if at_risk:
        # memory fading beats new content — highest priority
        c = at_risk[0]
        primary = {"action": "revise", "target": c["name"], "params": {},
                   "success_criteria": "retention ≥ 75%"}
        know = dim("knowledge")
        know_clause = (f"Knowledge is already above target ({know}%), so revision recovers "
                       "more readiness than new content today"
                       if isinstance(know, (int, float)) and know >= MASTERY_TARGET
                       else "recovering it protects the gains you've made")
        reason = (f"{c['name']} retention ({c['retention']}%) has fallen below the "
                  f"{RETENTION_RISK}% risk line and is predicted to keep dropping; {know_clause}.")
        evidence = [f"{c['name']} retention {c['retention']}% < {RETENTION_RISK}%",
                    f"growth lever = {lever}", f"prediction stability {stability}"]
    elif lever:
        primary = _candidate_from_lever(lever, weak)
        lv = dim(lever)
        tgt = EXAM_TARGET if lever == "exam_skills" else MASTERY_TARGET
        reason = (f"Your Growth Lever is {lever.replace('_', ' ')}"
                  + (f" ({lv}%, below its {tgt}% target)" if isinstance(lv, (int, float)) else "")
                  + f"; {ACTION_LABEL.get(primary['action'], primary['action']).lower()}"
                  f" {primary['target']} is the highest expected-gain move.")
        evidence = [f"growth lever = {lever}" + (f" at {lv}%" if lv is not None else ""),
                    f"prediction stability {stability}"]
    elif stretch:
        c = stretch[0]
        primary = {"action": "increase_difficulty", "target": c["name"],
                   "params": {"to": "hard"}, "success_criteria": "hard-item accuracy ≥ 70%"}
        reason = (f"{c['name']} mastery ({c['mastery']}%) is above the {MASTERY_STRETCH}% "
                  "stretch line and stable — harder items now build exam-grade depth.")
        evidence = [f"{c['name']} mastery {c['mastery']}% ≥ {MASTERY_STRETCH}%"]
    else:
        primary = {"action": "practise", "target": (weak[0]["name"] if weak else "a mixed set"),
                   "params": {}, "success_criteria": "accuracy ≥ 80%"}
        reason = "All measured dimensions are near target — balanced practice keeps momentum."
        evidence = ["no dimension below target"]

    # low stability → prefer gathering evidence before a big content swing
    if stability < STABILITY_MIN and primary["action"] in ("teach", "increase_difficulty"):
        primary = {"action": "practise", "target": primary["target"], "params": {},
                   "success_criteria": "accuracy ≥ 80%"}
        reason = ("Prediction is still low-stability, so a few more practice items firm up "
                  "the picture before committing to new content. ") + reason
        evidence.append(f"stability {stability} < {STABILITY_MIN}")

    # attach the concept key of the target, so Decision Outcomes can later check
    # whether the learner actually acted on THIS recommendation (executed?).
    if "target_key" not in primary:
        match = next((c for c in weak if c.get("name") == primary.get("target")), None)
        primary["target_key"] = match.get("concept_key") if match else None

    primary["expected_impact"] = {"readiness_delta": _impact(primary["action"]),
                                  "confidence": "medium"}

    # ---- alternative (the road not taken) ----
    alt = None
    if len(weak) > 1:
        c2 = weak[1]
        alt_action = "revise" if (isinstance(c2.get("retention"), (int, float))
                                  and c2["retention"] < RETENTION_RISK) else "practise"
        alt = {"action": alt_action, "target": c2["name"],
               "expected_impact": {"readiness_delta": _impact(alt_action)}}

    # ---- mentor intervention: confidence miscalibration or a sharp drop ----
    conf = dim("confidence")
    mentor_intervene = bool(isinstance(conf, (int, float)) and conf < 60) or bool(at_risk and len(at_risk) >= 2)

    return {
        "primary": primary,
        "alternative": alt,
        "reason": reason,
        "mentor_intervene": mentor_intervene,
        "evidence_trace": evidence,
        "engine_version": ENGINE_VERSION,
    }


if __name__ == "__main__":
    prof = {"current_state": {"knowledge": {"value": 83}, "retention": {"value": 58},
                              "exam_skills": {"value": 64}, "confidence": {"value": 72}},
            "growth_lever": {"lever_key": "retention"}, "stage": "Advanced"}
    pred = {"value": 72, "stability": 0.8}
    weak = [{"name": "Parliament", "subject": "Polity", "retention": 58, "mastery": 66, "pattern": "statement_based"},
            {"name": "Directive Principles", "subject": "Polity", "retention": 61, "mastery": 55, "pattern": "elimination"}]
    d = decide(prof, pred, weak)
    print("PRIMARY:", d["primary"]["action"], "→", d["primary"]["target"], "| impact", d["primary"]["expected_impact"])
    print("ALT    :", d["alternative"])
    print("REASON :", d["reason"])
    print("MENTOR :", d["mentor_intervene"], "| EVIDENCE:", d["evidence_trace"])
    assert d["primary"]["action"] == "revise" and d["primary"]["target"] == "Parliament"
    assert d["alternative"]["target"] == "Directive Principles"
    assert "65% risk line" in d["reason"]
    print("OK — Decision Engine picks revise-at-risk with a behavioral reason + alternative.")
