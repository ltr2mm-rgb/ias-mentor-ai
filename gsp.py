"""
AIMENTORA — Guided Success Programme (GSP) engine · Phase-1 spine (Prelims).

Turns the syllabus into a guided journey: STAGE (depth band) -> MODULE (teachable
unit + learning objective + mastery gate) -> CONCEPT (atom, from concept_inventory).
The macro "Guidance Engine": placement, module state, daily mission, promotion.
Reuses the live AML student model (concept_mastery) for gating — an attempt logged
via /me/attempt already moves mastery, so modules gate off real evidence.

Pilot content: Fundamental Rights (Polity, Part III). Modules are defined here as
data (easy to extend / later move to a DB table). Per-user state lives in
gsp_enrollment + gsp_module_progress.
"""
import datetime
from models import (ConceptMastery, ConceptInventory, Question,
                    GspModuleProgress)

STAGES = {1: "Foundation", 2: "Standard Books", 3: "Concept Integration",
          4: "Prelims Mastery", 5: "Mains", 6: "Interview"}

# Gate tuning
MIN_ATTEMPTS = 6            # minimum evidence before a module gate can pass
MIN_COVERAGE = 0.5         # fraction of a module's concepts that must be practiced

FR_MODULES = [
    {
        "module_id": "M-FR-0",
        "order": 0,
        "title": "Framework & Nature of Fundamental Rights",
        "stage": 1,
        "stage_name": "Foundation",
        "bloom": "Understand",
        "objective": "Recall the structure of Part III and describe the nature, scope and limits of Fundamental Rights.",
        "concept_keys": [
            "fundamental rights",
            "fundamental rights available only to citizens",
            "nature of fundamental rights",
            "significance of fundamental rights",
            "criticism of fundamental rights",
            "features of fundamental rights",
            "laws inconsistent with fundamental rights article 13",
            "fundamental rights available to foreigners",
            "classification of fundamental rights",
            "fundamental rights under part iii",
            "reasonable restrictions on fundamental rights"
        ],
        "prereqs": [],
        "exit_mastery": 0.8,
        "checkpoint_q": 5
    },
    {
        "module_id": "M-FR-1",
        "order": 1,
        "title": "Right to Equality (Articles 14-18)",
        "stage": 2,
        "stage_name": "Standard Books",
        "bloom": "Apply",
        "objective": "Distinguish the five equality provisions and apply them to cases of discrimination and classification.",
        "concept_keys": [
            "right to equality articles 14 18",
            "abolition of untouchability",
            "right to equality article 14",
            "right to equality",
            "article 15 prohibition of discrimination",
            "article 16 equality of opportunity in public employment",
            "fundamental rights right to equality",
            "article 14 equality before law and equal protection of laws",
            "article 14 equality before law and equal protection",
            "article 14 equality before law",
            "article 17 abolition of untouchability",
            "article 18 abolition of titles"
        ],
        "prereqs": [
            "M-FR-0"
        ],
        "exit_mastery": 0.85,
        "checkpoint_q": 8
    },
    {
        "module_id": "M-FR-2",
        "order": 2,
        "title": "Right to Freedom I — Arts 19, 20, 22",
        "stage": 2,
        "stage_name": "Standard Books",
        "bloom": "Understand",
        "objective": "Explain the six freedoms (Art 19), the protections under Arts 20 & 22, and their reasonable restrictions.",
        "concept_keys": [
            "preventive detention",
            "freedom of speech and expression article 19 1 a",
            "reasonable restrictions on freedom of speech",
            "right to freedom article 19",
            "right to freedom articles 19 22",
            "freedom of speech and expression under article 19 1 a"
        ],
        "prereqs": [
            "M-FR-0"
        ],
        "exit_mastery": 0.85,
        "checkpoint_q": 8
    },
    {
        "module_id": "M-FR-3",
        "order": 3,
        "title": "Article 21 & Derived Rights",
        "stage": 2,
        "stage_name": "Standard Books",
        "bloom": "Analyse",
        "objective": "Analyse Article 21 and the rights derived from it (privacy, education, environment) and their evolution through case law.",
        "concept_keys": [
            "right to privacy under article 21",
            "right to privacy",
            "right to privacy as fundamental right",
            "right to life and personal liberty article 21",
            "right to marry under article 21",
            "right to education",
            "right to education article 21a",
            "right to privacy as a fundamental right",
            "right to privacy as part of article 21",
            "right to clean environment and article 21",
            "right to education under article 21a",
            "article 21a right to education",
            "right to marry article 21",
            "right to life and personal liberty under article 21",
            "article 21 right to life and personal liberty",
            "right to shelter under article 21",
            "right to marry as part of article 21"
        ],
        "prereqs": [
            "M-FR-2"
        ],
        "exit_mastery": 0.85,
        "checkpoint_q": 10
    },
    {
        "module_id": "M-FR-4",
        "order": 4,
        "title": "Right against Exploitation (Arts 23-24)",
        "stage": 2,
        "stage_name": "Standard Books",
        "bloom": "Understand",
        "objective": "Describe the protections against exploitation and identify their enforceability against private persons.",
        "concept_keys": [
            "right against exploitation articles 23 24",
            "right against exploitation",
            "article 23 prohibition of traffic in human beings and forced labour",
            "right against exploitation articles 23 and 24",
            "right against exploitation under indian constitution"
        ],
        "prereqs": [
            "M-FR-0"
        ],
        "exit_mastery": 0.85,
        "checkpoint_q": 6
    },
    {
        "module_id": "M-FR-5",
        "order": 5,
        "title": "Right to Freedom of Religion (Arts 25-28)",
        "stage": 2,
        "stage_name": "Standard Books",
        "bloom": "Understand",
        "objective": "Explain the four dimensions of religious freedom in India's secular framework.",
        "concept_keys": [
            "right to freedom of religion articles 25 28",
            "right to freedom of religion"
        ],
        "prereqs": [
            "M-FR-0"
        ],
        "exit_mastery": 0.85,
        "checkpoint_q": 6
    },
    {
        "module_id": "M-FR-6",
        "order": 6,
        "title": "Cultural & Educational Rights (Arts 29-30)",
        "stage": 2,
        "stage_name": "Standard Books",
        "bloom": "Understand",
        "objective": "Describe the cultural and educational rights of minorities.",
        "concept_keys": [
            "cultural and educational rights",
            "cultural and educational rights articles 29 30"
        ],
        "prereqs": [
            "M-FR-0"
        ],
        "exit_mastery": 0.85,
        "checkpoint_q": 5
    },
    {
        "module_id": "M-FR-7",
        "order": 7,
        "title": "Right to Constitutional Remedies & Writs (Art 32)",
        "stage": 2,
        "stage_name": "Standard Books",
        "bloom": "Analyse",
        "objective": "Differentiate the five writs and the scope of Arts 32 vs 226 for enforcing rights.",
        "concept_keys": [
            "right to constitutional remedies article 32",
            "right to constitutional remedies",
            "writs mandamus and quo warranto",
            "article 32 right to constitutional remedies",
            "writs in indian constitution",
            "fundamental rights right to constitutional remedies",
            "types of writs"
        ],
        "prereqs": [
            "M-FR-1",
            "M-FR-2",
            "M-FR-3",
            "M-FR-4",
            "M-FR-5",
            "M-FR-6"
        ],
        "exit_mastery": 0.85,
        "checkpoint_q": 8
    },
    {
        "module_id": "M-FR-8",
        "order": 8,
        "title": "Integration — FR vs DPSP/Duties, Amendability, Emergency, Case Law",
        "stage": 3,
        "stage_name": "Concept Integration",
        "bloom": "Evaluate",
        "objective": "Integrate FRs with DPSPs and Duties, and evaluate amendability, emergency suspension and landmark judgments (PYQ + current affairs).",
        "concept_keys": [
            "suspension of fundamental rights during emergency",
            "suspension of fundamental rights during national emergency",
            "parliament s power to amend fundamental rights",
            "relationship between fundamental rights and directive principles",
            "distinction between fundamental rights and directive principles",
            "relationship between fundamental rights and fundamental duties",
            "relationship between fundamental rights directive principles and fundamental duties",
            "balance between fundamental rights and directive principles"
        ],
        "prereqs": [
            "M-FR-7"
        ],
        "exit_mastery": 0.85,
        "checkpoint_q": 10
    },
    {
        "module_id": "M-FR-9",
        "order": 9,
        "title": "Prelims Simulation & Elimination — Fundamental Rights",
        "stage": 4,
        "stage_name": "Prelims Mastery",
        "bloom": "Apply",
        "objective": "Solve mixed, full-length FR question sets under time using elimination technique, spanning doctrines, landmark cases and judicial review.",
        "concept_keys": [
            "doctrine of eclipse",
            "doctrine of severability",
            "basic structure doctrine",
            "judicial review of fundamental rights",
            "kesavananda bharati case",
            "golaknath case",
            "ninth schedule and judicial review",
            "definition of state article 12"
        ],
        "prereqs": [
            "M-FR-8"
        ],
        "exit_mastery": 0.8,
        "checkpoint_q": 25
    }
]
MODULE_BY_ID = {m["module_id"]: m for m in FR_MODULES}
FIRST_MODULE = FR_MODULES[0]["module_id"]


