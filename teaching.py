"""AI Marga — Teaching Engine (see TEACHING_ENGINE.md).

Content ≠ Pedagogy: this module decides HOW to teach a specific learner; it NEVER
invents facts (the Knowledge Kernel supplies grounded content). Pure functions over
an assembled `signals` dict, so every decision is transparent and unit-testable —
the same discipline as the Decision Intelligence Engine.

Stage 1 (this file): WHO → WHY (3-layer barrier) → learning objectives → strategy
→ teaching confidence. Later stages add the mental-model builder, the re-teach loop
with stopping criteria, and strategy-learning (Evidence Engine).
"""

# Target learning outcome per exam stage — teaching aims at exam success, not just
# understanding (understanding is the intermediate outcome).
_STAGE_OUTCOME = {
    "prelims":   ["Recognize", "Eliminate", "Recall"],
    "mains":     ["Analyze", "Structure", "Write"],
    "interview": ["Think", "Connect", "Justify"],
}


def _stage_of(exam_label):
    s = (exam_label or "").lower()
    if "mains" in s:
        return "mains"
    if "interview" in s:
        return "interview"
    return "prelims"


# ── Concept prerequisite graph (see TEACHING_ENGINE.md §11) ───────────────────
# A SEED graph — hand-authored for the highest-traffic UPSC concepts. It is
# deliberately partial and grows (later: extracted from ConceptInventory + PYQ
# co-occurrence). Read by: missing-prerequisite detection, confuses-concepts
# detection, the Mental Model Builder, and objective ordering.
#   model    = the structural scaffold to install BEFORE detail (§6)
#   siblings = confusable concepts (drives the "contrast & disambiguate" strategy)
#   prereqs  = what must be understood first
_CONCEPT_GRAPH = {
    "fundamental rights": {
        "model": ["Constitution", "Rights (Part III)", "Reasonable restrictions", "Remedies (Art 32)"],
        "siblings": ["Directive Principles of State Policy", "Fundamental Duties"], "prereqs": ["Preamble"]},
    "directive principles": {
        "model": ["Constitution", "DPSP (Part IV)", "Gandhian / Liberal / Socialist categories", "FR vs DPSP"],
        "siblings": ["Fundamental Rights"], "prereqs": ["Preamble"]},
    "fundamental duties": {
        "model": ["Constitution", "Fundamental Duties (Art 51A)", "How they relate to FR & DPSP"],
        "siblings": ["Fundamental Rights", "Directive Principles of State Policy"], "prereqs": []},
    "federalism": {
        "model": ["Union–State division of powers", "7th Schedule (3 lists)", "Centre–State relations"],
        "siblings": ["Unitary features"], "prereqs": ["Constitution"]},
    "polity": {
        "model": ["Constitution & Preamble", "Rights & Duties", "Union & States", "Judiciary"],
        "siblings": [], "prereqs": []},
    "indian polity": {
        "model": ["Constitution & Preamble", "Rights & Duties", "Union & States", "Judiciary"],
        "siblings": [], "prereqs": []},
    "medieval history": {
        "model": ["Delhi Sultanate", "The Mughals", "Administration & economy", "Society & culture"],
        "siblings": [], "prereqs": []},
    "ancient history": {
        "model": ["Sources", "Indus Valley", "Vedic age", "Mauryan & Gupta empires"],
        "siblings": [], "prereqs": []},
    "modern history": {
        "model": ["Advent of Europeans", "British expansion", "Reform & revolt (1857)", "Freedom struggle"],
        "siblings": [], "prereqs": []},
    "inflation": {
        "model": ["Money supply", "Demand-pull vs cost-push", "Measures (CPI / WPI)", "Control (monetary & fiscal)"],
        "siblings": ["Deflation"], "prereqs": []},
}


def _graph_match(target):
    """Longest case-insensitive containment match against the seed graph."""
    t = (target or "").lower()
    best, blen = None, 0
    for key, node in _CONCEPT_GRAPH.items():
        if key in t or t in key:
            if len(key) > blen:
                best, blen = node, len(key)
    return best


def mental_model(target):
    """The structural scaffold to install before detail, or None if unknown."""
    node = _graph_match(target)
    return list(node["model"]) if node and node.get("model") else None


