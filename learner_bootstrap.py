"""
learner_bootstrap.py — Learner Bootstrap Engine (B.0a domain layer).

Turns an *unknown learner* into a *learner with evidence*. It OWNS NOTHING: it is a pure
PROJECTION over the three EXISTING sources of truth, and it emits no events of its own —

  - Account / Profile  (student_profiles: target_year, mains_language, attempts, diagnostic_gs/csat)
  - Diagnostic         (diagnostic_gs / diagnostic_csat baselines on the profile)
  - Mission Engine     (MISSION_CREATED / MISSION_STARTED, via mission_engine.mission_state)

It answers ONE question: "given everything we already know, where is this learner in
initialization, and what should they see next?" Representation, not authority (cf. ADR-011
Mission Progress). Reuse-first: NO new events, NO new authoritative writes — every state is
derived from data the other engines already own.

Knowledge states (NOT UI actions) — highest reached wins:

    UNKNOWN -> REGISTERED -> PROFILE_READY -> LEARNING_BASELINE_READY -> MISSION_READY -> BOOTSTRAPPED

- PROFILE_READY            : the 3-tap profile is complete (target_year + language + attempts).
- LEARNING_BASELINE_READY  : the assessment produced a baseline (diagnostic_gs AND diagnostic_csat set).
- MISSION_READY            : a first mission exists (first MISSION_CREATED).
- BOOTSTRAPPED             : the learner has STARTED a mission — the first real moment of learning.

No percentages, timestamps, or analytics live here — those belong to Instrumentation.
`build_bootstrap_projection` is the domain entry point; `GET /me/bootstrap` is a thin wrapper.

UI CONTRACT: the frontend drives UX off **`next_action`**, **`can_resume`**, and **`resume_from`** —
NOT off `state`. `state` is domain/diagnostic information; a given state must never dictate a specific
screen (today REGISTERED → profile; tomorrow it might mean "welcome back" or "verify email"). Keeping the
UI on the action/resume fields lets the experience evolve without touching this state machine.

The state enum is FROZEN — do not add email_verified / payment_complete / optional_subject /
profile_version, etc. Those belong to other engines. This engine answers exactly one question:
"how far has this learner progressed from unknown to evidence-based learning?"
"""
from enum import Enum
from typing import Any, Dict


class OnboardingState(str, Enum):
    UNKNOWN = "UNKNOWN"
    REGISTERED = "REGISTERED"
    PROFILE_READY = "PROFILE_READY"
    LEARNING_BASELINE_READY = "LEARNING_BASELINE_READY"
    MISSION_READY = "MISSION_READY"
    BOOTSTRAPPED = "BOOTSTRAPPED"


# canonical maturity order — index == how far the learner has progressed
_ORDER = [
    OnboardingState.UNKNOWN,
    OnboardingState.REGISTERED,
    OnboardingState.PROFILE_READY,
    OnboardingState.LEARNING_BASELINE_READY,
    OnboardingState.MISSION_READY,
    OnboardingState.BOOTSTRAPPED,
]

# the learner's next action per state — UI-agnostic verbs; the UI maps these to screens.
_NEXT_ACTION = {
    OnboardingState.UNKNOWN: "register",
    OnboardingState.REGISTERED: "complete_profile",
    OnboardingState.PROFILE_READY: "start_assessment",
    OnboardingState.LEARNING_BASELINE_READY: "build_first_mission",
    OnboardingState.MISSION_READY: "start_mission",
    OnboardingState.BOOTSTRAPPED: "enter_learning",
}

# stable resume anchors — where the UI drops a returning learner back mid-initialization.
# DELIBERATELY not the enum: the resume contract is decoupled from the knowledge state, so
# screens can change without touching the state machine.
_RESUME_FROM = {
    OnboardingState.UNKNOWN: "welcome",
    OnboardingState.REGISTERED: "profile",
    OnboardingState.PROFILE_READY: "assessment_intro",
    OnboardingState.LEARNING_BASELINE_READY: "analysis",
    OnboardingState.MISSION_READY: "mission_control",
    OnboardingState.BOOTSTRAPPED: "mission_control",
}


