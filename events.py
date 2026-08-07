"""
events.py — the Learning Event layer (AIVORA OS, arch v1.3; review recommendation
"make the delta itself an event").

A tiny synchronous, in-process publish/subscribe bus plus the canonical event
names for the adaptive loop. The point is source-independence: an MCQ answer, a
completed revision, an AI-Mentor session, a note review, a mock test or a spaced-
repetition tick all publish the SAME events, and every downstream consumer keeps
working without caring what produced the change.

    AttemptRecorded            (or RevisionCompleted / MockSubmitted / NoteReviewed / …)
          ↓
    ProfileUpdated             learner_kernel recomputed the Learner State
          ↓
    PredictionUpdated          prediction_engine re-forecast readiness
          ↓
    StateDeltaCreated          state_delta diffed old → new  (the reviewer's key idea)
          ↓
    ExplanationCreated         explanation_service narrated the change
          ↓
    MissionUpdated             decision_engine chose the next best action

This bus is deliberately minimal (no async, no persistence, no ordering guarantees
beyond synchronous call order) — right for pilot scale. It can be swapped for a
real broker later WITHOUT changing publishers or subscribers, because they depend
only on the event names + payload shape, not on the transport.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, List


# ── canonical event names ─────────────────────────────────────────────────────
class Events:
    # sources (any of these kicks off the same pipeline)
    ATTEMPT_RECORDED = "AttemptRecorded"
    REVISION_COMPLETED = "RevisionCompleted"
    MOCK_SUBMITTED = "MockSubmitted"
    NOTE_REVIEWED = "NoteReviewed"
    MENTOR_SESSION = "MentorSessionEnded"
    READING_LOGGED = "ReadingLogged"
    SPACED_REP_TICK = "SpacedRepTick"
    # pipeline stages
    PROFILE_UPDATED = "ProfileUpdated"
    PREDICTION_UPDATED = "PredictionUpdated"
    STATE_DELTA_CREATED = "StateDeltaCreated"
    EXPLANATION_CREATED = "ExplanationCreated"
    MISSION_UPDATED = "MissionUpdated"


# the set of events that are legitimate *sources* (trigger a full recompute)
SOURCE_EVENTS = frozenset({
    Events.ATTEMPT_RECORDED, Events.REVISION_COMPLETED, Events.MOCK_SUBMITTED,
    Events.NOTE_REVIEWED, Events.MENTOR_SESSION, Events.READING_LOGGED,
    Events.SPACED_REP_TICK,
})


class EventBus:
    """Minimal synchronous pub/sub. Handlers are called in subscription order;
    a handler raising is isolated (logged via on_error) so one bad subscriber
    can't break the chain — matching the 'best-effort intelligence' rule."""

    def __init__(self, on_error: Callable[[str, Exception], None] = None):
        self._subs: Dict[str, List[Callable[[Dict[str, Any]], None]]] = defaultdict(list)
        self._on_error = on_error or (lambda ev, e: None)
        self.log: List[str] = []          # names of published events (debug/telemetry)

    def subscribe(self, event: str, handler: Callable[[Dict[str, Any]], None]) -> None:
        self._subs[event].append(handler)

    def publish(self, event: str, payload: Dict[str, Any]) -> None:
        self.log.append(event)
        for h in list(self._subs.get(event, ())):
            try:
                h(payload)
            except Exception as e:            # isolate a failing subscriber
                self._on_error(event, e)

    def clear(self) -> None:
        self._subs.clear()
        self.log.clear()


if __name__ == "__main__":
    seen = []
    bus = EventBus(on_error=lambda ev, e: seen.append(("ERR", ev)))
    bus.subscribe(Events.STATE_DELTA_CREATED, lambda p: seen.append(("delta", p["readiness"])))
    bus.subscribe(Events.STATE_DELTA_CREATED, lambda p: (_ for _ in ()).throw(ValueError("boom")))
    bus.subscribe(Events.MISSION_UPDATED, lambda p: seen.append(("mission", p["action"])))
    bus.publish(Events.STATE_DELTA_CREATED, {"readiness": 58})
    bus.publish(Events.MISSION_UPDATED, {"action": "revise"})
    print("seen:", seen, "| log:", bus.log)
    assert ("delta", 58) in seen and ("ERR", "StateDeltaCreated") in seen and ("mission", "revise") in seen
    assert bus.log == ["StateDeltaCreated", "MissionUpdated"]
    print("OK — pub/sub delivers, isolates a failing subscriber, logs event order.")
