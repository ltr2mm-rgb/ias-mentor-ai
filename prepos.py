"""
AIMENTORA PrepOS engine — the decision brain behind the "Today" screen.

Heuristic and fully transparent: from the candidate's real answer history it builds
a Knowledge Map, a digital-twin scorecard, a probabilistic Prelims forecast, the
adaptive daily mission, and proactive interventions. No black-box model — every
number is derived from the candidate's own data and is clearly an estimate.
"""
import datetime
import math
from collections import defaultdict

# available study minutes by profile bucket
HOURS_MIN = {"0-2": 90, "2-4": 180, "4-6": 300, "6+": 420,
             "6-8": 420, "8-10": 540, "10-12": 660, "12+": 720}


def _pct(n, d):
    return round(100 * n / d) if d else 0


def _date(x):
    if x is None:
        return None
    return x.date() if hasattr(x, "date") else x


# ── Knowledge Map (concept graph) with forgetting-curve retention ─────────────
def _retention(mastery, last_days):
    """Ebbinghaus-style decay: well-learned concepts decay slower.
    halflife grows with mastery (7 days at 0%, ~28 days at 100%)."""
    if last_days is None:
        return mastery
    halflife = 7.0 + mastery * 0.21
    return max(0, round(mastery * (0.5 ** (max(0, last_days) / halflife))))


def build_knowledge_map(answers, today=None):
    def mk():
        return {"att": 0, "cor": 0, "last": None}
    subj = defaultdict(lambda: {"att": 0, "cor": 0, "last": None, "topics": defaultdict(mk)})
    for a in answers:
        s = a.get("subject") or "General"
        d = _date(a.get("completed_at"))
        subj[s]["att"] += 1
        if a.get("is_correct"):
            subj[s]["cor"] += 1
        if d and (subj[s]["last"] is None or d > subj[s]["last"]):
            subj[s]["last"] = d
        t = a.get("topic")
        if t:
            tp = subj[s]["topics"][t]
            tp["att"] += 1
            if a.get("is_correct"):
                tp["cor"] += 1
            if d and (tp["last"] is None or d > tp["last"]):
                tp["last"] = d
    out = []
    for s, d in subj.items():
        s_mastery = _pct(d["cor"], d["att"])
        s_days = (today - d["last"]).days if (today and d["last"]) else None
        concepts = []
        for t, c in d["topics"].items():
            if c["att"] < 3:
                continue
            cm = _pct(c["cor"], c["att"])
            cdays = (today - c["last"]).days if (today and c["last"]) else None
            concepts.append({"name": t, "mastery": cm, "attempted": c["att"],
                             "retention": _retention(cm, cdays), "last_days": cdays})
        concepts.sort(key=lambda x: (x["retention"], x["mastery"]))
        out.append({"subject": s, "mastery": s_mastery, "attempted": d["att"],
                    "retention": _retention(s_mastery, s_days), "last_days": s_days,
                    "concepts": concepts})
    out.sort(key=lambda x: (x["retention"], x["mastery"], -x["attempted"]))
    return out


# ── Digital-twin scorecard ────────────────────────────────────────────────────
def compute_scores(answers, review_items, attempts, coverage_pct, today, writing_avg=None):
    n = len(answers)
    recent = answers[-200:]
    recent_acc = _pct(sum(1 for a in recent if a.get("is_correct")), len(recent))
    overall_acc = _pct(sum(1 for a in answers if a.get("is_correct")), n)

    seen = sum((r.get("times_seen") or 0) for r in review_items)
    corr = sum((r.get("times_correct") or 0) for r in review_items)
    overdue = sum(1 for r in review_items
                  if r.get("next_review") and _date(r["next_review"]) < today and not r.get("mastered"))
    retention = _pct(corr, seen) if seen else recent_acc
    retention = max(0, retention - min(20, overdue))

    days = set()
    for at in attempts:
        d = _date(at.get("completed_at"))
        if d and (today - d).days < 14:
            days.add(d)
    consistency = _pct(len(days), 14)

    rtot = len(review_items)
    rmast = sum(1 for r in review_items if r.get("mastered"))
    revision_eff = _pct(rmast, rtot) if rtot else 0

    km = build_knowledge_map(answers, today)
    ksubs = [s for s in km if s["attempted"] >= 5]
    if ksubs:
        wsum = sum(min(s["attempted"], 40) for s in ksubs)
        knowledge = round(sum(s["mastery"] * min(s["attempted"], 40) for s in ksubs) / wsum)
    else:
        knowledge = recent_acc

    readiness = round(0.5 * knowledge + 0.3 * coverage_pct + 0.2 * recent_acc)

    times = [a.get("time_taken") for a in answers if a.get("time_taken")]
    avg_sec = round(sum(times) / len(times), 1) if times else None
    if times:
        time_mgmt = max(40, round(100 - abs(avg_sec - 72) * 0.5))
        # reading/processing speed: faster-but-accurate scores higher; ideal band ~45-75s
        if avg_sec <= 75:
            reading_speed = min(100, round(60 + (75 - avg_sec) * 0.8))
        else:
            reading_speed = max(35, round(60 - (avg_sec - 75) * 0.6))
    else:
        time_mgmt = None
        reading_speed = None

    writing_quality = round(writing_avg) if writing_avg is not None else None

    sp = round(0.40 * readiness + 0.25 * knowledge + 0.20 * consistency + 0.15 * retention)
    sp = max(5, min(92, sp))

    has_data = n >= 20
    return {
        "knowledge": knowledge, "readiness": readiness, "retention": retention,
        "consistency": consistency, "revision_efficiency": revision_eff,
        "time_management": time_mgmt, "reading_speed": reading_speed,
        "writing_quality": writing_quality, "avg_seconds_per_q": avg_sec,
        "success_probability": sp,
        "overall_accuracy": overall_acc, "recent_accuracy": recent_acc,
        "answered": n, "coverage": coverage_pct, "overdue_revision": overdue,
        "has_enough_data": has_data,
    }


