"""
mission_planner.py — the Mission Planner (AI Marga OS, arch v1.3; review
recommendation "insert one more layer between Decision and Today's Mission").

    Decision Engine  →  Mission Planner  →  Today's Mission

A *decision* is instantaneous ("revise Parliament"). A *mission* is a plan —
an ordered set of steps that composes that decision into one coherent learner
experience, so the UI presents a session to work through instead of reacting to
one event at a time.

The planner owns SEQUENCING only. It reads a Decision (from decision_engine) and
expands it into steps via subject-agnostic recipes; it does not re-decide, re-
predict, or store state. Recipes are code-defined for v1 and tunable; a learner's
Learning DNA (§5.7) can later reshape them (more worked examples for a visual
learner, etc.) without changing the Mission contract.

Mission contract:
  { title, why, decision_action, target,
    steps: [ {kind, title, detail, target, est_min} ],
    expected_impact, success_criteria, est_total_min }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

PLANNER_VERSION = "mission-v1.3"

# Step recipes per decision action. Each recipe is a list of (kind, title, detail, est_min);
# "{t}" is filled with the decision target.
RECIPES: Dict[str, List[tuple]] = {
    "revise": [
        ("revise", "Revise {t}", "Re-read your notes + the key facts for {t}.", 12),
        ("practise", "Recall check — 8 questions on {t}", "Spaced-recall items, no hints.", 10),
        ("review", "Review what you missed", "Read the explanation for every wrong answer.", 6),
        ("checkpoint", "Confidence checkpoint", "Rate how sure you feel — recalibrates the model.", 4),
    ],
    "teach": [
        ("teach", "Learn {t}", "Work through the concept from first principles.", 15),
        ("example", "Worked example", "One solved question showing how {t} is tested.", 8),
        ("practise", "Practise — 6 questions on {t}", "Apply it immediately while fresh.", 10),
        ("checkpoint", "Mini-check", "Short mastery check to confirm it landed.", 5),
    ],
    "practise": [
        ("warmup", "Warm-up recall", "2 quick items to prime the topic.", 4),
        ("practise", "Practise — 12 questions on {t}", "Targeted at your weakest pattern.", 16),
        ("review", "Review mistakes", "Understand every miss before moving on.", 7),
        ("checkpoint", "Checkpoint", "Confirm the accuracy target was hit.", 4),
    ],
    "increase_difficulty": [
        ("practise", "Hard set on {t}", "Exam-grade difficulty to build depth.", 14),
        ("review", "Review mistakes", "Focus on the trickier distractors.", 6),
        ("checkpoint", "Checkpoint", "Confirm you hold up at higher difficulty.", 4),
    ],
    "checkpoint": [
        ("checkpoint", "Checkpoint on {t}", "A short assessment to re-measure {t}.", 8),
    ],
}

TITLE = {
    "revise": "Revise {t} before it fades",
    "teach": "Build {t} from the ground up",
    "practise": "Sharpen {t}",
    "increase_difficulty": "Level up on {t}",
    "checkpoint": "Checkpoint: {t}",
}


def plan(decision: Dict[str, Any], profile: Optional[Dict[str, Any]] = None,
         context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compose a Decision into Today's Mission."""
    primary = (decision or {}).get("primary", {}) or {}
    action = primary.get("action", "practise")
    target = primary.get("target", "your weakest area")
    recipe = RECIPES.get(action, RECIPES["practise"])

    steps: List[Dict[str, Any]] = []
    for kind, title, detail, est in recipe:
        steps.append({"kind": kind, "title": title.format(t=target),
                      "detail": detail.format(t=target), "target": target, "est_min": est})

    return {
        "title": TITLE.get(action, "Today's mission").format(t=target),
        "why": (decision or {}).get("reason", ""),
        "decision_action": action,
        "target": target,
        "steps": steps,
        "expected_impact": primary.get("expected_impact"),
        "success_criteria": primary.get("success_criteria"),
        "est_total_min": sum(s["est_min"] for s in steps),
        "planner_version": PLANNER_VERSION,
    }


if __name__ == "__main__":
    decision = {"primary": {"action": "revise", "target": "Parliament",
                            "expected_impact": {"readiness_delta": 1.1},
                            "success_criteria": "retention ≥ 75%"},
                "reason": "Parliament retention (58%) has fallen below the 65% risk line."}
    m = plan(decision)
    print("TITLE:", m["title"], "| ~", m["est_total_min"], "min")
    for i, s in enumerate(m["steps"], 1):
        print(f"  {i}. [{s['kind']}] {s['title']} ({s['est_min']}m)")
    print("WHY:", m["why"])
    assert m["steps"][0]["kind"] == "revise" and "Parliament" in m["steps"][0]["title"]
    assert m["est_total_min"] == 32 and len(m["steps"]) == 4
    assert any(s["kind"] == "checkpoint" for s in m["steps"])
    print("OK — decision 'revise Parliament' composed into a 4-step, 32-min mission.")
