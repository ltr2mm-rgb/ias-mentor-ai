"""
experiment_ops_adapter.py — the SINGLE constructor of ExperimentOpsArtifact v1.

One responsibility: `to_artifact(ExperimentResult, ...) -> ExperimentOpsArtifact v1`.
Nothing else runs experiments, ranks concepts, computes confidence, or promotes —
it only RESHAPES an already-computed `run_experiment()` result into the frozen
dashboard/endpoint contract.

Both producers go through this one function, so shape parity is guaranteed BY
CONSTRUCTION rather than by coincidence:

    snapshot generator ─┐
                        ├─▶ to_artifact() ─▶ ExperimentOpsArtifact v1
    live runner ────────┘

The endpoint then only chooses which producer supplies the bytes (transport, not
transformation). `source.kind` and the changing values (timestamps, metrics)
differ between producers; the KEYS never do — that is the parity test's job.

Contract axes (kept independent): `schema`/`schema_version` (JSON structure) ·
`artifact_version` (generation revision) · component versions in `replay`.
"""
from __future__ import annotations

import json
import hashlib
from typing import Any, Dict, List, Optional, Sequence

SCHEMA = "ExperimentOpsArtifact"
SCHEMA_VERSION = 1
ADAPTER_VERSION = "adapter-1.0"
EVALUATOR_VERSION = "evaluator-1.0"


# ── signal annotation (single definition; presentation-ready, derived upstream) ─
def annotate_signals(scorecard: Dict[str, Any]) -> Dict[str, Any]:
    """Attach {label,status} per scorecard row from the CI sign + metric direction,
    so the renderer computes nothing. status ∈ good|critical|neutral. Idempotent."""
    for r in scorecard.get("rows", []):
        lo, hi = r.get("interval", [None, None])
        guardrail = r.get("class") == "guardrail"
        higher_better = r.get("higher_is_better")
        if lo is None or hi is None:
            r["signal"] = {"label": "n/a", "status": "neutral"}
        elif lo > 0:
            r["signal"] = {"label": "Higher (supported)",
                           "status": "good" if (higher_better or guardrail) else "neutral"}
        elif hi < 0:
            if guardrail:
                r["signal"] = {"label": "Worse — guardrail", "status": "critical"}
            elif higher_better:
                r["signal"] = {"label": "Lower (supported)", "status": "critical"}
            else:
                r["signal"] = {"label": "Lower (supported)", "status": "neutral"}
        else:
            r["signal"] = {"label": "Not worse" if guardrail else "No sig. difference",
                           "status": "neutral"}
    return scorecard


# ── featured section from one ExperimentResult ───────────────────────────────
def _featured(result: Dict[str, Any]) -> Dict[str, Any]:
    exp = result["experiment"]
    sc = annotate_signals(dict(result["result"]["scorecard"]))
    w = result.get("window", {})
    return {
        "id": exp["id"],
        "title": exp.get("title", ""),
        "status": exp.get("status", "active"),
        "default_policy": exp["default_policy"],
        "candidate_policy": exp["candidate_policy"],
        "assignment_version": exp.get("assignment_version"),
        "hypothesis": exp.get("hypothesis", ""),
        "window": {"basis": w.get("basis"),
                   "start_seq": w.get("start_seq", exp.get("start_seq", 0)),
                   "end_seq": w.get("end_seq", exp.get("end_seq"))},
        "enrolled": result.get("enrolled", 0),
        "arm_counts": result.get("arm_counts", {}),
        "in_window_outcomes": result.get("in_window_outcomes", 0),
        "minimum_sample": exp.get("minimum_sample"),
        "primary_metric": exp.get("primary_metric"),
        "guardrails": list(exp.get("guardrails", [])),
        "scorecard": sc,
        "promotion": result["result"]["promotion"],
    }


# ── replay metadata (versions + a reproducible hash of the judged artifacts) ──
def _replay(result: Dict[str, Any]) -> Dict[str, Any]:
    sc, prom = result["result"]["scorecard"], result["result"]["promotion"]
    canonical = json.dumps({"scorecard": sc, "promotion": prom}, sort_keys=True)
    return {
        "experiment_layer_version": result.get("experiment_layer_version", "experiment-1.0"),
        "evaluator_version": EVALUATOR_VERSION,
        "outcome_version": "outcome-1.0",
        "confidence_version": sc.get("confidence_version", "confidence-1.0"),
        "scorecard_version": sc.get("scorecard_version", "scorecard-1.0"),
        "promotion_version": prom.get("promotion_version", "promotion-1.0"),
        "assignment_version": result["experiment"].get("assignment_version"),
        "window_basis": result.get("window", {}).get("basis"),
        "replay_hash": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()[:32],
        "note": "hash over {scorecard, promotion}; identical inputs reproduce it exactly",
    }