# ── Mental Model Diagnosis (TEACHING_ENGINE.md §4) — the fundamental change ────
# The best teachers don't present the right structure; they find the WRONG model the
# learner holds and replace it. Each entry: the common misconception + the correction.
_MENTAL_MODEL_FIX = {
    "fundamental rights": {
        "misconception": "Fundamental Rights are rights the government GIVES to citizens.",
        "correction": "The Constitution creates and limits the government; rights CONSTRAIN the State — "
                      "they aren't granted by it. Constitution → creates → Government → cannot violate → your Rights."},
    "directive principles": {
        "misconception": "DPSP are like Fundamental Rights — enforceable in court.",
        "correction": "DPSP are non-justiciable GOALS for the State (Part IV); FR are enforceable CLAIMS "
                      "against the State (Part III). Different purpose, different enforceability."},
    "fundamental duties": {
        "misconception": "Fundamental Duties are legally enforceable like rights.",
        "correction": "Fundamental Duties (Art 51A) are non-enforceable moral obligations — the citizen-side "
                      "complement to Rights, not court-enforceable."},
    "federalism": {
        "misconception": "India is a fully federal country like the USA.",
        "correction": "India is 'federal in form, unitary in spirit' — a strong Centre with a federal division of "
                      "powers that tilts to the Union in emergencies. Quasi-federal, not classic federal."},
    "inflation": {
        "misconception": "Inflation means prices are high.",
        "correction": "Inflation is the RATE at which the general price level RISES over time — a change, not a "
                      "level. Prices can be high with low inflation, or rise fast from a low base."},
}


def mental_model_diagnosis(target):
    """The wrong model the learner probably holds + the correction to install first.
    Returns {misconception, correction} or None. Longest-match wins."""
    tl = (target or "").lower()
    best, blen = None, 0
    for k, v in _MENTAL_MODEL_FIX.items():
        if (k in tl or tl in k) and len(k) > blen:
            best, blen = v, len(k)
    return best


# ── Exam heuristics + tricks (the mentor's "gold") — real, memorable rules to inject
# into a lesson, so the trick is verified pedagogy, not LLM-invented filler.
_EXAM_TRICKS = {
    "direction": {"heuristic": "Draw, don't calculate — one dot, one arrow.",
                  "trick": "Never rotate yourself. Face North and rotate the PAPER."},
    "blood relation": {"heuristic": "Don't remember people — remember generations.",
                       "trick": "Fix one known person, then move ± one generation at a time."},
    "series": {"heuristic": "Don't search for numbers — search for the CHANGE.",
               "trick": "Write the differences under the gaps; the pattern usually lives there."},
    "syllogism": {"heuristic": "Never try to prove — try to DISPROVE.",
                  "trick": "Draw the least-overlapping Venn; if a conclusion can fail even once, it's false."},
    "coding": {"heuristic": "Find the shift, not the meaning.",
               "trick": "Line letters against position numbers (A=1…); look for a constant gap."},
    "comprehension": {"heuristic": "Read the QUESTION first, then hunt the passage.",
                      "trick": "The answer is in the passage — never your own opinion or outside knowledge."},
    "csat": {"heuristic": "Classify before you solve — 2 seconds of naming saves the question.",
             "trick": "On CSAT, elimination beats calculation — rule out two options first."},
    "reasoning": {"heuristic": "Classify the family first (series / direction / blood-relation / coding…), then solve.",
                  "trick": "A wrong classification guarantees a wrong answer — name it before you touch it."},
}


def exam_tricks(target):
    """One memorable heuristic + one exam trick for the topic, or None. Longest match."""
    tl = (target or "").lower()
    best, blen = None, 0
    for k, v in _EXAM_TRICKS.items():
        if k in tl and len(k) > blen:
            best, blen = v, len(k)
    return best


def graph_signals(target, mastery=None):
    """Turn the graph into diagnosis signals — conservatively (only when the learner
    is shaky, so we don't over-fire): a likely-confused sibling, or a prerequisite gap."""
    node = _graph_match(target)
    out = {}
    if not node:
        return out
    shaky = (mastery is None) or (isinstance(mastery, (int, float)) and mastery < 55)
    if shaky and node.get("siblings"):
        out["sibling_conflict"] = node["siblings"][0]
    weak = isinstance(mastery, (int, float)) and mastery < 45
    if weak and node.get("prereqs"):
        out["prereq_gap"] = node["prereqs"][0]
    return out