# ── Current Growth Lever (the one bottleneck to focus on) ─────────────────────
def growth_lever(scores, profile=None):
    """Pick the single dimension whose improvement is predicted to lift readiness
    most, weighted by how far below target it sits (theory-of-constraints). Only
    considers dimensions we have actually measured; returns a positive, learner-
    facing message. See ENGINEERING_SPEC.md §4."""
    p = profile or {}
    dims = []
    def _add(key, label, level, target, weight):
        if isinstance(level, (int, float)):
            dims.append((key, label, float(level), float(target), float(weight)))
    _add("knowledge", "Knowledge", scores.get("knowledge"), 70, 1.0)
    _add("reasoning", "CSAT reasoning", p.get("diagnostic_csat"), 70, 1.3)
    if scores.get("has_enough_data"):
        _add("retention", "Retention", scores.get("retention"), 70, 1.2)
        _add("exam_skills", "Exam technique", scores.get("time_management"), 65, 1.3)
        _add("consistency", "Consistency", scores.get("consistency"), 60, 0.8)
    if not dims:
        return {"key": "foundation", "label": "Building your base", "measured": False,
                "message": "We're still learning how you study — a few tests will reveal "
                           "your biggest Growth Lever."}
    scored = [(k, lbl, lv, round(w * max(0.0, t - lv) / t, 3)) for (k, lbl, lv, t, w) in dims]
    scored.sort(key=lambda x: -x[3])
    key, label, level, drag = scored[0]
    if drag <= 0:
        return {"key": "balanced", "label": "Well-balanced", "measured": True,
                "level": round(level),
                "message": "No single weak spot stands out — keep your momentum across the board."}
    return {"key": key, "label": label, "level": round(level), "drag": drag, "measured": True,
            "message": f"Your Current Growth Lever is {label}. Improving it is expected to "
                       f"lift your readiness the most over the next few weeks."}


# What each mission task-kind is expected to do, and what "done well" looks like.
_TASK_IMPACT = {
    "revise": ("Locks in what you'd otherwise forget", "Clear all due cards"),
    "subject_test": ("Lifts mastery in your weakest area", "Score ≥ 80%"),
    "ncert_test": ("Turns reading into recall", "Score ≥ 80%"),
    "csat": ("Builds CSAT reliability so it can't derail you", "Score ≥ 70%"),
    "ca": ("Compounds daily across Prelims + Mains", "Note 5 points, each linked to a static topic"),
    "explain": ("Clears a repeat mistake at its root", "You can re-explain the concept in your own words"),
    "read": ("Moves your syllabus coverage forward", "Finish the reading + note the key points"),
    "guided": ("Keeps your syllabus coverage on pace", "Finish today's guided step"),
    "mains": ("Converts knowledge into Mains marks", "Get an AI evaluation on your answer"),
}
def _annotate_task(t):
    imp, suc = _TASK_IMPACT.get(t.get("kind"), ("Moves you toward exam-readiness", "Complete the task"))
    t.setdefault("impact", imp)
    t.setdefault("success", suc)


# ── Measurement Report (the doctor's-style "first mentor conversation") ────────
def _stage_from(scores):
    k = scores.get("knowledge") or 0
    return "Foundation" if k < 45 else ("Intermediate" if k < 70 else "Advanced")


def measurement_report(scores, km, lever=None, profile=None, interventions_list=None):
    """A relatable, mentor-voice read of the learner: summary, strengths, focus
    areas, risk factors, and learning style. Every line is derived from a measured
    signal — never invented. See AI_MARGA_OS.md §5.3."""
    p = profile or {}
    inter = interventions_list or []
    strengths, weaknesses, risks = [], [], []

    for key, label in (("knowledge", "knowledge base"), ("retention", "retention"),
                       ("consistency", "consistency"), ("time_management", "time management"),
                       ("reading_speed", "reading speed")):
        v = scores.get(key)
        if not isinstance(v, (int, float)):
            continue
        if v >= 70:
            strengths.append(f"Strong {label} ({v}%)")
        elif v < 45:
            weaknesses.append(f"{label.capitalize()} needs work ({v}%)")

    csat = p.get("diagnostic_csat")
    if isinstance(csat, (int, float)):
        if csat >= 70:
            strengths.append(f"Solid CSAT reasoning ({csat}%)")
        elif csat < 55:
            weaknesses.append(f"CSAT reasoning is a weak spot ({csat}%)")

    subs = [s for s in (km or []) if s.get("attempted", 0) >= 5]
    best = max(subs, key=lambda s: s["mastery"]) if subs else None
    worst = min(subs, key=lambda s: s["mastery"]) if subs else None
    if best and best["mastery"] >= 60:
        strengths.append(f"{best['subject']} is a strength ({best['mastery']}%)")
    if worst and worst is not best and worst["mastery"] < 50:
        weaknesses.append(f"{worst['subject']} is your weakest subject ({worst['mastery']}%)")

    for iv in inter:
        if iv.get("type") in ("overconfidence", "forgetting", "coach", "burnout", "inactive"):
            risks.append(iv.get("text"))
    fr = (p.get("failure_reason") or "").lower()
    if any(w in fr for w in ("negativ", "guess", "accuracy", "careless", "silly")):
        risks.append("You've lost marks to negative marking before — attempt only when you can "
                     "eliminate two options.")
    fs = (p.get("failure_stage") or "").lower()
    if "prelim" in fs:
        risks.append("You've fallen short at Prelims before — treat CSAT and accuracy as non-negotiable.")

    ls = (p.get("learning_style") or "").lower()
    ret = scores.get("retention")
    if "visual" in ls:
        style = "You learn best from visuals — maps and diagrams stick better for you than dense text."
    elif "reading" in ls:
        style = "You're a reading-first learner — depth over speed suits how you absorb material."
    elif isinstance(ret, (int, float)) and ret < 45:
        style = "Your retention drops quickly — frequent, spaced revision is what keeps knowledge in place for you."
    else:
        style = "You learn steadily from a mix of reading and practice — keep both in your daily rhythm."

    stage = _stage_from(scores)
    lv = lever or {}
    if isinstance(scores.get("knowledge"), (int, float)) and scores["knowledge"] >= 70:
        lead = f"a strong knowledge base ({scores['knowledge']}%)"
    elif isinstance(csat, (int, float)) and csat >= 70:
        lead = f"solid reasoning ({csat}%)"
    elif best and best["mastery"] >= 60:
        lead = f"a real strength in {best['subject']}"
    else:
        lead = f"a {stage.lower()} base to build on"

    if not scores.get("has_enough_data"):
        summary = ("We're still getting to know how you study — take a few practice sets and this "
                   f"report will sharpen fast. For now your plan is calibrated to a {stage} start.")
    elif lv.get("measured") and lv.get("label"):
        summary = (f"You have {lead}. The single biggest lever on your score right now is "
                   f"{lv['label']} — not a lack of effort. Improve that, and the rest lifts with it.")
    elif weaknesses:
        summary = f"You have {lead}, and the main gap to close next is {weaknesses[0].lower()}."
    else:
        summary = f"You're in balanced shape — {lead}, with no single weak spot dragging you down."

    return {
        "summary": summary, "stage": stage,
        "strengths": strengths[:4], "weaknesses": weaknesses[:4],
        "risks": risks[:3], "learning_style": style,
        "has_enough_data": bool(scores.get("has_enough_data")),
    }