def _blank(x) -> bool:
    return x is None or (isinstance(x, str) and x.strip() == "")


def derive_bootstrap_state(ev: Dict[str, Any]) -> OnboardingState:
    """PURE. Highest milestone reached wins. `ev` carries only existence flags:
    account_exists, profile_ready, baseline_ready, mission_created, mission_started."""
    if ev.get("mission_started"):
        return OnboardingState.BOOTSTRAPPED
    if ev.get("mission_created"):
        return OnboardingState.MISSION_READY
    if ev.get("baseline_ready"):
        return OnboardingState.LEARNING_BASELINE_READY
    if ev.get("profile_ready"):
        return OnboardingState.PROFILE_READY
    if ev.get("account_exists"):
        return OnboardingState.REGISTERED
    return OnboardingState.UNKNOWN


def project(ev: Dict[str, Any]) -> Dict[str, Any]:
    """PURE projection: evidence -> {state, next_action, resume_from, can_resume,
    completed_steps, current_step, first_mission_id}. No DB, no side effects.
    UI drivers are next_action / can_resume / resume_from; state is domain-only."""
    state = derive_bootstrap_state(ev)
    # completed_steps = milestones ACTUALLY achieved (evidence-based, NOT order-based). Reality is
    # non-monotonic: a learner can reach a mission via practice WITHOUT the formal diagnostic baseline,
    # so we must not infer "baseline done" just because a later milestone was reached.
    _achieved = []
    if ev.get("account_exists"): _achieved.append(OnboardingState.REGISTERED)
    if ev.get("profile_ready"): _achieved.append(OnboardingState.PROFILE_READY)
    if ev.get("baseline_ready"): _achieved.append(OnboardingState.LEARNING_BASELINE_READY)
    if ev.get("mission_created"): _achieved.append(OnboardingState.MISSION_READY)
    if ev.get("mission_started"): _achieved.append(OnboardingState.BOOTSTRAPPED)
    completed = [s.value for s in _achieved if s != state]  # achieved milestones other than the current
    can_resume = state not in (OnboardingState.UNKNOWN, OnboardingState.BOOTSTRAPPED)
    return {
        "state": state.value,                  # domain/diagnostic only — UI must not switch on this
        "next_action": _NEXT_ACTION[state],    # primary UI driver
        "resume_from": _RESUME_FROM[state],    # stable resume anchor (not the enum)
        "can_resume": can_resume,
        "completed_steps": completed,
        "current_step": state.value,
        "first_mission_id": ev.get("first_mission_id"),
    }


def _evidence(db, user_id: int) -> Dict[str, Any]:
    """The ONLY impure part: read evidence from the three existing sources. Loads nothing
    the other engines don't already own; writes nothing."""
    import models
    import mission_engine as me
    p = (db.query(models.StudentProfile)
           .filter(models.StudentProfile.user_id == user_id).first())
    profile_ready = bool(p) and not _blank(getattr(p, "target_year", None)) \
        and not _blank(getattr(p, "mains_language", None)) \
        and not _blank(getattr(p, "attempts", None))
    baseline_ready = bool(p) and getattr(p, "diagnostic_gs", None) is not None \
        and getattr(p, "diagnostic_csat", None) is not None
    ms = me.mission_state(db, user_id) or {}
    missions = ms.get("missions") or []
    mission_created = len(missions) > 0
    mission_started = any(m.get("started_seq") is not None for m in missions)
    first_mission_id = missions[0].get("mission_id") if missions else None
    return {
        # callers are authenticated, so the account always exists at this point
        "account_exists": True,
        "profile_ready": profile_ready,
        "baseline_ready": baseline_ready,
        "mission_created": mission_created,
        "mission_started": mission_started,
        "first_mission_id": first_mission_id,
    }


def build_bootstrap_projection(db, user_id: int) -> Dict[str, Any]:
    """Domain entry point — thin loader over the pure projection.
    `GET /me/onboarding` is a trivial wrapper over this."""
    return project(_evidence(db, user_id))
