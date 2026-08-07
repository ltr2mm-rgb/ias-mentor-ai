"""concept_alignment.py — READ-ONLY diagnostic for concept-vocabulary alignment.

Owns exactly ONE thing: measuring whether the question bank's concept vocabulary
and the concept inventory's vocabulary line up. It answers the question behind the
C1 blocker — "can a fresh learner be given a first mission, and if not, why not?" —
without anyone needing database access.

It does NOT:
  - repair anything          (the repair is POST /admin/concepts/seed-topics,
                              which already exists and is idempotent + additive)
  - define "answerable"      (mission_engine.question_count owns that definition)
  - define the canonical key (learner_events.canon_concept_key owns that)
  - write to the database    — EVER. Every function here is SELECT-only.

Why the numbers below are the right ones (the runtime chain they mirror):

    /me/attempt records a concept on an MCQ_ATTEMPTED event only if
    canon(question.concept_key) is present in ConceptInventory.key — the
    learner_events._valid_concept_keys gate. A question whose key is not an
    inventory key has its concept silently dropped, the projection never learns
    the concept, and mission_engine.generate() returns "no_answerable_concept".

So the single number that decides whether missions can form is the size of the
INTERSECTION between the canonicalised question keys and the inventory keys.

Portability: comparisons are done in Python over two bounded key sets rather than
in SQL, so this behaves identically on SQLite and Postgres and never builds a huge
IN (...) clause.
"""
from __future__ import annotations

from typing import Any, Dict, List

DIAGNOSTIC_VERSION = "concept-alignment-1.0"

# How many example keys to return per bucket. Small: this is a UI aid, not a dump.
_SAMPLE_LIMIT = 10


def _canon(value: str) -> str:
    """Canonical key form — delegated to the producer's own rule so the two can
    never drift (learner_events.canon_concept_key: trim + collapse whitespace,
    case preserved)."""
    import learner_events as le
    return le.canon_concept_key(value)


def _inventory_keys(db) -> List[str]:
    """Every ConceptInventory.key. READ-ONLY."""
    import models
    return [k for (k,) in db.query(models.ConceptInventory.key).all() if k]


def _question_key_counts(db) -> List[tuple]:
    """(raw concept_key, row_count) for every non-empty Question.concept_key.
    One grouped query; bounded by the number of DISTINCT keys, not rows. READ-ONLY."""
    import models
    from sqlalchemy import func
    return (db.query(models.Question.concept_key, func.count(models.Question.id))
              .filter(models.Question.concept_key.isnot(None),
                      models.Question.concept_key != "")
              .group_by(models.Question.concept_key)
              .all())


# SQLite allows at most 999 bound parameters per statement, so an IN (...) over a
# large inventory must be chunked. Kept well under the limit.
_IN_CHUNK = 400


def _answerable_inventory_keys(db, keys: List[str]) -> set:
    """Inventory keys that have at least one servable question.

    Delegates to mission_engine.answerable_keys — THE single definition of
    "answerable" (Rule 6). We must report the number the mission engine will
    actually act on, not a second opinion computed here. Chunked so a large
    inventory cannot blow the driver's bound-parameter limit. READ-ONLY."""
    import mission_engine as me
    out: set = set()
    for i in range(0, len(keys), _IN_CHUNK):
        out |= me.answerable_keys(db, keys[i:i + _IN_CHUNK])
    return out


def diagnose(db, sample_limit: int = _SAMPLE_LIMIT) -> Dict[str, Any]:
    """Measure concept-vocabulary alignment. Pure read; returns a plain dict that
    the admin UI renders directly."""
    inv_keys_raw = _inventory_keys(db)
    inv_keys = set(inv_keys_raw)
    composite = sum(1 for k in inv_keys_raw if "|" in k)

    rows = _question_key_counts(db)
    keyed_rows = sum(int(n or 0) for _k, n in rows)

    # Canonicalise question keys exactly as the runtime gate does, pooling the row
    # counts of any raw variants that canonicalise to the same key.
    canon_counts: Dict[str, int] = {}
    for raw, n in rows:
        c = _canon(raw)
        if c:
            canon_counts[c] = canon_counts.get(c, 0) + int(n or 0)

    matched = sorted(k for k in canon_counts if k in inv_keys)
    unmatched = sorted(k for k in canon_counts if k not in inv_keys)
    registerable_rows = sum(canon_counts[k] for k in matched)
    would_drop_rows = sum(canon_counts[k] for k in unmatched)

    distinct_keys = len(canon_counts)
    match_pct = round(100.0 * len(matched) / distinct_keys, 1) if distinct_keys else 0.0

    # The concepts a mission can actually be built on. Sourced from mission_engine's
    # own definition rather than inferred here, so this figure can never disagree
    # with what mission generation will really do.
    answerable = len(_answerable_inventory_keys(db, inv_keys_raw))
    can_generate = answerable > 0

    if not inv_keys:
        status, summary = "empty_inventory", (
            "The concept inventory is empty, so no concept can be validated and no "
            "mission can be generated.")
    elif not distinct_keys:
        status, summary = "no_keyed_questions", (
            "No question carries a concept tag, so there is nothing for a mission to "
            "draw on.")
    elif answerable == 0:
        status, summary = "misaligned", (
            "The two topic vocabularies do not overlap at all: none of the "
            f"{distinct_keys:,} topic labels used by the {keyed_rows:,} tagged questions "
            f"appears among the {len(inv_keys):,} labels in the concept inventory. "
            "Every new learner therefore reaches 'no answerable concept' and cannot be "
            "given a first mission.")
    elif unmatched:
        status, summary = "partial", (
            f"{answerable:,} of {distinct_keys:,} question topics ({match_pct}%) are "
            f"recognised, so missions can form — but {len(unmatched):,} topics covering "
            f"{would_drop_rows:,} questions are still invisible to the system.")
    else:
        status, summary = "aligned", (
            f"All {distinct_keys:,} question topics are recognised by the concept "
            f"inventory. {answerable:,} concepts are available for missions.")

    return {
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "status": status,
        "summary": summary,
        "inventory": {
            "total_keys": len(inv_keys),
            "composite_keys": composite,        # keys of the "<concept>|<subject>" form
            "plain_keys": len(inv_keys) - composite,
        },
        "questions": {
            "keyed_rows": keyed_rows,
            "distinct_keys": distinct_keys,
        },
        "alignment": {
            "matched_keys": len(matched),
            "unmatched_keys": len(unmatched),
            "match_pct": match_pct,
            "registerable_rows": registerable_rows,
            "would_drop_rows": would_drop_rows,
        },
        "mission_impact": {
            "answerable_concepts": answerable,
            "can_generate_missions": can_generate,
        },
        "samples": {
            "matched": matched[:sample_limit],
            "unmatched": unmatched[:sample_limit],
        },
        "repair": {
            "available": bool(unmatched),
            "action": "POST /admin/concepts/alignment/repair",
            "effect": ("Adds the missing question topics to the concept inventory so "
                       "they become usable for missions."),
            "safety": ("Additive and idempotent: it only ADDS inventory entries that are "
                       "missing. It never edits or deletes questions, and never removes "
                       "an existing inventory entry."),
            "would_add_keys": len(unmatched),
        },
    }