# ── Prediction Engine (current vs. expected chance, with confidence) ──────────
def prediction(scores, fcast=None, lever=None, days_left=None):
    """Estimate the probability of clearing NOW vs. AFTER following the plan, each
    with a confidence from evidence volume. An honest estimate that widens its
    confidence when data is thin — never a guarantee. See AI_MARGA_OS.md §5.9."""
    n = scores.get("answered", 0) or 0
    conf = "Low" if n < 150 else ("Medium" if n < 600 else "High")
    if not scores.get("has_enough_data"):
        conf = "Low"

    # Current readiness-to-clear: the composite strength (readiness, knowledge,
    # consistency, retention) — floored so it never reads as a demotivating "1%".
    # A learner should always see a number they can grow, not one that judges them.
    cur = scores.get("success_probability")
    if not isinstance(cur, (int, float)):
        cur = round(0.6 * (scores.get("recent_accuracy") or 0))
    cur = int(max(8, min(92, round(cur))))

    # Expected-after-plan reflects the RUNWAY: with more time left, a learner who
    # follows the plan closes more of the gap to a comfortable ceiling — so a
    # beginner with a long runway sees a motivating (but still honest) target.
    dl = days_left if isinstance(days_left, (int, float)) and days_left > 0 else 120
    runway = max(0.0, min(1.0, dl / 300.0))       # ~300+ days ≈ full closing potential
    ceiling = 85.0
    exp = cur + (ceiling - cur) * runway * 0.55
    exp = int(max(cur + 2, min(90, round(exp))))

    # What the current number is built from — shown so the estimate feels earned,
    # not mysterious (theory: trust rises when the model explains itself).
    basis = []
    for key, label in (("knowledge", "Knowledge"), ("retention", "Retention"),
                       ("readiness", "Exam readiness"), ("consistency", "Consistency")):
        v = scores.get(key)
        if isinstance(v, (int, float)):
            basis.append({"label": label, "value": int(round(v))})
    return {
        "current": {"probability": cur, "confidence": conf},
        "expected": {"probability": exp, "confidence": conf},
        "target": (fcast or {}).get("target") or "Prelims",
        "days_left": int(dl),
        "basis": basis,
        "measured": bool(scores.get("has_enough_data")),
        "note": "“If you follow this plan” closes part of the gap in the time you have "
                "left. An estimate from your own trends — it rises as you practise, and "
                "is a forecast, not a guarantee.",
    }


# ── Progress (the 5 layers — "am I getting closer to clearing?") ──────────────
_JOURNEY_STAGES = ["Foundation", "Standard Books", "Concept Integration",
                   "Prelims Mastery", "Mains Excellence", "Interview Readiness"]


def _pdate(s):
    try:
        y, m, d = (int(x) for x in str(s).split("-")[:3])
        return datetime.date(y, m, d)
    except Exception:
        return None


def snapshot_row(scores, pred, today):
    """One day's numbers, stored so movement/deltas can be shown later."""
    return {"d": today.isoformat(),
            "k": scores.get("knowledge"), "r": scores.get("readiness"),
            "ret": scores.get("retention"), "c": scores.get("consistency"),
            "sp": ((pred or {}).get("current") or {}).get("probability"),
            "ans": scores.get("answered", 0)}


def _streak(attempts, answers, today):
    days = set()
    for a in (answers or []):
        d = _date(a.get("completed_at"))
        if d:
            days.add(d)
    for at in (attempts or []):
        d = _date(at.get("completed_at"))
        if d:
            days.add(d)
    if not days:
        return 0
    cur = today if today in days else (today - datetime.timedelta(days=1))
    s = 0
    while cur in days:
        s += 1
        cur -= datetime.timedelta(days=1)
    return s


