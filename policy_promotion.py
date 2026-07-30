"""
policy_promotion.py — Promotion engine (M5 Phase A, EQ-04..06).

Answers ONE question — "Should the default change?" — the governance/automation
output, distinct from the scorecard ("what happened") and confidence ("how
certain"). It consumes ONLY the confidence contract (`evaluate_metric`) plus a
config; it never touches raw statistics, events, or the projection.

The rule is the frozen one from docs/implementation/mission-quality.md — explicit
gates, NOT a weighted composite (a composite would let a big win on one metric
mask a regression on another):

    PROMOTE candidate over default IF
        primary metric is higher                (statistically supported)
    AND every guardrail is not worse            (statistically supported)
    AND min sample_size >= threshold
    ELSE keep default, verdict ∈ {"worse", "insufficient_evidence"}

Direction lives HERE (governance), not in the confidence engine: the config says
which metric is primary, which are guardrails, and which direction is "better".
`policy_confidence.supported` only reports facts about the difference.

Config-driven so the metric wiring evolves without a code change. Phase A note:
the real primary lagging metric is retention_improvement, a READ-TIME view not yet
in the deterministic aggregate; until it lands, the leading proxy avg_mastery_gain
stands in as primary. Swapping to retention is a CONFIG edit — the rule, the
interface, and this engine stay put (exactly the swap-seam philosophy of M5).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import policy_confidence as cf

PROMOTION_VERSION = "promotion-1.0"

# Phase A provisional config (see module note). direction = which way is "better".
DEFAULT_CONFIG: Dict[str, Any] = {
    "primary": {"metric": "avg_mastery_gain", "direction": "higher"},
    "guardrails": [{"metric": "completion_rate", "direction": "higher"}],
    "min_sample_size": 20,
    "note": "Phase A: avg_mastery_gain proxies retention_improvement until the "
            "read-time retention view lands; swap is a config change.",
}


def _improved(ev: Dict[str, Any], direction: str) -> bool:
    """Candidate significantly BETTER on this metric, per its 'better' direction."""
    return ev["supported"]["higher"] if direction == "higher" else ev["supported"]["lower"]


def _regressed(ev: Dict[str, Any], direction: str) -> bool:
    """Candidate significantly WORSE on this metric, per its 'better' direction."""
    return ev["supported"]["lower"] if direction == "higher" else ev["supported"]["higher"]


def _decision(decision: str, verdict: Optional[str], evals: Dict[str, Any],
              min_n: int, config: Dict[str, Any], reasons: List[str]) -> Dict[str, Any]:
    return {
        "promotion_version": PROMOTION_VERSION,
        "decision": decision,                 # "PROMOTE" | "KEEP_DEFAULT"
        "verdict": verdict,                   # None (promoted) | "worse" | "insufficient_evidence"
        "min_sample_size": min_n,
        "threshold": config["min_sample_size"],
        "primary": config["primary"],
        "guardrails": config["guardrails"],
        "reasons": reasons,
        "evaluations": evals,                 # full per-metric confidence output (audit)
    }


def decide(default_samples: Dict[str, Any], candidate_samples: Dict[str, Any],
           config: Optional[Dict[str, Any]] = None, alpha: float = cf.DEFAULT_ALPHA) -> Dict[str, Any]:
    """Apply the explicit promotion rule. Returns an auditable decision object:
    the decision, the verdict (on KEEP_DEFAULT), and every metric's confidence
    evaluation that fed it. Deterministic (inherits confidence determinism)."""
    config = config or DEFAULT_CONFIG
    primary = config["primary"]
    guardrails = config["guardrails"]
    metrics = [primary] + guardrails

    evals: Dict[str, Any] = {}
    for m in metrics:
        k = m["metric"]
        evals[k] = cf.evaluate_metric(
            default_samples.get(k, []), candidate_samples.get(k, []),
            cf.METRIC_TYPES.get(k, "continuous"), alpha=alpha)

    min_n = min(evals[m["metric"]]["sample_size"]["min"] for m in metrics)

    # 1) insufficient evidence — not enough data to flip the default on anything
    if min_n < config["min_sample_size"]:
        return _decision("KEEP_DEFAULT", "insufficient_evidence", evals, min_n, config,
                         ["min sample %d < threshold %d" % (min_n, config["min_sample_size"])])

    # 2) guardrail regression — a significant worsening beats any primary gain
    for g in guardrails:
        if _regressed(evals[g["metric"]], g["direction"]):
            return _decision("KEEP_DEFAULT", "worse", evals, min_n, config,
                             ["guardrail %s significantly worse" % g["metric"]])

    # 3) primary metric
    ep = evals[primary["metric"]]
    if _regressed(ep, primary["direction"]):
        return _decision("KEEP_DEFAULT", "worse", evals, min_n, config,
                         ["primary %s significantly worse" % primary["metric"]])
    if _improved(ep, primary["direction"]):
        return _decision("PROMOTE", None, evals, min_n, config,
                         ["primary %s improved (supported); guardrails not worse; n>=threshold"
                          % primary["metric"]])

    # 4) improvement observed but not statistically supported — evidence, not vibes
    return _decision("KEEP_DEFAULT", "insufficient_evidence", evals, min_n, config,
                     ["primary %s improvement not statistically supported" % primary["metric"]])