def diagnose_barrier(signals):
    """Three-layer barrier diagnosis — Knowledge / Cognitive / Behaviour. Returns the
    single most-blocking barrier with its layer, triggering evidence and confidence.
    Every conclusion carries the signal that fired it. Behaviour/affective barriers
    are surfaced first because their remedy is often NOT a lesson."""
    s = signals or {}
    mastery = s.get("mastery")                 # 0-100 on this concept/target (None if unseen)
    attempts = s.get("attempts", 0) or 0
    recall = s.get("recall_accuracy")          # accuracy on direct/recall items
    applied = s.get("applied_accuracy")        # accuracy on application/CSAT items
    retention = s.get("retention")
    reasons = s.get("reasons", {}) or {}       # {conceptual,factual,careless,misread,guess: counts}
    reading_speed = s.get("reading_speed")
    consistency = s.get("consistency")
    sibling = s.get("sibling_conflict")        # name of confusable concept clustering errors
    conf_gap = s.get("confidence_gap")         # self-rated minus actual (overconfidence if > 0)

    cand = []
    def add(layer, key, label, why, w):
        cand.append({"layer": layer, "barrier": key, "label": label, "why": why, "weight": w})

    tot = sum(v for v in reasons.values() if isinstance(v, (int, float))) or 0

    # ---- Behaviour / affective (checked first — often not a teaching problem) ----
    if tot >= 4:
        if reasons.get("careless", 0) / tot >= 0.35:
            add("behaviour", "careless", "Careless slips",
                [f"{round(100*reasons['careless']/tot)}% of misses tagged careless"], 1.1)
        if reasons.get("misread", 0) / tot >= 0.30 or (isinstance(reading_speed, (int, float)) and reading_speed >= 90):
            add("behaviour", "reads_too_fast", "Reading too fast",
                ["misreads cluster; reading speed is high"], 1.0)
        if reasons.get("guess", 0) / tot >= 0.35:
            add("behaviour", "guessing", "Guessing under uncertainty",
                [f"{round(100*reasons['guess']/tot)}% of misses were guesses"], 0.9)
    if isinstance(consistency, (int, float)) and consistency < 25:
        add("behaviour", "inconsistent", "Inconsistent study",
            [f"low active-day consistency ({consistency}%)"], 0.7)
    if isinstance(conf_gap, (int, float)) and conf_gap >= 20:
        add("behaviour", "overconfidence", "Overconfidence",
            ["rates answers 'sure' but scores lower"], 0.8)

    # ---- Knowledge ----
    if (mastery is None or mastery == 0) and attempts < 3:
        add("knowledge", "never_seen", "A new concept",
            ["little or no prior work here"], 1.2)
    if s.get("prereq_gap"):
        add("knowledge", "missing_prerequisite", "Missing a prerequisite",
            ["also failing the prerequisite of this concept"], 1.3)
    if sibling:
        add("knowledge", "confuses_concepts", "Confusing two concepts",
            [f"errors cluster on “{sibling}”"], 1.25)
    if isinstance(mastery, (int, float)) and 0 < mastery < 45:
        add("knowledge", "weak_knowledge", "Shaky fundamentals",
            [f"mastery {mastery}%"], 1.0)

    # ---- Cognitive ----
    if isinstance(recall, (int, float)) and isinstance(applied, (int, float)) and recall - applied >= 25:
        add("cognitive", "memorizes_not_understands", "Recalls but can't apply",
            [f"recall {recall}% vs application {applied}%"], 1.15)
    if isinstance(retention, (int, float)) and retention < 40 and (mastery or 0) >= 45:
        add("cognitive", "forgets", "Knew it, now forgetting",
            [f"retention {retention}% though mastery is ok"], 1.0)

    if not cand:
        return {"layer": "knowledge", "barrier": "reinforce", "label": "Reinforce & extend",
                "why": ["no clear blocker — consolidate, then go deeper"], "confidence": "Low", "all": []}
    cand.sort(key=lambda c: -c["weight"])
    top = cand[0]
    conf = "High" if (top["weight"] >= 1.2 and tot >= 6) else ("Medium" if top["weight"] >= 1.0 else "Low")
    return {"layer": top["layer"], "barrier": top["barrier"], "label": top["label"],
            "why": top["why"], "confidence": conf, "all": cand[:4]}


# ── Depth of understanding (TEACHING_ENGINE.md §5) — understanding isn't binary ──
_DEPTH = {
    1: "understand it in your own words",
    2: "solve its PYQs",
    3: "eliminate wrong options under exam pressure",
    4: "structure a Mains answer on it",
    5: "explain it to someone else",
    6: "connect it to a current-affairs debate",
}