def progress(scores, pred, history, review_items, attempts, answers,
             syl_done, coverage_pct, days_left, exam_label, name, today):
    """Assemble the five progress layers, framed around 'am I getting closer?'.
    Deltas need history; when it's thin we flag `gathering` and hide movement."""
    hist = history or []
    todays = today.isoformat()
    past = [h for h in hist if h.get("d") and h["d"] != todays]
    yprior = past[-1] if past else None
    prior = None
    if past:
        target = today - datetime.timedelta(days=7)
        prior = min(past, key=lambda h: abs(((_pdate(h["d"]) or today) - target).days))

    def _delta(now, key):
        if not prior or now is None or prior.get(key) is None:
            return None
        return int(round(now - prior[key]))

    # Layer 1 — Journey (macro: where am I)
    pct = coverage_pct or 0
    si = 1
    for i, thr in enumerate((15, 35, 60, 80, 95)):
        if pct >= thr:
            si = i + 2
    si = min(6, si)
    journey = {"stage_index": si, "total": 6, "stage": _JOURNEY_STAGES[si - 1],
               "stages": list(_JOURNEY_STAGES),
               "pct": pct, "eta": exam_label or "your exam", "days_left": days_left}

    # Layer 2 — Growth (with weekly deltas)
    _k = {"knowledge": "k", "readiness": "r", "retention": "ret", "consistency": "c"}
    growth = []
    for key, label in (("knowledge", "Knowledge"), ("readiness", "Readiness"),
                       ("retention", "Retention"), ("consistency", "Consistency")):
        v = scores.get(key)
        growth.append({"key": key, "label": label,
                       "value": (v if v is not None else 0), "delta": _delta(v, _k[key])})

    # Layer 3 — Evidence (concrete wins)
    evidence = {"streak": _streak(attempts, answers, today),
                "questions": scores.get("answered", 0),
                "mastered": sum(1 for r in (review_items or []) if r.get("mastered")),
                "topics": syl_done or 0,
                "mocks": len(attempts or [])}

    # Layer 4 — Outcome (hope: chance of clearing, and how it moved)
    cur_sp = ((pred or {}).get("current") or {}).get("probability")
    prev_sp = prior.get("sp") if prior else None
    outcome = {"prob": cur_sp, "prev": prev_sp,
               "delta": (int(round(cur_sp - prev_sp)) if (cur_sp is not None and prev_sp is not None) else None),
               "confidence": ((pred or {}).get("current") or {}).get("confidence"),
               "measured": bool((pred or {}).get("measured"))}

    # Chance — the motivating "how am I doing" number: current → expected, its
    # weekly trend, what it's built from, and how sure we are. Never leads with a
    # demotivating figure (see prediction(): current is floored & composite-based).
    chance = {
        "current": ((pred or {}).get("current") or {}).get("probability"),
        "expected": ((pred or {}).get("expected") or {}).get("probability"),
        "delta": outcome["delta"],
        "confidence": ((pred or {}).get("current") or {}).get("confidence") or "Low",
        "basis": (pred or {}).get("basis") or [],
        "measured": bool((pred or {}).get("measured")),
    }

    # Yesterday's Win — celebrate concrete improvement since the last session, so
    # opening the app rewards effort (the dopamine loop that brings learners back).
    ywins = []
    if yprior:
        for score_key, snap_key, label in (("knowledge", "k", "Knowledge"),
                                           ("readiness", "r", "Readiness"),
                                           ("retention", "ret", "Retention"),
                                           ("consistency", "c", "Consistency")):
            now = scores.get(score_key)
            was = yprior.get(snap_key)
            if isinstance(now, (int, float)) and isinstance(was, (int, float)) and now - was > 0:
                ywins.append(f"{label} +{int(round(now - was))}%")
        qd = (scores.get("answered", 0) or 0) - (yprior.get("ans") or 0)
        if qd > 0:
            ywins.append(f"Completed {qd} question" + ("s" if qd != 1 else ""))
    st = evidence["streak"]
    if st >= 2:
        ywins.append(f"{st}-day streak")
    yesterday = {"has": bool(ywins), "items": ywins}

    # Layer 5 — Momentum (today's win — the single strongest movement)
    win = None
    if yprior:
        ups = sorted([g for g in growth if g.get("delta") and g["delta"] > 0],
                     key=lambda g: -g["delta"])
        if ups:
            win = f"Your {ups[0]['label']} is up +{ups[0]['delta']}% — nice."

    # Weekly Improvement — this week's tangible effort (Progress dashboard).
    wk_ago = today - datetime.timedelta(days=7)
    def _cd(x):                       # robust to datetime, date, or ISO-string inputs
        d = _date(x)
        if isinstance(d, str):
            d = _pdate(d)
        return d if isinstance(d, datetime.date) else None
    def _recent(items):
        return sum(1 for it in (items or [])
                   if (_cd(it.get("completed_at")) or datetime.date(1900, 1, 1)) > wk_ago)
    secs_week = sum((a.get("time_taken") or 0) for a in (answers or [])
                    if (_cd(a.get("completed_at")) or datetime.date(1900, 1, 1)) > wk_ago)
    weekly = {"questions": _recent(answers), "mocks": _recent(attempts),
              "hours": round(secs_week / 3600.0, 1) if secs_week else 0,
              "mastered": evidence["mastered"], "streak": evidence["streak"]}

    # Growth History — the readiness composite over time (Progress sparkline).
    trend_series = [{"d": h.get("d"), "v": h.get("sp")} for h in hist if h.get("sp") is not None]

    # Achievements — a short, honest timeline of milestones actually crossed.
    ach = []
    if yesterday["has"] and yesterday["items"]:
        ach.append({"when": "Yesterday", "text": yesterday["items"][0]})
    r_now = scores.get("readiness")
    r0 = next((h.get("r") for h in hist if h.get("r") is not None), None)
    if isinstance(r_now, (int, float)) and isinstance(r0, (int, float)):
        for thr in (25, 35, 50, 65):
            if r0 < thr <= r_now:
                ach.append({"when": "Recently", "text": f"Readiness crossed {thr}%"})
    if journey["stage_index"] > 1:
        ach.append({"when": "Milestone", "text": "Reached " + journey["stage"]})

    return {"hope": "You're getting closer.", "greeting_name": name,
            "journey": journey, "growth": growth, "evidence": evidence,
            "outcome": outcome, "chance": chance, "yesterday": yesterday, "win": win,
            "weekly": weekly, "trend_series": trend_series, "achievements": ach[:5],
            "gathering": (len(past) == 0),
            "has_enough_data": bool(scores.get("has_enough_data"))}


# ── Decision Engine (choose the one highest-leverage next action) ─────────────
def _decision(action, title, detail, why, task_key, pred):
    toward = None
    if pred and pred.get("measured"):
        toward = "a step toward your {}% target".format(pred["expected"]["probability"])
    return {"action": action, "title": title, "detail": detail, "why": why,
            "task_key": task_key, "toward": toward}


# ── Mission as a LEARNING OUTCOME: an adaptive Learn/Revise → Practice → Analyze
# cycle. The Decision Engine picks the outcome; the sequence adapts to the learner's
# Digital Twin (learn when the concept is weak, revise when it's known but fading).
def _low(v):
    return (not isinstance(v, (int, float))) or v < 55


def _learn_phase(target, minutes=8):
    return {"n": 1, "kind": "learn", "minutes": minutes,
            "title": f"Learn — {target}", "detail": "Concept, worked examples & the traps to avoid."}


def _revise_phase(target, review_due=0, minutes=6):
    extra = f" · {review_due} due cards" if review_due else ""
    return {"n": 1, "kind": "revise", "minutes": minutes,
            "title": f"Quick revision — {target}{extra}",
            "detail": "You know this — a fast recall pass to lock it back in."}