# ── mastery over a module's concepts (reads the live AML student model) ──
def module_progress(db, user_id, module):
    """Return {mastery, coverage, attempts, practiced, total} for one module."""
    keys = module["concept_keys"]
    total = len(keys)
    if total == 0:                       # simulation-type module (no own concepts)
        return {"mastery": 0.0, "coverage": 0.0, "attempts": 0, "practiced": 0, "total": 0}
    rows = (db.query(ConceptMastery)
            .filter(ConceptMastery.user_id == user_id,
                    ConceptMastery.concept_key.in_(keys)).all())
    practiced = len(rows)
    attempts = sum((r.attempts or 0) for r in rows)
    mastery = (sum((r.mastery or 0) for r in rows) / practiced) if practiced else 0.0
    return {"mastery": round(mastery, 3), "coverage": round(practiced / total, 3),
            "attempts": attempts, "practiced": practiced, "total": total}


def _gate_passed(module, prog):
    if module["concept_keys"]:
        return (prog["mastery"] >= module["exit_mastery"]
                and prog["coverage"] >= MIN_COVERAGE
                and prog["attempts"] >= MIN_ATTEMPTS)
    # simulation module: gated externally (mock accuracy) — left to /promote payload
    return False


def _mastered_ids(db, user_id):
    return {r.module_id for r in db.query(GspModuleProgress)
            .filter(GspModuleProgress.user_id == user_id,
                    GspModuleProgress.state == "mastered").all()}