def target_depth(stage):
    """The depth the exam stage requires — the engine teaches and checks TO this level,
    not just 'understood'. Prelims → L3 (eliminate), Mains → L4, Interview → L6."""
    lvl = 4 if stage == "mains" else (6 if stage == "interview" else 3)
    return {"level": lvl, "label": _DEPTH[lvl]}


# ── Strategy as a 5-dimension BUILD-MIX (§6) — every lesson blends all five; only
# the proportion changes with level, stage and barrier. Presentation styles (the
# recipe) are the TOOLS that deliver this mix.
_DIMS = ["intuition", "structure", "memory", "application", "exam_skills"]


def build_mix(mastery, stage, barrier=None):
    """Proportions of the five build-dimensions for THIS lesson (sum to 100)."""
    m = mastery if isinstance(mastery, (int, float)) else 25
    if m < 40:
        base = {"intuition": 60, "structure": 20, "memory": 10, "application": 5, "exam_skills": 5}
    elif m < 70:
        base = {"intuition": 30, "structure": 25, "memory": 15, "application": 20, "exam_skills": 10}
    else:
        base = {"intuition": 10, "structure": 20, "memory": 10, "application": 35, "exam_skills": 25}
    if stage == "mains":
        base["application"] += 15; base["structure"] += 5
        base["exam_skills"] = max(0, base["exam_skills"] - 10); base["intuition"] = max(0, base["intuition"] - 10)
    elif stage == "interview":
        base["application"] += 15; base["intuition"] += 5
        base["exam_skills"] = max(0, base["exam_skills"] - 10); base["memory"] = max(0, base["memory"] - 10)
    else:  # prelims
        base["exam_skills"] += 10; base["memory"] += 5
        base["application"] = max(0, base["application"] - 10); base["intuition"] = max(0, base["intuition"] - 5)
    if barrier == "confuses_concepts":
        base["structure"] += 10; base["intuition"] = max(0, base["intuition"] - 10)
    elif barrier == "forgets":
        base["memory"] += 15; base["intuition"] = max(0, base["intuition"] - 15)
    elif barrier in ("weak_knowledge", "never_seen", "missing_prerequisite"):
        base["intuition"] += 10; base["application"] = max(0, base["application"] - 10)
    tot = sum(base.values()) or 1
    return {k: round(v * 100.0 / tot) for k, v in base.items()}


def learning_objectives(target, stage, mastery=None):
    """Small, measurable, stage-scoped objectives — what must change in the learner."""
    outs = _STAGE_OUTCOME.get(stage, _STAGE_OUTCOME["prelims"])
    base = [f"Explain {target} in your own words",
            f"Tell {target} apart from its closest confusable idea"]
    if stage == "prelims":
        base += [f"Eliminate wrong options on {target} MCQs", f"Answer {target} PYQs"]
    elif stage == "mains":
        base += [f"Lay out the key dimensions of {target}", f"Structure a 10-marker on {target}"]
    else:
        base += [f"Take and defend a balanced view on {target}", f"Connect {target} to a current debate"]
    return {"stage": stage, "outcome": outs, "objectives": base}


# Barrier → teaching strategy recipe (an ordered sequence of modalities).
_STRATEGY = {
    "never_seen": ("Foundation from first principles",
                   ["A relatable story or analogy", "First-principles explanation",
                    "A simple diagram / structure", "One worked example", "Practice"]),
    "missing_prerequisite": ("Prerequisite-first",
                   ["Teach the missing prerequisite", "Bridge it to today's concept",
                    "Worked example", "Practice"]),
    "confuses_concepts": ("Contrast & disambiguate",
                   ["Side-by-side comparison table", "The one rule that tells them apart",
                    "PYQ traps that exploit the confusion", "Mnemonic", "Practice"]),
    "weak_knowledge": ("Rebuild the core",
                   ["The core idea, plainly", "Diagram / structure",
                    "Two worked examples", "Practice"]),
    "memorizes_not_understands": ("Understand, don't memorize",
                   ["Why it's true (the mechanism)", "Apply it to a fresh scenario",
                    "Transfer drill across contexts", "Practice"]),
    "forgets": ("Active recall + spacing",
                   ["Rapid recap", "A memory hook / mnemonic",
                    "Active-recall prompts", "Schedule spaced review", "Practice"]),
    "careless": ("Slow-thinking checklist",
                   ["A pre-answer checklist", "Trap-spotting on two examples",
                    "Deliberate-pace practice"]),
    "reads_too_fast": ("Read-to-answer discipline",
                   ["Underline the ask & keywords", "Restate the question first",
                    "Paced practice"]),
    "guessing": ("Elimination technique",
                   ["Eliminate two options first", "Confidence-tagged practice",
                    "Review only the guesses"]),
    "overconfidence": ("Counter-examples first",
                   ["Trap questions up front", "Where the intuition breaks",
                    "Careful practice"]),
    "inconsistent": ("Small daily wins",
                   ["One tight concept today", "A quick win to rebuild rhythm",
                    "Short practice"]),
    "reinforce": ("Extend & deepen",
                   ["Quick recap", "A harder application",
                    "A current-affairs / Mains angle", "Practice"]),
}