def _outcome_plan(action, scores, profile, km, review_due):
    """Turn the chosen action into an outcome + an adaptive 3-phase mission."""
    p = profile or {}
    ret = scores.get("retention")
    if action == "revise":
        target, objective, level = "your weak concepts", "Strengthen your Retention", None
        step1 = _revise_phase(target, review_due)
        practice_title, practice_min = "Recall check — a short quiz on what you just revised", 12
    elif action == "practise_csat":
        target, objective, level = "CSAT logical reasoning", "Improve your CSAT Logical Reasoning", p.get("diagnostic_csat")
        step1 = _learn_phase(target) if _low(level) else _revise_phase(target, review_due)
        practice_title, practice_min = "Practice — 15 adaptive CSAT questions", 20
    elif action == "practise_weak":
        subj = (km[0].get("subject") if km else "your weakest subject")
        target, objective, level = subj, f"Master {subj}", (km[0].get("mastery") if km else None)
        step1 = _learn_phase(target) if _low(level) else _revise_phase(target, review_due)
        practice_title, practice_min = f"Practice — 25 {subj} questions", 20
    elif action == "accuracy_drill":
        target, objective, level = "exam technique", "Sharpen your exam technique", scores.get("time_management")
        step1 = _learn_phase("elimination & timing technique") if _low(level) else _revise_phase("your technique tips", review_due)
        practice_title, practice_min = "Practice — 25 mixed MCQs against the clock", 20
    else:  # continue / coverage
        target, objective, level = "today's topic", "Advance your syllabus", None
        step1 = _learn_phase("today's reading")
        practice_title, practice_min = "Quick check — questions on what you just read", 15
    practice = {"n": 2, "kind": "practice", "minutes": practice_min, "title": practice_title,
                "detail": "Adaptive questions at the right difficulty for you."}
    analyze = {"n": 3, "kind": "analyze", "minutes": 5,
               "title": "AI analysis — why you missed & what to lock in",
               "detail": "Mistakes explained, weak concepts flagged, revision cards made."}
    phases = [step1, practice, analyze]
    return {"objective": objective, "target": target, "phases": phases,
            "est_minutes": sum(x["minutes"] for x in phases)}


def _mk(d, scores, profile, km, review_due):
    d.update(_outcome_plan(d.get("action"), scores, profile, km, review_due))
    return d


def decide(scores, lever=None, review_due=0, km=None, profile=None, pred=None):
    """The explicit, evidence-traced policy: given the learner's state, the Growth
    Lever, and the forecast, choose the single highest-leverage OUTCOME for today,
    delivered as an adaptive Learn/Revise → Practice → Analyze cycle.
    Rule-based and transparent — every decision carries its triggering evidence.
    See AI_MARGA_OS.md §5.9 / ENGINEERING_SPEC §6."""
    km = km or []
    lev = lever or {}
    lev_key = lev.get("key")
    lev_label = lev.get("label", "your Growth Lever")
    ret = scores.get("retention")

    # 1) Fading memory + retention is the lever → revise (highest return).
    if review_due and review_due >= 3 and (lev_key == "retention" or (isinstance(ret, (int, float)) and ret < 45)):
        why = [f"{lev_label} is your Growth Lever" + (f" ({ret}%)" if isinstance(ret, (int, float)) else ""),
               f"{review_due} cards are overdue",
               "spaced repetition is the highest-return action right now"]
        return _mk(_decision("revise", f"Clear your {review_due} due revision cards",
                         "Lock in what you'd otherwise forget before adding anything new.",
                         why, "revise_due", pred), scores, profile, km, review_due)

    # 2) Reasoning/CSAT is the lever → CSAT practice.
    if lev_key == "reasoning":
        why = [f"{lev_label} is your Growth Lever", "CSAT can qualify or sink a Prelims attempt"]
        return _mk(_decision("practise_csat", "Do a CSAT practice set",
                         "Comprehension + reasoning — treat CSAT as a daily must.", why, "csat", pred),
                   scores, profile, km, review_due)

    # 3) A clear weakest subject → targeted practice.
    weak = km[0] if km else None
    if weak and weak.get("attempted", 0) >= 5 and weak.get("mastery", 100) < 70:
        why = [f"{weak['subject']} is your weakest subject ({weak['mastery']}%)",
               "targeted practice here moves your score the most"]
        return _mk(_decision("practise_weak", f"Practise {weak['subject']} — 25 MCQs",
                         f"Your weakest area at {weak['mastery']}% — 25 targeted questions to lift it.",
                         why, f"weak_mcq:{weak['subject']}", pred), scores, profile, km, review_due)

    # 4) Exam technique is the lever → accuracy drill.
    tm = scores.get("time_management")
    if lev_key == "exam_skills" or (isinstance(tm, (int, float)) and tm < 45):
        why = ["Exam technique is your Growth Lever",
               "accuracy and timing decide Prelims under negative marking"]
        return _mk(_decision("accuracy_drill", "Run an accuracy drill — 25 mixed MCQs",
                         "Attempt only when you can eliminate two options — chase strike-rate.",
                         why, "accuracy_drill", pred), scores, profile, km, review_due)

    # 5) Nothing urgent → keep the plan moving.
    why = ["No urgent gap stands out today", "keep your syllabus coverage moving"]
    return _mk(_decision("continue", "Continue your guided step",
                     "Keep momentum on the next step of your plan.", why, "coverage", pred),
               scores, profile, km, review_due)


# ── Probabilistic forecast ────────────────────────────────────────────────────
def forecast(scores, target_label):
    acc = scores["recent_accuracy"] / 100.0
    n = scores["answered"]
    attempts = 90                                  # assumed Prelims attempts of 100
    raw = attempts * acc * 2 - attempts * (1 - acc) * (2.0 / 3.0)
    base = max(0, round(raw))
    band = 16 if n < 150 else (10 if n < 500 else 6)
    low, high = max(0, base - band), min(200, base + band)
    conf = "low — needs more practice data" if n < 150 else ("moderate" if n < 600 else "improving")
    if base >= 105:
        clearing = "Strong — comfortably above recent cutoffs"
    elif base >= 90:
        clearing = "On track — around the cutoff zone"
    elif base >= 70:
        clearing = "Borderline — needs focused improvement"
    else:
        clearing = "Below cutoff — build fundamentals first"
    return {
        "prelims_range": f"{low}–{high}", "prelims_base": base,
        "confidence": conf, "clearing": clearing,
        "projection_range": f"{min(200, low + 12)}–{min(200, high + 14)}",
        "target": target_label,
    }


