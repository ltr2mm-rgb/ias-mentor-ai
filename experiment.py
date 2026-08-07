"""
experiment.py — Experiment layer (M5 Phase B).

A DEDICATED layer above the pipeline, distinct from planning and evaluation:

    Experiment → Assignment → Planning → Evaluation

Its only responsibilities: **define experiments, assign learners, define windows,
invoke the evaluator.** It never ranks concepts, never computes confidence, never
promotes a planner — those stay in the (now frozen) planning and evaluation
layers, which this module only *consumes*.

Design (per the Phase B review):

1. **Immutable, pre-registered experiments.** `Experiment` is a frozen object:
   once created it cannot be edited — not the window, not the metrics, not the
   sample threshold. Change → create a NEW experiment (ADR-supersession style).
   This is what keeps the confidence machinery honest: the window and criteria
   are fixed *before* anyone looks at results.

2. **Assignment is a PURE FUNCTION** — `arm = hash(assignment_version, id, user) % n`.
   Deterministic, replayable, persistent-by-construction (a learner never bounces
   arms), no mutable assignment table, trivially reproducible historically.

3. **An `EXPERIMENT_ENROLLED` event records a historical FACT** — "at this seq,
   this learner entered experiment X under assignment rule Y." The assignment
   stays a pure function; the event is the audit trail (who was in, when, under
   which rule) that makes windows, eligibility, and "why was this learner in that
   arm?" answerable from the event stream alone.

4. **Windows are SEQ-based, not timestamps.** seq is causal and is what replay /
   projections / MissionOutcome already use; timestamps are observational. A
   learner's window is `[enrollment_seq, end_seq]` over their own `created_seq`.
   (seq is per-user, so `end_seq` acts as a per-learner cap; `enrollment_seq` — an
   event fact — is the true per-learner start.)

The whole comparison is therefore reproducible from the event stream alone.
"""
from __future__ import annotations

import os
import json
import zlib
from dataclasses import dataclass, asdict, fields
from typing import Any, Dict, List, Optional, Tuple

import learner_events as le
import mission_outcome as mo
import mission_engine as me
import mission_evaluator as mev

EXPERIMENT_LAYER_VERSION = "experiment-1.0"
ASSIGNMENT_VERSION = "exp-assign-v1"
ENROLL_ACTIVITY = "EXPERIMENT_ENROLLED"


# ── immutable, pre-registered experiment spec ────────────────────────────────
@dataclass(frozen=True)
class Experiment:
    """Immutable experiment definition. Frozen → activation is pre-registration:
    no edits, no extending `end_seq`, no changing metrics or thresholds. To change
    anything, create a NEW experiment (supersede)."""
    id: str
    default_policy: str
    candidate_policy: str
    end_seq: int
    start_seq: int = 0
    assignment_version: str = ASSIGNMENT_VERSION
    minimum_sample: int = 20
    primary_metric: str = "avg_mastery_gain"
    guardrails: Tuple[str, ...] = ("completion_rate",)
    alpha: float = 0.05
    # descriptive + lifecycle metadata (NOT evaluation semantics; ADR-008: lifecycle
    # is orthogonal to the seq-based window). `activated_at` is wall-clock lifecycle
    # metadata only — it never enters replay or window math.
    title: str = ""
    hypothesis: str = ""
    status: str = "active"            # draft | review | active | closed | archived
    activated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["guardrails"] = list(self.guardrails)
        return d


# ── deterministic assignment — a PURE FUNCTION, never stored/mutated ─────────
def assigned_arm_index(user_id, experiment: Experiment) -> int:
    """0 → default arm, 1 → candidate arm. Stable hash (not Python's salted
    hash()) over (assignment_version, experiment_id, user_id): changing the
    algorithm changes `assignment_version`, so historical assignments stay
    reproducible."""
    key = "%s|%s|%s" % (experiment.assignment_version, experiment.id, user_id)
    return zlib.crc32(key.encode("utf-8")) % 2


def assign(user_id, experiment: Experiment) -> str:
    """The policy this learner competes under. Pure, deterministic, persistent by
    construction — same learner → same arm, forever, with no stored state."""
    return (experiment.candidate_policy if assigned_arm_index(user_id, experiment) == 1
            else experiment.default_policy)


# ── enrollment: record the historical fact (assignment itself stays pure) ────
def enroll(db, user_id, experiment: Experiment) -> Tuple[str, Dict[str, Any]]:
    """Emit `EXPERIMENT_ENROLLED` (idempotent per experiment·learner): "this
    learner entered experiment X under rule Y." Returns the assigned policy. The
    event's own `seq` is the enrollment_seq used for windowing."""
    arm = assign(user_id, experiment)
    ev = {
        "event_id": "enroll-%s-%s" % (experiment.id, user_id),
        "module": "experiment",
        "activity_type": ENROLL_ACTIVITY,
        "metadata": {
            "experiment_id": experiment.id,
            "assignment_version": experiment.assignment_version,
            "assigned_arm": arm,
            "default_policy": experiment.default_policy,
            "candidate_policy": experiment.candidate_policy,
            "primary_metric": experiment.primary_metric,
        },
    }
    res = le.ingest(db, user_id, [ev], valid_keys=le._valid_concept_keys(db))
    return arm, res


# ── planner wiring: generation CONSULTS assignment (Experiment → Planning) ───
def generate_for_user(db, user_id, experiment: Experiment, mission_id=None) -> Dict[str, Any]:
    """Enroll (idempotent audit) then generate under the learner's assigned arm.
    The mission's `policy_version` is stamped by the arm, so its outcome is
    automatically attributed to the right arm downstream."""
    arm, _ = enroll(db, user_id, experiment)
    return me.generate(db, user_id, policy=arm, mission_id=mission_id)


