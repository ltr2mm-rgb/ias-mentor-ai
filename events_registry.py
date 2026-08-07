"""events_registry.py — authoritative EVENTS vocabulary (P23 / P24).

Source of truth: docs/EVENTS_REGISTRY.md (23 ids; vocabulary frozen 2026-08-03).
Producers reference EVENTS.<name> and emit via learner_events.emit(); they never
hard-code an event string and never touch `.legacy`. The migration bridge
(canonical id -> stored activity_type) lives in exactly one place: the emit adapter.
See ADR-003 (Learner Activity Stream).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Event:
    id: str                 # frozen canonical id (lower.dotted) — the unit that is frozen
    domain: str
    actor: str              # "learner" | "system"
    legacy: Optional[str]   # stored activity_type today (migration bridge); None if not yet emitted
    status: str             # "complete" | "planned"


class EVENTS:
    # complete — observable end-to-end today
    mcq_attempted        = Event("mcq.attempted", "learning", "learner", "MCQ_ATTEMPTED", "complete")
    mission_created      = Event("mission.created", "mission", "system", "MISSION_CREATED", "complete")
    mission_started      = Event("mission.started", "mission", "learner", "MISSION_STARTED", "complete")
    mission_completed    = Event("mission.completed", "mission", "learner", "MISSION_COMPLETED", "complete")
    mission_cancelled    = Event("mission.cancelled", "mission", "learner", "MISSION_CANCELLED", "complete")
    experiment_enrolled  = Event("experiment.enrolled", "experiment", "system", "EXPERIMENT_ENROLLED", "complete")
    baseline_established = Event("baseline.established", "learning", "system", "BASELINE_ESTABLISHED", "complete")
    # planned — kept orphan consumers + targets (producers wired incrementally in M7)
    revision_completed   = Event("revision.completed", "learning", "learner", "REVISION_COMPLETED", "planned")
    answer_evaluated     = Event("answer.evaluated", "learning", "system", "ANSWER_EVALUATED", "planned")
    assessment_started   = Event("assessment.started", "assessment", "learner", None, "planned")
    assessment_answered  = Event("assessment.answered", "assessment", "learner", "ASSESSMENT_ANSWERED", "planned")
    assessment_completed = Event("assessment.completed", "assessment", "learner", None, "planned")
    assessment_abandoned = Event("assessment.abandoned", "assessment", "learner", None, "planned")
    bootstrap_started    = Event("bootstrap.started", "bootstrap", "learner", None, "planned")
    bootstrap_completed  = Event("bootstrap.completed", "bootstrap", "learner", None, "planned")
    analysis_presented   = Event("analysis.presented", "bootstrap", "system", None, "planned")
    nav_opened           = Event("nav.opened", "navigation", "learner", None, "planned")
    mission_skipped      = Event("mission.skipped", "mission", "learner", None, "planned")
    lesson_completed     = Event("lesson.completed", "learning", "learner", None, "planned")
    resource_opened      = Event("resource.opened", "content", "learner", None, "planned")
    video_started        = Event("video.started", "content", "learner", None, "planned")
    note_created         = Event("note.created", "content", "learner", None, "planned")
    profile_updated      = Event("profile.updated", "profile", "learner", None, "planned")