# ── Adaptive daily mission ────────────────────────────────────────────────────
def daily_mission(km, review_due, hours_bucket, next_coverage, today, profile=None):
    """Build the day's tailor-made task list. `profile` (a dict of the candidate's
    intake + diagnostic signals) personalises WHICH tasks appear, their difficulty,
    and adds a 'why this task for you' line to each."""
    p = profile or {}
    avail = HOURS_MIN.get(hours_bucket if hours_bucket in HOURS_MIN else "2-4", 180)
    # Working candidates get a tighter, more doable list — tighter still if they
    # work full-time (prep_intensity now describes the working commitment).
    intensity = (p.get("prep_intensity") or "").lower()
    if p.get("working_professional"):
        avail = min(avail, 120 if "full" in intensity else 150)
    tasks = []

    def add(key, kind, title, detail, minutes, params, why=""):
        tasks.append({"key": key, "kind": kind, "title": title, "detail": detail,
                      "minutes": minutes, "params": params, "why": why})

    # Baseline difficulty from the diagnostic (or self-rating) when we lack per-subject data.
    def _base_diff():
        g = p.get("diagnostic_gs")
        if isinstance(g, (int, float)):
            return "easy" if g < 45 else ("medium" if g < 70 else "hard")
        kl = (p.get("knowledge_level") or "").lower()
        if kl == "low":
            return "easy"
        if kl == "strong":
            return "hard"
        return "medium"

    base_src = "diagnostic" if isinstance(p.get("diagnostic_gs"), (int, float)) else "self-rated level"

    # Should CSAT be a daily priority for this candidate?
    csat_priority, csat_why = False, ""
    cs = (p.get("comprehension_skill") or "").lower()
    dc = p.get("diagnostic_csat")
    fs = (p.get("failure_stage") or "").lower()
    fr = (p.get("failure_reason") or "").lower()
    if (isinstance(dc, (int, float)) and dc < 55) or "improv" in cs or "weak" in cs:
        csat_priority, csat_why = True, "your comprehension/reasoning is a current weak spot"
    if "prelim" in fs or "csat" in fr:
        csat_priority, csat_why = True, "you've fallen short at Prelims before — CSAT can't be left to chance"

    # 1) Spaced-repetition queue (always first when due).
    if review_due > 0:
        add("revise_due", "revise", f"Revise {review_due} due card{'s' if review_due > 1 else ''}",
            "Clear today's spaced-repetition queue first — the cheapest marks you'll earn.",
            min(35, max(10, review_due * 2)), {},
            why="Spaced repetition locks in what you'd otherwise forget — highest return per minute.")

    # 2) Weakest-subject practice — from data if we have it, else from what they declared.
    weakest = km[0] if km else None
    if weakest and weakest["attempted"] >= 5:
        m = weakest["mastery"]
        diff = "easy" if m < 50 else ("medium" if m < 70 else "hard")
        diff_note = {"easy": "starting easy to build confidence",
                     "medium": "medium difficulty to consolidate",
                     "hard": "stepping up to hard — you're ready"}[diff]
        add(f"weak_mcq:{weakest['subject']}", "subject_test", f"25 {diff.title()} MCQs — {weakest['subject']}",
            f"Weakest area at {m}% mastery ({diff_note}). 25 targeted questions to lift it.",
            30, {"subject": weakest["subject"], "count": 25, "difficulty": diff},
            why=f"Your data shows {weakest['subject']} is weakest ({m}% mastery) — the fastest place to gain marks.")
        if weakest["concepts"]:
            c = weakest["concepts"][0]
            add(f"concept:{weakest['subject']}", "explain", f"Clear up: {c['name']}",
                f"Weakest concept ({c['mastery']}%) in {weakest['subject']} — get an AI explanation.",
                20, {"subject": weakest["subject"], "topic": c["name"]},
                why=f"You keep missing {c['name']} — clearing the concept stops the repeat mistakes.")
    else:
        weak_declared = [s.strip() for s in (p.get("weak_subjects") or "").split(",") if s.strip()]
        if weak_declared:
            subj = weak_declared[0]
            diff = _base_diff()
            add(f"weak_mcq:{subj}", "subject_test", f"25 {diff.title()} MCQs — {subj}",
                f"Begin on a subject you flagged as weak. 25 questions at {diff} level.",
                30, {"subject": subj, "count": 25, "difficulty": diff},
                why=f"You marked {subj} as weak and we don't have your practice data yet — starting here at {diff} level, matched to your {base_src}.")

    # 3) CSAT as a daily priority when this candidate needs it.
    if csat_priority:
        add("csat", "csat", "CSAT practice set — priority",
            "Comprehension + reasoning. Treat CSAT as a daily must, not an afterthought.",
            25, {"area": "reasoning"},
            why=f"Made a daily priority because {csat_why}.")

    # 3a) Accuracy / negative-marking discipline when that's their leak.
    if any(w in fr for w in ("negativ", "guess", "accuracy", "careless", "silly")):
        subj = next((s.strip() for s in (p.get("weak_subjects") or "").split(",") if s.strip()),
                    "General Studies")
        add("accuracy_drill", "subject_test", "Accuracy drill — 25 mixed MCQs",
            "Attempt a question only when you can eliminate at least two options. Chase strike-rate, not coverage.",
            30, {"subject": subj, "count": 25, "difficulty": "medium"},
            why="You've flagged accuracy / negative marking — this builds the discipline to attempt smart and stop leaking marks.")

    # 3b) Directly address where a repeat aspirant fell short last time.
    if "main" in fs:
        add("mains_write", "mains", "Write one Mains answer",
            "Pick a GS question, write a ~150-word answer, and get it AI-evaluated.",
            30, {"paper": "GS"},
            why="You reached Mains before — answer-writing is the skill that converts your knowledge into marks there.")
    elif "interview" in fs:
        add("interview_point", "read", "Sharpen one interview / DAF talking point",
            "Pick a likely theme from your DAF or current affairs and refine how you'd speak on it.",
            20, {},
            why="You've cleared Mains before — staying articulate on current themes is your edge in the interview.")

    # 4) Reading-first candidates get a focused deep-read.
    style = (p.get("learning_style") or "").lower()
    rs = (p.get("reading_speed") or "").lower()
    if not next_coverage and (style == "reading" or "slow" in rs):
        detail = "Deep-read one core topic and make crisp, revisable notes."
        add("read_topic", "read", "Read & note one core topic", detail, 30, {},
            why="Matched to your reading-first style — depth over speed suits how you learn.")

    # 5) Daily current-affairs habit.
    add("current_affairs", "ca", "Read today's current affairs",
        "Daily habit — note 5 points and link each to a static topic.", 30, {},
        why="Current affairs compounds daily; 5 linked points keeps Prelims + Mains covered.")

    # 6) Next guided-program step.
    if next_coverage:
        add("coverage", "guided", next_coverage.get("title", "Move the syllabus forward"),
            "The next step in your guided program — keep coverage moving.", 35, next_coverage,
            why="Keeps your syllabus coverage moving steadily toward exam-readiness.")

    # 7) Alternate-day CSAT upkeep (only if not already prioritised).
    if not csat_priority and today.toordinal() % 2 == 0:
        add("csat", "csat", "CSAT practice set",
            "Keep CSAT qualifying — comprehension + reasoning.", 25, {"area": "reasoning"},
            why="Alternate-day CSAT upkeep to stay comfortably above the qualifying line.")

    chosen, total = [], 0
    for t in tasks:
        if not chosen or total + t["minutes"] <= avail + 10:
            chosen.append(t)
            total += t["minutes"]
        if total >= avail:
            break
    for _t in chosen:
        _annotate_task(_t)
    hrs, mins = total // 60, total % 60
    est = (f"{hrs} hr {mins} min" if hrs else f"{mins} min")
    return {"tasks": chosen, "est_minutes": total, "est_label": est, "available_minutes": avail}


