"""Pedagogy Kernel (architecture §1.2) — teaching knowledge, structured as
RECIPES × ASSETS.

- A **recipe** is a subject-agnostic lesson structure (a sequence of task types).
  One recipe works across Polity, History, CSAT, … — only the asset changes.
- An **asset** is concept-specific content for one task type (an analogy, a
  comparison, a worked example, …). Assets are generated ONCE (learner-agnostic)
  through the AI Execution Runtime, gated by MANUAL verification (v1), stored
  versioned, and then REUSED for every learner (reuse-before-generate).

Recipes are code-defined here for v1 (few, static, subject-agnostic); assets live
in the `teaching_assets` table. This module owns generation, the pre-check, reuse
lookup, and Recipe × Asset composition. It never makes educational decisions about
*which* concept to teach — that is the Decision/Teaching engines (Steps 3+).
"""
from __future__ import annotations

import json
import re

import ai_runtime
from models import TeachingAsset

# Frozen content version — bump ONLY when verified assets change (governance:
# verified assets are immutable; improvements ship as a new version). Stamped onto
# every lesson outcome so learning-effect changes are attributable to content.
KERNEL_VERSION = "1.0"

# ── Task types (the atomic teaching assets a recipe is built from) ────────────
# Each: label + a generation-prompt template. Prompts are deliberately tight so the
# LLM only *fills* the asset (architecture §4, "spec, not prompt"). {concept}/{subject}
# are substituted. Keep outputs self-contained markdown (no external links/branding).
TASK_TYPES = {
    "analogy": {
        "label": "Analogy",
        "prompt": ("Write ONE clear, everyday analogy that helps a UPSC aspirant intuitively "
                   "understand the concept '{concept}'{subject}. 3–5 sentences. Plain language, "
                   "no jargon. Return only the analogy."),
    },
    "concept-explainer": {
        "label": "Concept explainer",
        "prompt": ("Explain the concept '{concept}'{subject} for a UPSC Prelims aspirant in a tight, "
                   "accurate way. 5–8 sentences, exam-relevant, no filler. Return only the explanation."),
    },
    "comparison": {
        "label": "Comparison table",
        "prompt": ("Create a compact comparison that clarifies '{concept}'{subject} against the concept "
                   "it is most often confused with. Use a small markdown table (Aspect | A | B) with "
                   "4–6 rows. Return only the table (and a one-line caption)."),
    },
    "worked-example": {
        "label": "Worked example",
        "prompt": ("Give ONE worked example that applies '{concept}'{subject} the way UPSC tests it. "
                   "Show the reasoning step by step, then the answer. Return only the worked example."),
    },
    "mnemonic": {
        "label": "Mnemonic",
        "prompt": ("Create ONE memorable mnemonic (and a one-line explanation of what each part stands "
                   "for) to recall the key points of '{concept}'{subject}. Return only the mnemonic + key."),
    },
    "pyq-insight": {
        "label": "PYQ insight",
        "prompt": ("Describe how UPSC has previously framed questions on '{concept}'{subject} — the common "
                   "angles and what a well-prepared aspirant should watch for. 4–6 sentences. Do NOT invent "
                   "specific question numbers or years. Return only the insight."),
    },
    "common-mistakes": {
        "label": "Common mistakes",
        "prompt": ("List the 3–4 most common mistakes or misconceptions aspirants have about "
                   "'{concept}'{subject}, each with a one-line correction. Markdown bullets. Return only the list."),
    },
    "pyq-trap": {
        "label": "PYQ trap",
        "prompt": ("Describe ONE classic 'trap' in how '{concept}'{subject} is tested — a subtle wording or "
                   "distinction that makes aspirants pick the wrong option — and how to avoid it. 3–5 sentences."),
    },
    "mini-check": {
        "label": "Mini check",
        "prompt": ("Write ONE exam-style multiple-choice question that checks understanding of "
                   "'{concept}'{subject}, with four options A–D, the correct option marked, and a one-line "
                   "explanation. Return it as readable markdown."),
    },
    # ── Concept-completeness assets (schema locked before any UI) ─────────────
    # These describe the concept itself (not a recipe step). They let the Teaching
    # Engine frame objectives, check prerequisites, and pre-empt misconceptions.
    "learning-objectives": {
        "label": "Learning objectives",
        "prompt": ("List 3–4 crisp learning objectives for '{concept}'{subject} — what a UPSC aspirant "
                   "should be able to DO after this lesson. Markdown bullets. Return only the list."),
    },
    "prerequisites": {
        "label": "Prerequisites",
        "prompt": ("List the 2–4 prior concepts an aspirant must already understand before learning "
                   "'{concept}'{subject}. One line each, name + why. Return only the list."),
    },
    "misconceptions": {
        "label": "Misconceptions",
        "prompt": ("List the 3–4 most common misconceptions about '{concept}'{subject} that must be "
                   "corrected up front, each with a one-line correction. Markdown bullets. Return only the list."),
    },
    "story": {
        "label": "Story hook",
        "prompt": ("Write a short, vivid real-world story or scenario (4–6 sentences) that hooks interest in "
                   "'{concept}'{subject} before the theory. Plain language. Return only the story."),
    },
    "interview-angle": {
        "label": "Interview angle",
        "prompt": ("Give ONE thoughtful angle on '{concept}'{subject} suitable for a UPSC personality test — "
                   "a balanced, opinion-inviting framing. 3–5 sentences. Return only the angle."),
    },
}

