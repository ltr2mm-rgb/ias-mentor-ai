"""
experiment_ops_source.py — producer selection for the experiment-ops endpoint.

The operational control that decides WHICH producer supplies the
ExperimentOpsArtifact — snapshot (default) or live — WITHOUT the endpoint
branching and WITHOUT touching the contract, adapter, or renderer. Because the
adapter guarantees the contract, flipping the producer changes only the DATA
SOURCE, never the response shape.

Three deployment modes via the `EXPERIMENT_OPS_PRODUCER` flag:
  • unset / "snapshot"  → serve the committed `ops_data.json` (representative)
  • "live"              → run the active experiment(s) through the live runner
                          (`source.kind == "live"`); 503 if none is configured yet.

The active producer is exposed as operational telemetry (see `active_producer()`,
surfaced on `/version`) so "why am I still seeing representative data?" / "did we
switch to live?" is answerable without inspecting configuration.

This module is import-safe with no DB/web deps at import time (the live path takes
a `db` session as an argument), so it unit-tests against a plain session.
"""
from __future__ import annotations

import os
import json
import datetime
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCER_ENV = "EXPERIMENT_OPS_PRODUCER"
SNAPSHOT_PATH = os.path.join(_HERE, "ops_data.json")
ACTIVE_PATH = os.path.join(_HERE, "active_experiments.json")


class LiveUnavailable(Exception):
    """Live producer selected but no active experiment is configured to run."""


# The producer is resolved ONCE (at import / explicit reload) into immutable
# runtime state — NOT read from the environment per request. This makes the
# operational mode something operators intentionally deploy (restart / explicit
# reload) rather than something that can silently drift during a process's life
# if the env changes mid-flight.
_RESOLVED_PRODUCER: Optional[str] = None


def _read_env_producer() -> str:
    v = (os.getenv(PRODUCER_ENV) or "snapshot").strip().lower()
    return "live" if v == "live" else "snapshot"


def reload_producer() -> str:
    """(Re)resolve the producer from configuration. Call at application startup or
    on an explicit operational reload — never per request."""
    global _RESOLVED_PRODUCER
    _RESOLVED_PRODUCER = _read_env_producer()
    return _RESOLVED_PRODUCER


def active_producer() -> str:
    """The producer resolved at startup/reload (immutable runtime state):
    "snapshot" (default) | "live". Surfaced as operational telemetry on /version."""
    if _RESOLVED_PRODUCER is None:
        reload_producer()
    return _RESOLVED_PRODUCER


# resolve at import so the value is fixed by the time any request is served
reload_producer()


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


# ── snapshot producer (moved out of the web layer) ──────────────────────────
def snapshot_artifact() -> Dict[str, Any]:
    """Serve the committed representative snapshot, stamping contract identity +
    provenance defensively (a well-formed `ops_data.json` already carries them)."""
    with open(SNAPSHOT_PATH, "r", encoding="utf-8") as f:
        model = json.load(f)
    model.setdefault("schema", "ExperimentOpsArtifact")
    model.setdefault("schema_version", 1)
    src = dict(model.get("source") or {})
    src.setdefault("kind", "snapshot")
    src.setdefault("generated_at", model.get("generated_at"))
    src.setdefault("artifact_version", model.get("artifact_version", "ops-1.0"))
    src["served_at"] = _now_iso()
    model["source"] = src
    return model


# ── live producer (active experiment registry → runner → adapter) ───────────
def _load_active_experiments():
    """(featured Experiment | None, [history Experiments]) from the optional
    `active_experiments.json`. Delegates to the Experiment layer's single registry
    reader (`experiment.load_active`) so the live dashboard producer and the
    generation path resolve the SAME active experiment — one reader, one answer."""
    import experiment as ex
    return ex.load_active(ACTIVE_PATH)


def live_artifact(db, generated_at: Optional[str] = None) -> Dict[str, Any]:
    """Run the active experiment(s) live and shape via the SAME adapter. Raises
    LiveUnavailable if no active experiment is configured (honest empty state —
    never fabricates data or silently serves the snapshot as 'live')."""
    import experiment_runner as runner
    featured, history = _load_active_experiments()
    if featured is None:
        raise LiveUnavailable("no active experiment configured for the live producer")
    art = runner.build_live_artifact(db, featured, history, generated_at=generated_at or _now_iso())
    art["source"]["served_at"] = _now_iso()
    return art


# ── the resolver — the ONLY place the producer branch lives ─────────────────
def resolve(db=None, generated_at: Optional[str] = None) -> Dict[str, Any]:
    """Return the ExperimentOpsArtifact from the active producer. The endpoint
    calls only this — it never chooses a producer itself."""
    if active_producer() == "live":
        return live_artifact(db, generated_at)   # may raise LiveUnavailable
    return snapshot_artifact()