# ── Proactive interventions / coach ───────────────────────────────────────────
def interventions(answers, km, attempts, today):
    out = []
    last = {}
    for a in answers:
        s, d = a.get("subject"), _date(a.get("completed_at"))
        if s and d and (s not in last or d > last[s]):
            last[s] = d
    for s in km:
        sub = s["subject"]
        if sub in last and s["attempted"] >= 8:
            gap = (today - last[sub]).days
            if gap >= 12:
                out.append({"type": "forgetting",
                            "text": f"You haven't practised {sub} in {gap} days — retention is slipping. Make it today's first revision."})

    actdays = [_date(at.get("completed_at")) for at in attempts if at.get("completed_at")]
    if actdays:
        gap = (today - max(actdays)).days
        if gap >= 3:
            out.append({"type": "inactive",
                        "text": f"You've been away {gap} days. Restart light: clear due revision, then one 25-MCQ set."})

    bydiff = defaultdict(lambda: {"a": 0, "c": 0})
    for a in answers:
        d = (a.get("difficulty") or "medium").lower()
        bydiff[d]["a"] += 1
        if a.get("is_correct"):
            bydiff[d]["c"] += 1
    hard, med = bydiff.get("hard"), bydiff.get("medium")
    if hard and med and hard["a"] >= 15 and med["a"] >= 15:
        ha, ma = _pct(hard["c"], hard["a"]), _pct(med["c"], med["a"])
        if ma - ha >= 25:
            out.append({"type": "coach",
                        "text": f"Your accuracy drops from {ma}% on medium to {ha}% on hard questions. Master medium first, then escalate."})

    if km:
        lever = km[0]
        if lever["attempted"] >= 5 and lever["mastery"] < 70:
            out.append({"type": "lever",
                        "text": f"Biggest subject to gain from: {lever['subject']} ({lever['mastery']}%) — focused practice here moves your Prelims score the most."})

    # Overconfidence: answers tagged 'sure' that were wrong are hidden gaps,
    # not bad luck - the most dangerous mistake type under negative marking.
    sure = [a for a in answers if (a.get("confidence") or "").lower() == "sure"]
    if len(sure) >= 20:
        sw = sum(1 for a in sure if not a.get("is_correct"))
        pw = _pct(sw, len(sure))
        if pw >= 25:
            out.append({"type": "overconfidence",
                        "text": f"{pw}% of answers you marked 'sure' were wrong ({sw} of {len(sure)}). Those are misconceptions, not slips - open the Mistake Notebook filtered to 'sure' and clear them first."})

    # Burnout guard: ten straight heavy days with accuracy sliding means fatigue,
    # not weakness. Prescribe one light day before it costs a week.
    byday = {}
    for a in answers:
        d = _date(a.get("completed_at"))
        if d:
            byday.setdefault(d, []).append(bool(a.get("is_correct")))
    days = sorted(byday)
    if len(days) >= 10:
        run = days[-10:]
        if all((run[i + 1] - run[i]).days == 1 for i in range(9)) and \
           all(len(byday[d]) >= 30 for d in run):
            first = [x for d in run[:5] for x in byday[d]]
            lastp = [x for d in run[5:] for x in byday[d]]
            a1, a2 = _pct(sum(first), len(first)), _pct(sum(lastp), len(lastp))
            if a2 <= a1 - 8:
                out.append({"type": "burnout",
                            "text": f"Ten heavy days in a row and accuracy slid from {a1}% to {a2}%. That's fatigue, not weakness - take one light day (revision only), then resume."})
    return out[:5]