# ── Recipes (subject-agnostic lesson structures) ──────────────────────────────
# Recipe × Asset = Lesson. Steps are task-type keys, in teaching order.
RECIPES = {
    "comparison-first": {
        "label": "Comparison-first",
        "note": "Best when a concept is confused with a neighbour (FR vs DPSP).",
        "steps": ["analogy", "comparison", "pyq-trap", "worked-example", "mini-check"],
    },
    "example-first": {
        "label": "Example-first",
        "note": "Best for application/quant concepts — lead with a worked example.",
        "steps": ["worked-example", "concept-explainer", "analogy", "mini-check"],
    },
    "story-first": {
        "label": "Story-first",
        "note": "Best for dry factual topics — anchor with a memorable hook.",
        "steps": ["analogy", "concept-explainer", "mnemonic", "mini-check"],
    },
    "exam-drill": {
        "label": "Exam drill",
        "note": "Fast revision — how it's tested, what to avoid, one check.",
        "steps": ["pyq-insight", "common-mistakes", "mini-check"],
    },
}

# Coaching-brand / contact markers that must never leak into stored assets.
_BANNED = ("vision ias", "visionias", "insights ias", "forum ias", "forumias",
           "byju", "unacademy", "drishti", "http://", "https://", "www.", ".com",
           "@", "whatsapp", "telegram", "call us", "8826", "helpline")


def list_recipes():
    return [{"key": k, "label": v["label"], "note": v["note"], "steps": v["steps"]}
            for k, v in RECIPES.items()]


def list_task_types():
    return [{"key": k, "label": v["label"]} for k, v in TASK_TYPES.items()]


def _subject_frag(subject):
    return f" (subject: {subject})" if subject else ""


def build_prompt(task_type, concept, subject=""):
    tt = TASK_TYPES.get(task_type)
    if not tt:
        raise ValueError(f"unknown task_type: {task_type}")
    human = concept.replace("-", " ").strip()
    return tt["prompt"].format(concept=human, subject=_subject_frag(subject))


def run_checks(content, task_type):
    """Lightweight ADVISORY pre-check (v1 verification is manual). Never auto-verifies;
    it just surfaces warnings for the human reviewer at the promotion gate."""
    warnings = []
    text = (content or "").strip()
    if len(text) < 40:
        warnings.append("too short (<40 chars)")
    low = text.lower()
    hits = sorted({b for b in _BANNED if b in low})
    if hits:
        warnings.append("brand/contact markers: " + ", ".join(hits))
    if task_type == "comparison" and "|" not in text:
        warnings.append("comparison has no markdown table")
    if task_type == "mini-check" and not re.search(r"\b[ABCD]\b", text):
        warnings.append("mini-check has no visible A–D options")
    return {"ok": not warnings, "warnings": warnings, "length": len(text)}


def generate_asset(db, concept, subject, task_type, recipe_key=None):
    """Generate ONE asset via the AI Execution Runtime and store it as a DRAFT.
    Drafts are NEVER served to learners until an admin verifies them (manual gate)."""
    prompt = build_prompt(task_type, concept, subject)
    res = ai_runtime.route(task="pedagogy.asset", prompt=prompt,
                           spec={"concept": concept, "task_type": task_type})
    content = (res.output or "").strip()
    checks = run_checks(content, task_type)
    # next version number for this (concept, task_type)
    prior = (db.query(TeachingAsset)
             .filter(TeachingAsset.concept == concept, TeachingAsset.task_type == task_type)
             .order_by(TeachingAsset.version.desc()).first())
    version = (prior.version + 1) if prior else 1
    asset = TeachingAsset(
        concept=concept, subject=subject or None, task_type=task_type,
        kind="asset", recipe_key=recipe_key, content=content,
        provider=(res.decision or {}).get("provider"), status="draft",
        version=version, verify_detail=json.dumps(checks, ensure_ascii=False),
    )
    db.add(asset); db.commit(); db.refresh(asset)
    return asset, res.decision, checks


def get_asset(db, concept, task_type):
    """Reuse lookup — the newest VERIFIED asset for a (concept, task_type), or None."""
    return (db.query(TeachingAsset)
            .filter(TeachingAsset.concept == concept, TeachingAsset.task_type == task_type,
                    TeachingAsset.status == "verified")
            .order_by(TeachingAsset.version.desc()).first())


def compose_lesson(db, concept, recipe_key):
    """Recipe × Asset — assemble a lesson from VERIFIED assets only (reuse-before-
    generate: zero model calls). Reports which steps are still missing an asset so
    the Teaching Engine (Step 3) / an author knows what to generate next."""
    recipe = RECIPES.get(recipe_key)
    if not recipe:
        raise ValueError(f"unknown recipe: {recipe_key}")
    steps, missing = [], []
    for tt in recipe["steps"]:
        a = get_asset(db, concept, tt)
        if a:
            steps.append({"task_type": tt, "label": TASK_TYPES.get(tt, {}).get("label", tt),
                          "asset_id": a.id, "version": a.version, "content": a.content})
        else:
            missing.append(tt)
            steps.append({"task_type": tt, "label": TASK_TYPES.get(tt, {}).get("label", tt),
                          "asset_id": None, "content": None})
    return {"concept": concept, "recipe": recipe_key, "recipe_label": recipe["label"],
            "steps": steps, "missing": missing, "complete": not missing}
