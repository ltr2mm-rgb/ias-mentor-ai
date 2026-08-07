"""
platform_version.py — the single versioned deployment baseline (review
recommendation "create a versioned deployment baseline").

Individual decisions are already version-stamped (engine/prediction/profile/
explanation/planner). This adds ONE release identifier on top — **AIMENTORA
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

import datetime as _dt
import hashlib
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


# ── Build identity ───────────────────────────────────────────────────────────
# `git_sha` / `build_time` above are only as good as the deploy that sets them,
# and nothing in this repository does: the Dockerfile sets neither, so both report
# "unknown" and a running instance cannot say which build it is. That is the
# verifiable half of the deployment-ground-truth problem (audit H8).
#
# The fingerprint below closes it WITHOUT depending on the build system: it hashes
# the bytes of a fixed set of core source files that are actually running. Two
# instances with the same fingerprint are running the same code; a fingerprint that
# changes after a deploy proves the deploy landed.
#
# It is NOT commit provenance. It answers "is this the code I expect?", not "which
# commit is this?" — `git_sha` remains the right field for the latter once the
# deploy system supplies it, and is left untouched here.
#
# The file list is FIXED and small (this bounds the cost and keeps the value
# reproducible). Large content assets are deliberately excluded — they are data,
# not the application, and hashing them would make startup cost unpredictable.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_FINGERPRINT_FILES = (
    "main.py",
    "platform_version.py",
    "config.py",
    "auth.py",
    "models.py",
    "ai_runtime.py",
    "gemini_service.py",
    "learner_events.py",
    "learner_projection.py",
    "mission_engine.py",
    "concept_alignment.py",
    "rate_limit.py",
    "frontend/index.html",
    "frontend/admin.html",
)

_CODE_FINGERPRINT = None

# When this process began serving. Distinguishes "the deploy restarted the process"
# from "the deploy shipped different code" — a fingerprint that is unchanged after a
# restart means the same code came back up.
PROCESS_STARTED_AT = _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def code_fingerprint() -> str:
    """Short, stable hash of the running application's core source files.

    Computed on first use and cached, NOT at import: this module is imported on the
    boot path, and startup work is exactly what should not be added there. Missing
    files are folded in deterministically so the value stays reproducible rather
    than raising."""
    global _CODE_FINGERPRINT
    if _CODE_FINGERPRINT is None:
        h = hashlib.sha256()
        for rel in _FINGERPRINT_FILES:          # fixed order → reproducible
            h.update(rel.encode("utf-8"))
            try:
                with open(os.path.join(_BASE_DIR, rel), "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
            except OSError:
                h.update(b"\x00<absent>\x00")   # deterministic, never raises
        _CODE_FINGERPRINT = h.hexdigest()[:12]
    return _CODE_FINGERPRINT


def manifest() -> Dict[str, Any]:
    """The full release manifest a running instance reports. Build metadata is
    read from the environment at deploy time (set GIT_SHA / BUILD_TIME in the
    Dockerfile or Cloud Run env), so the same code reports the exact build.
    `code_fingerprint` is derived from the running files themselves, so it
    identifies the build even when the deploy sets nothing."""
    return {
        "platform": f"AIMENTORA Platform {PLATFORM_VERSION}",
        "platform_version": PLATFORM_VERSION,
        "architecture_version": ARCHITECTURE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "components": dict(COMPONENTS),
        "docs": dict(DOCS),
        "build": {
            "git_sha": os.getenv("GIT_SHA", "unknown"),
            "build_time": os.getenv("BUILD_TIME", "unknown"),
            "environment": os.getenv("APP_ENV", "unknown"),
            "code_fingerprint": code_fingerprint(),
            # Retained here for compatibility: tests/test_build_identity.py BI-07,
            # frontend/admin.html renderBuildIdentity() and DEPLOYMENT.md §4 all read
            # it from `build`. It is duplicated in `runtime` below, which is where it
            # belongs. Removing this copy is a BREAKING change and is not BL-008A.
            "process_started_at": PROCESS_STARTED_AT,
        },
        # ── runtime identity (BL-008A) ──────────────────────────────────────
        # WHAT WAS BUILT vs WHAT IS RUNNING are different questions. `build`
        # answers the first; `runtime` answers the second.
        #
        # K_REVISION is injected into the container by Cloud Run. Reading it lets a
        # running instance state its own revision, so DEPLOYMENT.md §4 check 1 no
        # longer requires gcloud. If the platform does not set it, this reports
        # "unknown" — the same honest default as the build fields.
        "runtime": {
            "revision": os.getenv("K_REVISION", "unknown"),
            "process_started_at": PROCESS_STARTED_AT,
        },
    }


if __name__ == "__main__":
    import json
    print(json.dumps(manifest(), indent=2))
