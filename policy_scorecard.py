"""
policy_scorecard.py — Human-readable policy scorecard (M5 Phase A, EQ-03).

ONE responsibility: turn a MissionOutcome AGGREGATE
(`mission_outcome.aggregate_by_policy`) into a human-readable comparison of a
**default** policy vs a **candidate** policy. It answers exactly one question —
"What happened?" — for a person reading signals.

It DECIDES nothing. No promotion, no confidence intervals, no thresholds, no
verdicts, no "should we ship this?". Those are separate downstream components
that consume different artifacts:
    • promotion engine   → EQ-04..06  (governance / automation)
    • confidence metadata→ EQ-08      (sample size, CI, window)
Keeping presentation ("what happened") separate from governance ("should the
default change") is the whole point of the two-evaluator-outputs design in
docs/implementation/mission-quality.md. This module is the first of the two.

Purity / faithfulness (EQ-03): every cell is either COPIED from the aggregate or
arithmetically derived from it (delta = candidate - default). The module reads no
events, re-aggregates nothing, holds no thresholds, and invents no numbers — so
the scorecard is a faithful projection of the aggregate, and inherits the
aggregate's replayability/determinism for free.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SCORECARD_VERSION = "scorecard-1.0"

# Metric catalogue — DECLARATIVE presentation metadata only, NOT a decision rule.
# `higher_is_better` is a display hint for a human eye (which direction reads as
# good); it gates nothing. `class_` mirrors the leading/lagging/efficiency
# taxonomy in mission-quality.md so the scorecard groups the way the design doc
# describes. Retention (the primary lagging metric) is a READ-TIME view (M2
# discipline) and is not in the deterministic aggregate yet — it joins the
# scorecard when the read-time retention view lands; the scorecard simply
# presents whatever metrics the aggregate carries.
METRICS: List[Dict[str, Any]] = [
    {"key": "completion_rate",        "label": "Completion rate",        "class": "guardrail",  "higher_is_better": True},
    {"key": "avg_mastery_gain",       "label": "Avg mastery gain",       "class": "leading",    "higher_is_better": True},
    {"key": "avg_attempts_on_target", "label": "Avg attempts / mission", "class": "efficiency", "higher_is_better": None},
    {"key": "avg_elapsed_seq",        "label": "Avg elapsed (seq-span)", "class": "efficiency", "higher_is_better": None},
]


def _delta(candidate: Optional[float], default: Optional[float]) -> Optional[float]:
    """candidate − default, or None if either side is absent. The ONLY arithmetic
    the scorecard performs; everything else is a copy from the aggregate."""
    if candidate is None or default is None:
        return None
    return round(candidate - default, 4)


def build_scorecard(aggregate: Dict[str, Any], default_policy: str,
                    candidate_policy: str) -> Dict[str, Any]:
    """Default-vs-candidate scorecard from an aggregate. Presentation only.

    `aggregate` is the dict returned by `mission_outcome.aggregate_by_policy`.
    Each row: {metric, label, class, higher_is_better, default, candidate, delta,
    n_default, n_candidate}. `n_*` is the policy's mission count — the sample size
    behind that column. (Per-metric effective-n and confidence intervals are added
    by the confidence step, EQ-08; the scorecard deliberately does not fabricate
    them here.)"""
    d = aggregate.get(default_policy) or {}
    c = aggregate.get(candidate_policy) or {}
    n_d = d.get("missions")
    n_c = c.get("missions")

    rows: List[Dict[str, Any]] = []
    for m in METRICS:
        k = m["key"]
        dv = d.get(k)
        cv = c.get(k)
        rows.append({
            "metric": k,
            "label": m["label"],
            "class": m["class"],
            "higher_is_better": m["higher_is_better"],
            "default": dv,          # copied verbatim from aggregate[default][k]
            "candidate": cv,        # copied verbatim from aggregate[candidate][k]
            "delta": _delta(cv, dv),
            "n_default": n_d,
            "n_candidate": n_c,
        })

    return {
        "scorecard_version": SCORECARD_VERSION,
        "default_policy": default_policy,
        "candidate_policy": candidate_policy,
        "n_default": n_d,
        "n_candidate": n_c,
        "rows": rows,
        # explicit boundary marker: this artifact is presentation, not governance.
        # (kept free of governance vocabulary so the artifact never even mentions
        # ship/keep decisions or evidence-strength — those are separate outputs.)
        "note": "presentation only — governance and evidence-strength are separate outputs",
    }


def render_text(scorecard: Dict[str, Any]) -> str:
    """A plain-text rendering for logs/CLI — still presentation only. Purely a
    function of the scorecard dict (no new numbers)."""
    dp = scorecard["default_policy"]
    cp = scorecard["candidate_policy"]
    lines = [
        "Policy scorecard — %s (default, n=%s)  vs  %s (candidate, n=%s)"
        % (dp, scorecard.get("n_default"), cp, scorecard.get("n_candidate")),
        "%-26s %10s %10s %10s" % ("metric", "default", "candidate", "Δ"),
        "-" * 60,
    ]
    for r in scorecard["rows"]:
        def fmt(v):
            return "—" if v is None else ("%.4f" % v if isinstance(v, float) else str(v))
        lines.append("%-26s %10s %10s %10s"
                     % (r["label"], fmt(r["default"]), fmt(r["candidate"]), fmt(r["delta"])))
    lines.append("(%s)" % scorecard["note"])
    return "\n".join(lines)
