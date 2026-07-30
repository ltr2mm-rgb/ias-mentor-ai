"""
platform_version.py — the single versioned deployment baseline (review
recommendation "create a versioned deployment baseline").

Individual decisions are already version-stamped (engine/prediction/profile/
explanation/planner). This adds ONE release identifier on top — **AI Marga
Platform 1.0** — that bundles every component + schema version into a build a
running instance can self-report via `GET /version`. Tag the matching git commit
and treat it as the immutable baseline for the pilot, so "which exact build
produced these results?" has a one-line answer.

Dependency-free on purpose (no DB, no engine imports) so it can be imported
anywhere, including a health/version endpoint. The manifest values are pinned
here and asserted equal to the live module constants by a consistency test —
so this file cannot silently drift from the code it describes.
"""

from __future__ import annotations

import os
from typing import Any, Dict

PLATFORM_VERSION = "1.0"          # the release identifier — bump on any pilot-affecting change
ARCHITECTURE_VERSION = "v1.4"     # INTELLIGENCE_LAYER_PLAN.md
SCHEMA_VERSION = "1.4"            # models.py: LearningProfile, PredictionHistory, DecisionRecord,
                                  # DecisionOutcome, EngineHealthLog, Experiment

# Algorithm/policy versions in effect for this release. Each must equal the
# corresponding module constant (guarded by tests/test_release_manifest).
COMPONENTS = {
    "decision_policy":     "decision-v1.4",   # decision_engine.ENGINE_VERSION
    "prediction":          "readiness-v1.3",  # prediction_engine.ENGINE_VERSION
    "profile":             "profile-v1.3",    # learner_kernel.PROFILE_VERSION
    "explanation":         "explain-v1.3",    # explanation_service.ENGINE_VERSION
    "planner":             "mission-v1.3",    # mission_planner.PLANNER_VERSION
    "experiment_registry": "v1",
    "policy_evaluator":    "v1",
    "engine_health":       "v1",
    "calibration":         "v1",
}

DOCS = {
    "architecture_plan":       "v1.4",   # INTELLIGENCE_LAYER_PLAN.md
    "product_architecture":    "v1.2",   # AI_MARGA_OS.md (frozen)
    "engineering_spec":        "v1.0",   # ENGINEERING_SPEC.md
    "pilot_plan":              "v1.0",   # PILOT_PLAN.md
    "pilot_report_template":   "v1.0",   # PILOT_REPORT_TEMPLATE.md
}


def manifest() -> Dict[str, Any]:
    """The full release manifest a running instance reports. Build metadata is
    read from the environment at deploy time (set GIT_SHA / BUILD_TIME in the
    Dockerfile or Cloud Run env), so the same code reports the exact build."""
    return {
        "platform": f"AI Marga Platform {PLATFORM_VERSION}",
        "platform_version": PLATFORM_VERSION,
        "architecture_version": ARCHITECTURE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "components": dict(COMPONENTS),
        "docs": dict(DOCS),
        "build": {
            "git_sha": os.getenv("GIT_SHA", "unknown"),
            "build_time": os.getenv("BUILD_TIME", "unknown"),
            "environment": os.getenv("APP_ENV", "unknown"),
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(manifest(), indent=2))
