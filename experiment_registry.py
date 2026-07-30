"""
experiment_registry.py — first-class recommendation experiments (arch v1.4; review
"add an Experiment Registry").

Encoding experiments in `engine_version` strings works technically but loses the
operational story: when did decision-v1.5 start, who was assigned, why was it
stopped, was it rolled back? This module makes an Experiment a real object with a
lifecycle, and assigns learners to arms deterministically.

Boundaries (important):
  • The intelligence engine does NOT read this — a decision is made the same way
    regardless. The registry only *labels* which experiment/arm produced it.
  • The learner never sees it.
  • It exists for operations, dashboards, and future research.

Assignment is a deterministic hash of (experiment_id, user_id) → stable per learner
across sessions and restarts (not Python's per-process-salted hash()). One running
experiment at a time in v1 (the `eligibility='all'` case).
"""

from __future__ import annotations

import datetime
import hashlib
from typing import Any, Dict, List, Optional

# lifecycle transitions
STATUSES = {"draft", "running", "stopped", "promoted", "rolled_back"}
DEFAULT_POLICY = "decision-v1.4"          # what runs when no experiment is active


def create(db, name: str, control_policy: str, treatment_policy: str,
           description: str = "", split: float = 0.5, owner: str = None,
           notes: str = "") -> Optional[int]:
    import models
    # bind the experiment to the exact deployed build at creation time, so it
    # stays reproducible even after later platform versions exist (review rec).
    try:
        import platform_version
        m = platform_version.manifest()
        pv, sha = m["platform_version"], m["build"]["git_sha"]
    except Exception:
        pv, sha = None, None
    try:
        exp = models.Experiment(name=name, description=description, status="draft",
                                control_policy=control_policy, treatment_policy=treatment_policy,
                                eligibility="all", split=split, owner=owner, notes=notes,
                                platform_version=pv, git_sha=sha,
                                created_at=datetime.datetime.utcnow())
        db.add(exp)
        db.commit()
        return exp.id
    except Exception:
        db.rollback()
        return None


def set_status(db, experiment_id: int, status: str, note: str = None) -> bool:
    """Transition an experiment. running → stamps started_at; a terminal status
    (stopped/promoted/rolled_back) → stamps ended_at."""
    import models
    if status not in STATUSES:
        return False
    try:
        exp = db.query(models.Experiment).filter(models.Experiment.id == experiment_id).first()
        if not exp:
            return False
        exp.status = status
        now = datetime.datetime.utcnow()
        if status == "running" and not exp.started_at:
            exp.started_at = now
        if status in ("stopped", "promoted", "rolled_back"):
            exp.ended_at = now
        if note:
            exp.notes = ((exp.notes or "") + f"\n[{now.isoformat()}] {note}").strip()
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False


def active(db):
    """The single running experiment, or None (v1: one at a time)."""
    import models
    try:
        return (db.query(models.Experiment)
                .filter(models.Experiment.status == "running")
                .order_by(models.Experiment.started_at.desc()).first())
    except Exception:
        return None


def _arm(experiment_id: int, user_id: int, split: float) -> str:
    """Stable, uniform hash assignment. split = fraction to treatment."""
    h = hashlib.md5(f"{experiment_id}:{user_id}".encode()).hexdigest()
    frac = int(h[:8], 16) / 0xFFFFFFFF
    return "treatment" if frac < split else "control"


def resolve(db, user_id: int) -> Dict[str, Any]:
    """Which experiment/arm/policy applies to this learner right now. When no
    experiment is running, returns the default policy and a null experiment — so
    the pipeline always gets a policy_version to stamp."""
    exp = active(db)
    if not exp:
        return {"experiment_id": None, "arm": None, "policy_version": DEFAULT_POLICY}
    arm = _arm(exp.id, user_id, exp.split if exp.split is not None else 0.5)
    policy = exp.treatment_policy if arm == "treatment" else exp.control_policy
    return {"experiment_id": exp.id, "arm": arm, "policy_version": policy or DEFAULT_POLICY}


def as_dict(exp) -> Dict[str, Any]:
    return {"id": exp.id, "name": exp.name, "description": exp.description, "status": exp.status,
            "control_policy": exp.control_policy, "treatment_policy": exp.treatment_policy,
            "split": exp.split, "owner": exp.owner, "notes": exp.notes,
            "platform_version": exp.platform_version, "git_sha": exp.git_sha,
            "started_at": exp.started_at.isoformat() if exp.started_at else None,
            "ended_at": exp.ended_at.isoformat() if exp.ended_at else None,
            "created_at": exp.created_at.isoformat() if exp.created_at else None}


def listing(db) -> List[Dict[str, Any]]:
    import models
    try:
        return [as_dict(e) for e in db.query(models.Experiment)
                .order_by(models.Experiment.id.desc()).all()]
    except Exception:
        return []