# ── active-experiment registry: the layer's ONE reader of what's live ────────
# `active_experiments.json` (optional) is the registry of what is currently
# running. The Experiment layer owns reading it, so BOTH the generation path
# (`generate_if_enrolled`) and the ops producer resolve "which experiment is
# active" through the SAME reader — they cannot disagree. Absent file → no active
# experiment → generation falls back to the default planner (safe no-op).
_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "active_experiments.json")


def load_active(path: Optional[str] = None) -> Tuple[Optional["Experiment"], List["Experiment"]]:
    """(featured Experiment | None, [history Experiments]) from the registry file.
    Only known `Experiment` fields are accepted; unknown keys are ignored so a
    config typo can never crash a caller. Pure read — no DB, no mutation."""
    p = path or _REGISTRY_PATH
    if not os.path.exists(p):
        return None, []
    with open(p, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    known = {fld.name for fld in fields(Experiment)}

    def mk(d: Dict[str, Any]) -> "Experiment":
        kw = {k: v for k, v in d.items() if k in known}
        if isinstance(kw.get("guardrails"), list):
            kw["guardrails"] = tuple(kw["guardrails"])
        return Experiment(**kw)

    featured = mk(cfg["featured"]) if cfg.get("featured") else None
    history = [mk(d) for d in cfg.get("history", [])]
    return featured, history


def featured_active(path: Optional[str] = None) -> Optional["Experiment"]:
    """The active featured Experiment, or None if no experiment is running."""
    return load_active(path)[0]


def generate_if_enrolled(db, user_id, mission_id=None, path: Optional[str] = None) -> Dict[str, Any]:
    """The SINGLE mission-generation entry point that respects the active experiment.
    If a featured experiment is running, enroll (idempotent audit) + generate under
    the learner's deterministically-assigned arm; otherwise fall back to the default
    planner unchanged. This keeps ALL experiment mechanics out of the web layer — the
    endpoint calls only this. Activating/deactivating an experiment is purely a
    matter of the registry file; no endpoint code changes."""
    featured = featured_active(path)
    if featured is None:
        return me.generate(db, user_id, mission_id=mission_id)
    return generate_for_user(db, user_id, featured, mission_id=mission_id)


# ── enrollments: the audit is the source of truth for who's in and when ──────
def enrollments(db, experiment: Experiment) -> Dict[int, int]:
    """{user_id: enrollment_seq} from EXPERIMENT_ENROLLED events for this
    experiment — recovered from the event stream, not from mutable state."""
    import models
    out: Dict[int, int] = {}
    rows = (db.query(models.LearnerEvent)
            .filter(models.LearnerEvent.activity_type == ENROLL_ACTIVITY)
            .order_by(models.LearnerEvent.id.asc()).all())
    for r in rows:
        meta = json.loads(r.meta) if r.meta else {}
        if meta.get("experiment_id") == experiment.id and r.user_id not in out:
            out[r.user_id] = r.seq
    return out


# ── seq-based window (per learner: [enrollment_seq, end_seq]) ────────────────
def _in_window(outcome: Dict[str, Any], enrollment_seq: int, experiment: Experiment) -> bool:
    cseq = outcome.get("created_seq")
    return cseq is not None and enrollment_seq <= cseq <= experiment.end_seq


def window_outcomes(db, experiment: Experiment) -> List[Dict[str, Any]]:
    """All in-window MissionOutcomes across enrolled learners, each already
    stamped with its arm's `policy_version` (so the evaluator groups by arm)."""
    outs: List[Dict[str, Any]] = []
    for uid, enr_seq in enrollments(db, experiment).items():
        payload = json.loads(mo.get_or_build(db, uid).payload)
        for o in payload.get("outcomes", []):
            if _in_window(o, enr_seq, experiment):
                outs.append(o)
    return outs


# ── run the experiment through the FROZEN evaluator ──────────────────────────
def _promotion_config(experiment: Experiment) -> Dict[str, Any]:
    """Map the immutable experiment onto the frozen promotion engine's config.
    (Direction defaults to 'higher' for the Phase-A metric set.)"""
    return {
        "primary": {"metric": experiment.primary_metric, "direction": "higher"},
        "guardrails": [{"metric": g, "direction": "higher"} for g in experiment.guardrails],
        "min_sample_size": experiment.minimum_sample,
    }


def run_experiment(db, experiment: Experiment) -> Dict[str, Any]:
    """Gather in-window outcomes across arms and hand them to the FROZEN
    `mission_evaluator`. This layer decides *what data* and *which criteria*; the
    evaluator decides *what happened / how certain / should the default change*."""
    enr = enrollments(db, experiment)
    outs = window_outcomes(db, experiment)
    result = mev.evaluate_from_outcomes(
        outs, experiment.default_policy, experiment.candidate_policy,
        _promotion_config(experiment), experiment.alpha)
    return {
        "experiment_layer_version": EXPERIMENT_LAYER_VERSION,
        "experiment": experiment.to_dict(),
        "enrolled": len(enr),
        "arm_counts": _arm_counts(enr, experiment),
        "in_window_outcomes": len(outs),
        "window": {"basis": "per-learner seq [enrollment_seq, end_seq]",
                   "start_seq": experiment.start_seq, "end_seq": experiment.end_seq},
        "result": result,
    }


def _arm_counts(enr: Dict[int, int], experiment: Experiment) -> Dict[str, int]:
    c = {experiment.default_policy: 0, experiment.candidate_policy: 0}
    for uid in enr:
        c[assign(uid, experiment)] += 1
    return c
