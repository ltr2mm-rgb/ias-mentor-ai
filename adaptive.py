"""
Adaptive weakness-targeting.

Turns a candidate's attempt history into a targeted set of freshly generated
questions aimed at their weak concepts — the "based on your last tests you are
weak in Inflation and Fiscal Deficit; here are 30 new questions" feature.

Two levels of granularity, so it works whether or not your existing questions
are concept-tagged yet:
  • concept-level  — when attempts carry a concept_id (ideal)
  • subject-level  — fall back to weak subjects, then target the highest-yield
                     (most PYQ-frequent) concepts within them

Scoring is deterministic and testable; generation uses question_generator.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional


def _accuracy(correct: int, total: int) -> float:
    return (correct / total) if total else 0.0


def weak_concepts(
    attempts: List[Dict[str, Any]],
    concept_index: Dict[str, Dict[str, Any]],
    min_attempts: int = 3,
    accuracy_threshold: float = 0.6,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Rank the candidate's weakest CONCEPTS.

    `attempts`: [{"concept_id"?: str, "subject"?: str, "correct": bool}, ...]
    `concept_index`: {concept_id: concept_record}
    Returns concept records annotated with accuracy/attempts, weakest first.
    """
    # concept-level tally
    c_correct: Dict[str, int] = defaultdict(int)
    c_total: Dict[str, int] = defaultdict(int)
    s_correct: Dict[str, int] = defaultdict(int)
    s_total: Dict[str, int] = defaultdict(int)

    for a in attempts:
        ok = 1 if a.get("correct") else 0
        cid = a.get("concept_id")
        subj = a.get("subject")
        if cid:
            c_total[cid] += 1
            c_correct[cid] += ok
        if subj:
            s_total[subj] += 1
            s_correct[subj] += ok

    ranked: List[Dict[str, Any]] = []

    # 1) concept-level weaknesses
    for cid, tot in c_total.items():
        if tot < min_attempts or cid not in concept_index:
            continue
        acc = _accuracy(c_correct[cid], tot)
        if acc <= accuracy_threshold:
            rec = dict(concept_index[cid])
            rec["_accuracy"] = round(acc, 3)
            rec["_attempts"] = tot
            rec["_reason"] = "low accuracy on this concept"
            ranked.append(rec)

    # 2) if we don't have enough concept-level signal, target weak subjects'
    #    highest-yield concepts
    if len(ranked) < top_k:
        weak_subjects = sorted(
            [(s, _accuracy(s_correct[s], t)) for s, t in s_total.items() if t >= min_attempts],
            key=lambda x: x[1],
        )
        by_subject = defaultdict(list)
        for rec in concept_index.values():
            by_subject[rec.get("subject")].append(rec)
        chosen_ids = {r["id"] for r in ranked}
        for subj, acc in weak_subjects:
            if acc > accuracy_threshold:
                continue
            cands = sorted(by_subject.get(subj, []), key=lambda r: -(r.get("pyq_frequency") or 0))
            for rec in cands:
                if rec["id"] in chosen_ids:
                    continue
                r = dict(rec)
                r["_accuracy"] = round(acc, 3)
                r["_attempts"] = s_total[subj]
                r["_reason"] = f"weak subject ({subj}); high-yield concept"
                ranked.append(r)
                chosen_ids.add(rec["id"])
                if len(ranked) >= top_k:
                    break
            if len(ranked) >= top_k:
                break

    ranked.sort(key=lambda r: (r.get("_accuracy", 1.0), -(r.get("pyq_frequency") or 0)))
    return ranked[:top_k]


def targeted_set(
    attempts: List[Dict[str, Any]],
    concept_index: Dict[str, Dict[str, Any]],
    per_concept: int = 6,
    top_k: int = 5,
    _gen=None,
) -> Dict[str, Any]:
    """Full flow: find weak concepts -> generate fresh questions for each."""
    from question_generator import generate, suggest_pattern

    weak = weak_concepts(attempts, concept_index, top_k=top_k)
    blocks = []
    for c in weak:
        pattern = suggest_pattern(c)
        qs = generate(c, pattern=pattern, difficulty="medium", n=per_concept, _gen=_gen)
        blocks.append(
            {
                "concept_id": c["id"],
                "concept": c["concept"],
                "subject": c["subject"],
                "why": c.get("_reason"),
                "your_accuracy": c.get("_accuracy"),
                "questions": qs,
            }
        )
    return {
        "focus_areas": [c["concept"] for c in weak],
        "total_questions": sum(len(b["questions"]) for b in blocks),
        "blocks": blocks,
    }
