"""subject_concept_translator.py — the subject->concept bridge (cold-start).

Pure, stateless translation of the diagnostic's SUBJECT-level evidence into
CONCEPT-level evidence the mission generator can consume. It owns exactly one
thing: converting `by_subject` (from diagnostic.score) into a per_concept seed
keyed by canonical concept_key.

It does NOT:
  - score answers            (the diagnostic owns scoring)
  - decide missions          (the mission engine owns selection)
  - write the DB / emit events / mutate the projection
                             (the CALLER owns persistence — see the bootstrap
                              first-mission integration)

Vocabulary ownership: the diagnostic owns its subject labels; the concept
inventory owns concept subjects. This module holds the SMALL, explicit
normalisation between them — the one place the two vocabularies meet — and it
CONSUMES the diagnostic vocabulary rather than maintaining a second copy of it.
"""
from typing import Any, Dict, List


# The diagnostic's subject labels are already canonical EXCEPT these two, which
# are prefixes of the concept inventory's labels. Everything else passes through.
_SUBJECT_NORMALISE = {
    "Polity": "Polity & Governance",
    "Environment": "Environment & Ecology",
}

# Bound the seed: enough answerable concepts per subject to give the generator a
# real pool, capped so we never seed thousands of rows. Highest exam-frequency first.
_PER_SUBJECT_CAP = 8


def normalise_subject(subject: str) -> str:
    """Diagnostic subject label -> concept-inventory canonical label."""
    return _SUBJECT_NORMALISE.get(subject, subject)


def _answerable_concept_keys(db, canonical_subject: str, cap: int) -> List[str]:
    """Concept keys under a canonical subject that have >=1 servable question,
    highest exam-frequency first, capped. READ-ONLY."""
    import models
    import mission_engine as me
    rows = (db.query(models.ConceptInventory.key, models.ConceptInventory.frequency)
              .filter(models.ConceptInventory.subject == canonical_subject)
              .order_by(models.ConceptInventory.frequency.desc())
              .all())
    keys = [k for k, _f in rows if k]
    if not keys:
        return []
    answerable = me.answerable_keys(db, keys)   # the single 'answerable' definition, one query
    return [k for k in keys if k in answerable][:cap]


def translate(by_subject: Dict[str, Any], db, per_subject_cap: int = _PER_SUBJECT_CAP) -> Dict[str, Any]:
    """Convert diagnostic subject scores into a per_concept seed.

    Input:  by_subject = {"<diagnostic subject>": {"score": 0-100, "asked", "correct"}}
    Output: {concept_key: {"mastery": 0-1, "attempts": int, "correct": int,
                           "source": "diagnostic", "subject": "<canonical>"}}

    mastery = subject score / 100 — the generator ranks lowest-mastery first, so a
    learner's weakest measured subjects are naturally targeted. Concepts within a
    subject share that subject's mastery: the diagnostic measured at subject
    granularity, so the seed is honest about the resolution of its evidence. This
    is TRANSLATION, not judgement — no new scoring or weighting is invented here.
    """
    seed: Dict[str, Any] = {}
    for subject, sc in (by_subject or {}).items():
        if not sc or not sc.get("asked"):
            continue
        canonical = normalise_subject(subject)
        keys = _answerable_concept_keys(db, canonical, per_subject_cap)
        if not keys:
            continue
        mastery = round((sc.get("score", 0) or 0) / 100.0, 4)
        for k in keys:
            seed.setdefault(k, {           # first subject to claim a key wins; deterministic
                "mastery": mastery,
                "attempts": int(sc.get("asked", 0) or 0),
                "correct": int(sc.get("correct", 0) or 0),
                "source": "diagnostic",
                "subject": canonical,
            })
    return seed