# ── one history row from an ExperimentResult ─────────────────────────────────
def _history_entry(result: Dict[str, Any]) -> Dict[str, Any]:
    exp = result["experiment"]
    prom = result["result"]["promotion"]
    rows = result["result"]["scorecard"]["rows"]
    prim_key = exp.get("primary_metric", "avg_mastery_gain")
    prim = next((r for r in rows if r["metric"] == prim_key), rows[0] if rows else {})
    comp = next((r for r in rows if r["metric"] == "completion_rate"), {})
    return {
        "experiment_id": exp["id"], "title": exp.get("title", ""),
        "date": exp.get("activated_at"),
        "candidate": exp["candidate_policy"], "default": exp["default_policy"],
        "n": prom.get("min_sample_size"),
        "decision": prom.get("decision"), "verdict": prom.get("verdict"),
        "primary_metric": prim_key,
        "primary_effect": prim.get("effect"), "primary_ci": prim.get("interval"),
        "completion_default": comp.get("default"), "completion_candidate": comp.get("candidate"),
        "window": {"basis": result.get("window", {}).get("basis"),
                   "end_seq": exp.get("end_seq")},
    }


def _promotion_history(history_results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Derive the promotion log from historical results deterministically, so both
    producers emit identical keys."""
    log = []
    for r in history_results:
        exp, prom = r["experiment"], r["result"]["promotion"]
        if prom.get("decision") == "PROMOTE":
            log.append({"date": exp.get("activated_at"), "experiment_id": exp["id"],
                        "action": "PROMOTE candidate → default",
                        "from_policy": exp["default_policy"], "to_policy": exp["candidate_policy"],
                        "note": "promotion rule fired (primary supported; guardrails not worse)"})
        elif prom.get("verdict") == "worse":
            log.append({"date": exp.get("activated_at"), "experiment_id": exp["id"],
                        "action": "KEEP_DEFAULT (worse)",
                        "from_policy": exp["default_policy"], "to_policy": exp["default_policy"],
                        "note": "candidate significantly regressed a guardrail"})
    return log


# ── the single artifact constructor ──────────────────────────────────────────
def to_artifact(featured_result: Dict[str, Any],
                history_results: Sequence[Dict[str, Any]] = (),
                *, source_kind: str, generated_at: str,
                artifact_version: str = "ops-1.0",
                runner_version: Optional[str] = None,
                platform: str = "AI Marga · Experiment Operations",
                footer: Optional[str] = None) -> Dict[str, Any]:
    """ExperimentResult(+history) → ExperimentOpsArtifact v1. The ONLY place the
    contract is assembled; every producer routes through here."""
    source: Dict[str, Any] = {"kind": source_kind, "generated_at": generated_at,
                              "artifact_version": artifact_version}
    if runner_version is not None:
        source["runner_version"] = runner_version
    if footer is None:
        footer = ("Live experiment run." if source_kind == "live" else
                  "Representative snapshot generated by the deterministic evaluator over the "
                  "Phase B harness (offline). Every value is a genuine evaluator/experiment "
                  "output; no live-learner data yet.")
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "artifact_version": artifact_version,
        "generated_at": generated_at,
        "source": source,
        "platform": platform,
        "featured": _featured(featured_result),
        "replay": _replay(featured_result),
        "history": [_history_entry(r) for r in history_results],
        "promotion_history": _promotion_history(history_results),
        "footer": footer,
    }


# ── shape helper (used by the parity test) ───────────────────────────────────
def recursive_schema(obj: Any) -> Any:
    """Structural skeleton: dict → sorted keys mapped to their sub-skeletons; list
    → the skeleton of its first element (or 'empty'); every leaf → "leaf". Leaf
    TYPES are collapsed on purpose so a nullable field (e.g. `verdict` None vs a
    string) or an int-vs-float value does not read as a shape difference — only the
    key structure and nesting are compared. Keys, nesting, and dict-vs-list-vs-leaf
    mismatches are still caught."""
    if isinstance(obj, dict):
        return {k: recursive_schema(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return ["<empty>" if not obj else recursive_schema(obj[0])]
    return "leaf"