def select_strategy(barrier, stage, style=None):
    """Pick the teaching recipe for this barrier, tilted by exam stage and style."""
    name, recipe = _STRATEGY.get(barrier, _STRATEGY["reinforce"])
    recipe = list(recipe)
    if stage == "mains" and barrier in ("reinforce", "weak_knowledge", "memorizes_not_understands"):
        recipe = recipe[:-1] + ["Multi-dimensional analysis", "Answer framework (intro · body · way forward)"]
    if stage == "interview" and barrier in ("reinforce", "memorizes_not_understands"):
        recipe = recipe[:-1] + ["Multiple viewpoints", "A follow-up question to defend your stance"]
    if style == "example_first" and "One worked example" in recipe:
        recipe = ["One worked example"] + [r for r in recipe if r != "One worked example"]
    return {"strategy": name, "recipe": recipe}


# ── Current Cognitive State (TEACHING_ENGINE.md §7) — replaces "learning style" ──
# Stable learning styles lack evidence; the learner's CURRENT state changes teaching
# far more. Inferred from live signals; each state carries the teaching adjustment.
_STATE_ACTION = {
    "near_mastery": "Skip the basics — go straight to application, edge cases and PYQ traps.",
    "forgetting":   "Lead with rapid recall and a memory hook; keep it short.",
    "guessing":     "Slow down — teach elimination and how to be sure before answering.",
    "overloaded":   "One idea only, in plain language; strip everything else out.",
    "confused":     "Clear the specific confusion first, side-by-side, before anything new.",
    "low_rhythm":   "Keep it very short — a single quick win to rebuild momentum.",
    "confident":    "Stretch with a harder application or a trap that tests the confidence.",
    "curious":      "Teach normally and feed the curiosity with one 'why it matters' hook.",
}


def cognitive_state(signals):
    """The learner's current cognitive/affective state — what actually changes the
    teaching decision right now. Returns {state, action}."""
    s = signals or {}
    mastery, retention, consistency = s.get("mastery"), s.get("retention"), s.get("consistency")
    conf_gap = s.get("confidence_gap")
    reasons = s.get("reasons", {}) or {}
    tot = sum(v for v in reasons.values() if isinstance(v, (int, float))) or 0
    def frac(k):
        return (reasons.get(k, 0) / tot) if tot else 0
    if isinstance(mastery, (int, float)) and mastery >= 75 and (not isinstance(retention, (int, float)) or retention >= 55):
        st = "near_mastery"
    elif tot >= 4 and frac("guess") >= 0.35:
        st = "guessing"
    elif isinstance(retention, (int, float)) and retention < 40 and (mastery or 0) >= 45:
        st = "forgetting"
    elif tot >= 5 and (frac("careless") + frac("misread")) >= 0.5:
        st = "overloaded"
    elif tot >= 4 and frac("conceptual") >= 0.4:
        st = "confused"
    elif isinstance(consistency, (int, float)) and consistency < 20:
        st = "low_rhythm"
    elif isinstance(conf_gap, (int, float)) and conf_gap >= 20:
        st = "confident"
    else:
        st = "curious"
    return {"state": st, "action": _STATE_ACTION.get(st, "")}


def teaching_confidence(barrier_conf, grounded, mastery=None):
    """Expected understanding gain + confidence — honest, low when we know little
    (mirrors the Prediction Engine). Low confidence is a signal to switch strategy."""
    base = 55
    if grounded:
        base += 12
    if barrier_conf == "High":
        base += 12
    elif barrier_conf == "Low":
        base -= 12
    if isinstance(mastery, (int, float)):
        base += int((100 - mastery) * 0.08)     # more headroom to gain when mastery is low
    gain = max(20, min(90, base))
    conf = "High" if (grounded and barrier_conf == "High") else ("Medium" if (grounded or barrier_conf != "Low") else "Low")
    return {"expected_gain": gain, "confidence": conf}