def modules_state(db, user_id):
    """Every FR module with its computed state + progress."""
    mastered = _mastered_ids(db, user_id)
    out = []
    for m in FR_MODULES:
        prog = module_progress(db, user_id, m)
        prereqs_met = all(p in mastered for p in m["prereqs"])
        if m["module_id"] in mastered:
            state = "mastered"
        elif not prereqs_met:
            state = "locked"
        elif prog["attempts"] == 0:
            state = "available"
        else:
            state = "in_progress"
        out.append({**m, "progress": prog, "state": state,
                    "gate_ready": _gate_passed(m, prog)})
    return out


def current_module(states):
    """The module the student should work on now: first in_progress, else first available."""
    for s in states:
        if s["state"] == "in_progress":
            return s
    for s in states:
        if s["state"] == "available":
            return s
    return None


def readiness(states):
    """Topic readiness % = coverage-weighted mastery across all modules with concepts."""
    num = den = 0.0
    for s in states:
        t = s["progress"]["total"]
        if t:
            num += s["progress"]["mastery"] * s["progress"]["coverage"] * t
            den += t
    return round(100 * num / den) if den else 0


def concept_facts(db, keys, limit=40):
    """Verified key_facts per concept — served from the embedded pilot facts
    (grounds module-detail content reliably, no DB scan)."""
    try:
        from gsp_seed import CONCEPT_FACTS
    except Exception:
        CONCEPT_FACTS = {}
    out = []
    for ck in keys:
        cf = CONCEPT_FACTS.get(ck)
        if cf:
            out.append({"concept": ck, "importance": cf.get("importance"),
                        "difficulty": cf.get("difficulty"),
                        "key_facts": cf.get("key_facts", [])[:4]})
        if len(out) >= limit:
            break
    return out
