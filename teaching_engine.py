"""Teaching Engine — V1 (architecture §1 "Teaching Engine": instructional strategy).

The "chef": given a learner's situation, it decides HOW to teach — which recipe, in
what order — and assembles the lesson from the Pedagogy Kernel (reuse verified assets;
generate + language-adapt the rest through the AI Execution Runtime), ending with an
inline mini-check.

Deliberately a THIN vertical slice — no Teaching Graph, no adaptive policy, no bandits,
no self-learning. Its only job is to prove the pipeline:

    learner (concept · barrier · stage · archetype)
        → choose recipe → assemble (reuse or generate+adapt) → mini-check → return

Boundary: it owns instructional strategy. It does NOT decide WHAT to teach or WHEN
(Decision Engine), and it never talks to a model SDK directly (AI Execution Runtime).
"""
from __future__ import annotations

import pedagogy_kernel as pk
import ai_runtime

# Component versions, stamped onto every lesson + outcome so a change in learning
# results can be attributed to the RECIPE / question strategy rather than the
# content (which is versioned separately as pk.KERNEL_VERSION). Bump when the recipe
# set / ordering (RECIPE_VERSION) or the mini-check generator (MINICHECK_VERSION) change.
RECIPE_VERSION = "1.0"
MINICHECK_VERSION = "1.0"

# ── Learner archetypes (V1: a small fixed set; the Digital Twin will emit these) ─
# Each maps to a one-line language-adaptation instruction used when generating/adapting.
ARCHETYPES = {
    "beginner":     "Explain simply, define every term, short sentences, concrete before abstract.",
    "example-first": "Lead with a concrete example, then draw out the principle.",
    "advanced":     "Be precise and analytical; assume strong fundamentals; add depth and nuance.",
    "weak-english": "Use very simple English and short sentences; avoid idioms and long clauses.",
    "revision":     "Be concise; focus on recall cues and exactly what is tested.",
}
DEFAULT_ARCHETYPE = "beginner"

# ── Barrier → recipe policy (V1: static table; V2 learns this from outcomes) ────
BARRIER_RECIPE = {
    "confusion":   "comparison-first",   # confused with a neighbouring concept
    "application": "example-first",      # understands theory, can't apply it
    "new-concept": "story-first",        # first exposure
    "revision":    "exam-drill",         # seen before, needs recall + traps
}
DEFAULT_BARRIER = "new-concept"

# One-line rationale per barrier (Explanation Engine seed — architecture §6). Turns
# "here is a lesson" into "here is WHY this lesson", which builds learner trust.
WHY = {
    "confusion":   "it's easily confused with a neighbouring concept, so we teach it by direct comparison",
    "application": "you likely grasp the idea but need to apply it, so we lead with a worked example",
    "new-concept": "it's a fresh concept, so we open with a story to make it stick",
    "revision":    "you've met this before, so we go straight to how it's tested and the traps",
}


def detect_barrier(barrier=None, stage=None):
    """V1 barrier 'detection': trust an explicit barrier if valid; else infer a
    sensible default from stage. (V2 will infer from Digital Twin + assessment.)"""
    if barrier in BARRIER_RECIPE:
        return barrier
    return DEFAULT_BARRIER


def select_recipe(barrier, archetype):
    """Pick the lesson structure. Barrier drives it; the 'revision' archetype forces
    the fast exam-drill regardless (a learner in revision mode wants recall, not story)."""
    if archetype == "revision":
        return "exam-drill"
    return BARRIER_RECIPE.get(barrier, "comparison-first")


def _adapt_note(archetype):
    return ARCHETYPES.get(archetype, ARCHETYPES[DEFAULT_ARCHETYPE])


def teach(db, concept, subject=None, barrier=None, archetype=None, stage=None):
    """Assemble a full lesson. Returns a dict with the chosen recipe, ordered steps
    (each reused-from-kernel or freshly generated+adapted), the inline mini-check,
    and a reuse/generate summary. Raises RuntimeError only if generation fully fails."""
    concept = (concept or "").strip().lower().replace(" ", "-")
    if not concept:
        raise ValueError("concept is required")
    archetype = archetype if archetype in ARCHETYPES else DEFAULT_ARCHETYPE
    barrier = detect_barrier(barrier, stage)
    recipe_key = select_recipe(barrier, archetype)
    recipe = pk.RECIPES[recipe_key]
    note = _adapt_note(archetype)

    # Teaching steps = the recipe minus the mini-check (which is served separately as
    # a STRUCTURED, interactive question so the lesson screen can grade it inline).
    steps, reused, generated = [], 0, 0
    for tt in [t for t in recipe["steps"] if t != "mini-check"]:
        label = pk.TASK_TYPES.get(tt, {}).get("label", tt)
        asset = pk.get_asset(db, concept, tt)          # reuse-before-generate
        if asset:
            steps.append({"task_type": tt, "label": label, "source": "reused",
                          "asset_id": asset.id, "provider": asset.provider,
                          "content": asset.content})
            reused += 1
        else:
            prompt = pk.build_prompt(tt, concept, subject) + f"\n\nAudience: {note}"
            res = ai_runtime.route(task="pedagogy.asset", prompt=prompt, archetype=archetype,
                                   spec={"concept": concept, "task_type": tt, "adapt": archetype})
            steps.append({"task_type": tt, "label": label, "source": "generated",
                          "asset_id": None, "provider": (res.decision or {}).get("provider"),
                          "content": (res.output or "").strip()})
            generated += 1

    check = _generate_check(concept, subject, archetype, note)
    objectives = pk.get_asset(db, concept, "learning-objectives")   # reuse-only framing
    return {
        "concept": concept, "subject": subject, "barrier": barrier,
        "archetype": archetype, "stage": stage,
        "recipe": recipe_key, "recipe_label": recipe["label"],
        "versions": {"kernel": pk.KERNEL_VERSION, "recipe": RECIPE_VERSION,
                     "minicheck": MINICHECK_VERSION},
        "why": f"We're teaching {concept.replace('-', ' ')} with a {recipe['label'].lower()} "
               f"approach because {WHY.get(barrier, WHY[DEFAULT_BARRIER])}.",
        "objectives": objectives.content if objectives else None,
        "steps": steps, "check": check,
        "reused": reused, "generated": generated,
        # honest signal: teaching steps wholly reused from verified assets are instant
        # & trusted; generated steps are live/unverified until an admin promotes them.
        "fully_verified": generated == 0,
    }


def _generate_check(concept, subject, archetype, note):
    """Structured mini-check for inline grading. Returns
    {question, options:{A..D}, correct, explanation} or None on failure."""
    human = concept.replace("-", " ")
    subj = f" (subject: {subject})" if subject else ""
    prompt = (
        f"Write ONE exam-style multiple-choice question that checks real understanding of "
        f"'{human}'{subj} for a UPSC aspirant. Return STRICT JSON only, no prose:\n"
        f'{{"question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}}, '
        f'"correct": "A|B|C|D", "explanation": "one-line why the answer is correct"}}\n'
        f"Audience: {note}"
    )
    try:
        res = ai_runtime.route(task="mcq.generate", prompt=prompt, json_mode=True,
                               archetype=archetype, spec={"concept": concept, "task_type": "mini-check"})
        c = res.json
        if isinstance(c, dict) and c.get("question") and isinstance(c.get("options"), dict) \
                and (c.get("correct") or "").upper() in ("A", "B", "C", "D"):
            c["correct"] = c["correct"].upper()
            return c
    except Exception:
        pass
    return None
