"""
experiment_runner.py — the LIVE producer of ExperimentOpsArtifact v1.

One responsibility: run experiments and hand their results to the adapter.
    run(db, experiment)                    -> ExperimentResult          (single)
    build_live_artifact(db, featured, ...) -> ExperimentOpsArtifact v1  (via adapter)

It does NOT reshape anything (that is the adapter) and it does NOT decide which
producer the endpoint serves (that is main.py). `run()` is a thin call into the
frozen experiment layer's `run_experiment()`; the runner exists so the live path
has an explicit boundary and version stamp, symmetric with the offline generator.
"""
from __future__ import annotations

from typing import Any, Dict, Sequence

import experiment as ex
import experiment_ops_adapter as adapter

RUNNER_VERSION = "runner-1.0"


def run(db, experiment: "ex.Experiment") -> Dict[str, Any]:
    """Execute one experiment through the frozen layer → ExperimentResult."""
    return ex.run_experiment(db, experiment)


def build_live_artifact(db, featured: "ex.Experiment",
                        history: Sequence["ex.Experiment"] = (),
                        *, generated_at: str,
                        artifact_version: str = "ops-1.0") -> Dict[str, Any]:
    """Run the featured experiment (+ any history experiments) and shape the results
    into ExperimentOpsArtifact v1 via the SAME adapter the snapshot generator uses.
    `source.kind == "live"` and `runner_version` are stamped; the KEYS match the
    snapshot artifact exactly (proven by the parity test)."""
    featured_result = run(db, featured)
    history_results = [run(db, h) for h in history]
    return adapter.to_artifact(
        featured_result, history_results,
        source_kind="live", generated_at=generated_at,
        artifact_version=artifact_version, runner_version=RUNNER_VERSION)