def checkins(profile, scores, km, attempts, answers, review_due, today):
    """Proactive 'AIMENTORA reaching out first' messages for the dashboard — surfaced
    BEFORE the candidate has to go looking. Each carries an icon, a CTA, and the
    panel to jump to. Returns the top few, most-urgent first."""
    p = profile or {}
    sc = scores or {}
    out = []

    def push(icon, text, cta, panel, tone="info"):
        out.append({"icon": icon, "text": text, "cta": cta, "panel": panel, "tone": tone})

    # Diagnostic not yet taken — calibrate first.
    if p.get("diagnostic_gs") is None:
        push("🎯", "Take the 5-minute diagnostic so I can calibrate your plan to your real level.",
             "Take diagnostic", "profile", "nudge")

    # A concept is fading on the forgetting curve.
    decaying = [s for s in (km or []) if s.get("attempted", 0) >= 8 and s.get("retention", 100) < 55]
    if decaying:
        s = sorted(decaying, key=lambda x: x.get("retention", 100))[0]
        push("🧠", f"Your {s['subject']} is fading ({s.get('retention', 0)}% retention). A quick revision now locks it back in.",
             "Revise now", "revision", "urgent")

    # Been away.
    actdays = [_date(at.get("completed_at")) for at in (attempts or []) if at.get("completed_at")]
    gap = (today - max(actdays)).days if actdays else None
    if gap is not None and gap >= 3:
        push("👋", f"It's been {gap} days — welcome back. Let's restart light: clear due revision, then one set.",
             "Resume today", "today", "warm")

    # Revision pile building up.
    if review_due >= 5:
        push("🔁", f"You have {review_due} cards due for revision — the cheapest marks on offer today.",
             "Clear queue", "revision", "info")

    # Close to a readiness milestone.
    rd = int(sc.get("readiness") or 0)
    nxt = (rd // 10 + 1) * 10
    if rd and 0 < (nxt - rd) <= 6 and rd < 90:
        push("🚀", f"You're only {nxt - rd} points from {nxt}% readiness — one focused week pushes you over.",
             "Keep going", "today", "win")

    # Genuinely strong — reinforce.
    if (sc.get("success_probability") or 0) >= 72:
        push("🌟", "You're in genuinely strong shape — protect this lead with steady daily reps.",
             "Today's plan", "today", "win")

    return out[:3]


def weekly_report(answers, attempts, today):
    """Compute the week-in-review: activity, accuracy trend, subject movement,
    consistency, plus trend series for charts and a summary string for the AI note."""
    def wk_acc(start, end):
        sel = [a for a in answers if a.get("completed_at") and start <= _date(a["completed_at"]) < end]
        cor = sum(1 for a in sel if a.get("is_correct"))
        return _pct(cor, len(sel)), len(sel)

    this_start = today - datetime.timedelta(days=7)
    last_start = today - datetime.timedelta(days=14)
    this_acc, this_n = wk_acc(this_start, today + datetime.timedelta(days=1))
    last_acc, last_n = wk_acc(last_start, this_start)

    tests_this = sum(1 for at in attempts if at.get("completed_at") and _date(at["completed_at"]) >= this_start)
    active_days = len({_date(a["completed_at"]) for a in answers
                       if a.get("completed_at") and _date(a["completed_at"]) >= this_start})

    # subject accuracy this week vs all-time (movement proxy)
    sub_all = defaultdict(lambda: {"a": 0, "c": 0})
    sub_wk = defaultdict(lambda: {"a": 0, "c": 0})
    for a in answers:
        s = a.get("subject") or "General"
        sub_all[s]["a"] += 1
        sub_all[s]["c"] += 1 if a.get("is_correct") else 0
        if a.get("completed_at") and _date(a["completed_at"]) >= this_start:
            sub_wk[s]["a"] += 1
            sub_wk[s]["c"] += 1 if a.get("is_correct") else 0
    moves = []
    for s, w in sub_wk.items():
        if w["a"] >= 4:
            moves.append({"subject": s, "week": _pct(w["c"], w["a"]),
                          "alltime": _pct(sub_all[s]["c"], sub_all[s]["a"]),
                          "delta": _pct(w["c"], w["a"]) - _pct(sub_all[s]["c"], sub_all[s]["a"]),
                          "attempted": w["a"]})
    moves.sort(key=lambda x: x["delta"], reverse=True)

    # 8-week accuracy trend + 14-day activity
    weekly_trend = []
    for i in range(7, -1, -1):
        s0 = today - datetime.timedelta(days=7 * (i + 1) - 1)
        s1 = today - datetime.timedelta(days=7 * i - 1)
        acc, cnt = wk_acc(s0, s1)
        weekly_trend.append({"label": f"-{i}w" if i else "now", "accuracy": acc, "count": cnt})
    daily_activity = []
    for i in range(13, -1, -1):
        d = today - datetime.timedelta(days=i)
        cnt = sum(1 for a in answers if a.get("completed_at") and _date(a["completed_at"]) == d)
        daily_activity.append({"day": d.strftime("%d %b"), "count": cnt})

    delta = this_acc - last_acc
    summary = (f"This week: {this_n} questions across {active_days} active days, {tests_this} tests. "
               f"Accuracy {this_acc}% (vs {last_acc}% last week, {'+' if delta >= 0 else ''}{delta}). "
               f"Best movement: {moves[0]['subject']} {('+' if moves[0]['delta'] >= 0 else '')}{moves[0]['delta']}%. "
               if moves else
               f"This week: {this_n} questions across {active_days} active days, {tests_this} tests. "
               f"Accuracy {this_acc}% (vs {last_acc}% last week). ")
    if moves and moves[-1]["delta"] < 0:
        summary += f"Weakest movement: {moves[-1]['subject']} {moves[-1]['delta']}%."

    return {
        "this_week": {"accuracy": this_acc, "questions": this_n, "tests": tests_this,
                      "active_days": active_days},
        "last_week": {"accuracy": last_acc, "questions": last_n},
        "accuracy_delta": delta,
        "movers_up": [m for m in moves if m["delta"] > 0][:3],
        "movers_down": [m for m in reversed(moves) if m["delta"] < 0][:3],
        "weekly_trend": weekly_trend,
        "daily_activity": daily_activity,
        "summary": summary,
        "has_data": this_n > 0 or last_n > 0,
    }


def briefing(name, scores, mission, today):
    hh = today.timetuple().tm_hour if hasattr(today, "timetuple") else 8
    greet = "Good morning" if hh < 12 else ("Good afternoon" if hh < 17 else "Good evening")
    lines = [f"{greet}, {name or 'there'}."]
    if not scores["has_enough_data"]:
        lines.append("We're still learning how you study — take a few tests and your dashboard sharpens fast.")
    else:
        lines.append(f"Mastery {scores['knowledge']}% · Readiness {scores['readiness']}% · "
                     f"Retention {scores['retention']}%.")
    lines.append(f"Today's mission is sized to about {mission['est_label']} of focused work.")
    return lines