# Re-teach ladder — when a check fails, the TEACHING changes (not the words repeat).
# Each failed attempt switches modality; after the ladder is exhausted, escalate.
_RETEACH = [
    ("Worked examples first",
     ["Start with 2 fully worked examples", "Extract the pattern from them",
      "Now state the principle, briefly", "Practice"]),
    ("Visual & structured",
     ["A diagram / mind-map of the whole", "Label each part in one line",
      "Map one example onto it", "Practice"]),
]


# Reverse lookup so a strategy that worked before can be reused by name.
_STRATEGY_BY_NAME = {v[0]: list(v[1]) for v in _STRATEGY.values()}


def _preferred_from_history(barrier, history):
    """Evidence Engine in miniature: prefer a strategy that has WORKED for THIS learner
    on THIS barrier before. Returns a strategy dict or None."""
    if not history:
        return None
    worked = [h for h in history if h.get("barrier") == barrier and h.get("passed")]
    if worked:
        # Prefer the strategy that worked FASTEST for this learner (time-to-mastery).
        timed = [h for h in worked if h.get("seconds")]
        pick = min(timed, key=lambda h: h["seconds"]) if timed else worked[-1]
        name = pick.get("strategy")
        if name in _STRATEGY_BY_NAME:
            fast = " (your fastest way to get this)" if timed else ""
            return {"strategy": name, "recipe": list(_STRATEGY_BY_NAME[name]),
                    "learned": "this worked for you before" + fast}
    return None


def _from_aggregate(barrier, priors):
    """Cross-learner prior (Evidence Engine): when this learner has no history for the
    barrier, lean on the strategy that has worked best for OTHER learners on it. Sparse
    early, compounding as data grows. `priors` is {barrier: best_strategy_name}."""
    if not priors:
        return None
    name = priors.get(barrier)
    if name and name in _STRATEGY_BY_NAME:
        return {"strategy": name, "recipe": list(_STRATEGY_BY_NAME[name]),
                "learned": "works best for learners like you"}
    return None


def reteach(attempt, stage):
    """attempt is 1-based (1 = first re-teach). Switch strategy each time; escalate
    once the ladder is spent (different modality → video/live → human mentor, §9)."""
    if attempt - 1 < len(_RETEACH):
        name, recipe = _RETEACH[attempt - 1]
        return {"strategy": name, "recipe": list(recipe), "escalate": False}
    return {"strategy": "Let's bring in your mentor",
            "recipe": ["Try a video / live explanation of this one",
                       "Ask your mentor to walk you through it"], "escalate": True}


def plan(signals):
    """Teaching plan: WHO → WHY (barrier) → objectives → strategy → confidence. On a
    re-teach (attempt ≥ 1) the strategy switches per the ladder — the engine never
    assumes the first explanation worked."""
    target = signals.get("target") or "this concept"
    stage = _stage_of(signals.get("exam_label"))
    # Enrich with the concept graph (sibling confusion / prerequisite gap) before diagnosis.
    sig = dict(signals)
    sig.update(graph_signals(target, sig.get("mastery")))
    d = diagnose_barrier(sig)
    obj = learning_objectives(target, stage, sig.get("mastery"))
    attempt = int(sig.get("attempt") or 0)
    if attempt >= 1:
        strat = reteach(attempt, stage)
    else:
        strat = (_preferred_from_history(d["barrier"], sig.get("strategy_history"))
                 or _from_aggregate(d["barrier"], sig.get("aggregate_priors"))
                 or select_strategy(d["barrier"], stage, sig.get("style")))
    tc = teaching_confidence(d.get("confidence"), bool(sig.get("grounded")), sig.get("mastery"))
    # Confidence gate (§10): when we're not sure the lesson will land, say so and lean
    # on the check to verify — rather than shipping a low-confidence lesson silently.
    caution = (tc.get("confidence") == "Low")
    return {"target": target, "stage": stage, "barrier": d, "objectives": obj,
            "strategy": strat, "confidence": tc, "attempt": attempt, "caution": caution,
            "mental_model": mental_model(target), "model_fix": mental_model_diagnosis(target),
            "cognitive_state": cognitive_state(sig),
            "depth": target_depth(stage), "build_mix": build_mix(sig.get("mastery"), stage, d["barrier"]),
            "exam_tricks": exam_tricks(target),
            "escalate": bool(strat.get("escalate"))}
