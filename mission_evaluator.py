"""
mission_evaluator.py — Whole-evaluator pipeline (M5 Phase A, EQ-07).

Composes the five Phase-A stages into ONE replayable evaluation:

    Events → MissionOutcome → Aggregate → Scorecard → Confidence → Promotion

The architectural rule this module enforces (and EQ-07 proves): only **stage 1**
(MissionOutcome) reads the DB. Every later stage consumes the previous in-memory
artifact and NOTHING else — no re-reading events, no re-reading projections. So
`evaluate_from_outcomes` is a pure function of the outcomes list, and therefore
of the event stream that produced it. That is what makes the whole evaluator
replayable and keeps the layering honest: if a future change lets promotion (or
any downstream stage) query events directly, `evaluate_from_outcomes` would need
a DB handle it does not have, and EQ-07 would fail.

The compared artifact is {scorecard (confidence-enriched), promotion decision} —
the two consumer-facing outputs. Both are deterministic (aggregation is
order-independent; the confidence bootstrap is seeded from the data), so a cold
replay reproduces them byte-for-byte.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import mission_outcome as mo
import policy_scorecard as ps
import policy_confidence as pc
import policy_promotion as pp

EVALUATOR_VERSION = "evaluator-1.0"


# ── stage 1 (the ONLY DB access) — two equivalent ways to obtain outcomes ────
def outcomes_incremental(db, user_id: int) -> List[Dict[str, Any]]:
    """Outcomes via the materialised (incrementally built) projection."""
    return json.loads(mo.get_or_build(db, user_id).payload).get("outcomes", [])


def outcomes_replay(db, user_id: int) -> List[Dict[str, Any]]:
    """Outcomes via a full replay straight from the event log (no stored state)."""
    return mo.rebuild_from_replay(db, user_id).get("outcomes", [])


# ── stages 2–5 — PURE: consume only the outcomes list, never the DB ──────────
def evaluate_from_outcomes(outcomes: List[Dict[str, Any]],
                           default_policy: str, candidate_policy: str,
                           config: Optional[Dict[str, Any]] = None,
                           alpha: float = pc.DEFAULT_ALPHA) -> Dict[str, Any]:
    """Run the evaluation pipeline over an outcomes list. No DB, no events, no
    wall-clock — a pure function of (outcomes, policies, config, alpha)."""
    # stage 2: aggregate per policy            ← outcomes
    aggregate = mo.aggregate_by_policy(outcomes)
    # sibling extraction: raw per-policy samples + evaluation window  ← outcomes
    samples = pc.samples_by_policy(outcomes)
    d_s = samples.get(default_policy, {})
    c_s = samples.get(candidate_policy, {})
    # stage 3: scorecard (pure presentation)   ← aggregate
    scorecard = ps.build_scorecard(aggregate, default_policy, candidate_policy)
    # stage 4: confidence-enriched scorecard   ← scorecard + samples
    enriched = pc.enrich_scorecard(scorecard, d_s, c_s,
                                   d_s.get("window"), c_s.get("window"), alpha)
    # stage 5: promotion decision              ← samples (via the confidence contract)
    decision = pp.decide(d_s, c_s, config, alpha)
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "default_policy": default_policy,
        "candidate_policy": candidate_policy,
        "scorecard": enriched,
        "promotion": decision,
    }


def evaluate(db, user_id: int, default_policy: str, candidate_policy: str,
             config: Optional[Dict[str, Any]] = None,
             alpha: float = pc.DEFAULT_ALPHA) -> Dict[str, Any]:
    """Full pipeline. Stage 1 (`outcomes_incremental`) is the ONLY DB touch;
    everything after is `evaluate_from_outcomes`, which takes no `db`."""
    outcomes = outcomes_incremental(db, user_id)
    return evaluate_from_outcomes(outcomes, default_policy, candidate_policy, config, alpha)
