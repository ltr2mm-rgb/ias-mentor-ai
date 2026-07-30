"""
state_delta.py — the State Delta (AI Marga OS, arch v1.3; review recommendation
"insert one very small component between the kernel and the UI").

Sits between the Prediction Engine and the Explanation Service:

    Evidence → Learner Kernel → Prediction Engine → STATE DELTA → Explanation → UI

Emits a single structured diff of what changed on an event, so neither the
Explanation Service nor any frontend component has to recompute differences
independently. Pure functions, no DB, no I/O — trivially testable.

Contract it emits:
    { "dims": { <dim>: {"old","new","change"} , ... },   # only dims that moved
      "readiness": {"old","new","change"} | None,
      "growth_lever_changed": bool,
      "growth_lever": {"old","new"} }
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def snapshot(profile: Optional[Dict[str, Any]], readiness: Optional[float]) -> Dict[str, Any]:
    """Reduce a full profile dict + a readiness value to the minimal shape the
    delta needs. Accepts None (cold start) and returns an empty-ish snapshot."""
    profile = profile or {}
    state = profile.get("current_state", {}) or {}
    lever = (profile.get("growth_lever") or {}).get("lever_key")
    numeric = {k: v.get("value") for k, v in state.items()
               if isinstance(v, dict) and isinstance(v.get("value"), (int, float))}
    return {"dims": numeric, "readiness": readiness, "lever": lever}


def compute_delta(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Structured old→new diff between two snapshots()."""
    dims: Dict[str, Any] = {}
    for key, new_v in (new.get("dims") or {}).items():
        old_v = (old.get("dims") or {}).get(key)
        if old_v is None:
            if new_v is not None:
                dims[key] = {"old": None, "new": new_v, "change": None}
            continue
        if new_v != old_v:
            dims[key] = {"old": old_v, "new": new_v, "change": round(new_v - old_v, 1)}

    r_old, r_new = old.get("readiness"), new.get("readiness")
    readiness = None
    if r_new is not None:
        change = round(r_new - r_old, 1) if isinstance(r_old, (int, float)) else None
        readiness = {"old": r_old, "new": r_new, "change": change}

    l_old, l_new = old.get("lever"), new.get("lever")
    return {
        "dims": dims,
        "readiness": readiness,
        "growth_lever_changed": bool(l_new and l_old and l_new != l_old),
        "growth_lever": {"old": l_old, "new": l_new},
    }


if __name__ == "__main__":
    old = snapshot({"current_state": {"knowledge": {"value": 69}, "retention": {"value": 63},
                                      "exam_skills": {"value": 64}},
                    "growth_lever": {"lever_key": "knowledge"}}, readiness=48)
    new = snapshot({"current_state": {"knowledge": {"value": 83}, "retention": {"value": 63},
                                      "exam_skills": {"value": 64}},
                    "growth_lever": {"lever_key": "exam_skills"}}, readiness=58)
    d = compute_delta(old, new)
    print(d)
    assert d["dims"]["knowledge"]["change"] == 14
    assert "retention" not in d["dims"], "unchanged dims must be omitted"
    assert d["readiness"]["change"] == 10
    assert d["growth_lever_changed"] is True
    print("OK — delta reports only what moved: knowledge +14, readiness +10, lever knowledge→exam_skills.")
