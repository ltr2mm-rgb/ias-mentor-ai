"""
AIVORA PrepOS engine — the decision brain behind the "Today" screen.

Heuristic and fully transparent: from the candidate's real answer history it builds
a Knowledge Map, a digital-twin scorecard, a probabilistic Prelims forecast, the
adaptive daily mission, and proactive interventions. No black-box model — every
number is derived from the candidate's own data and is clearly an estimate.
"""
import datetime
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
                        "text": f"Biggest score lever: {lever['subject']} (now {lever['mastery']}%). Gains here move your Prelims score the most."})
    return out[:4]


def checkins(profile, scores, km, attempts, answers, review_due, today):
    """Proactive 'AIVORA reaching out first' messages for the dashboard — surfaced
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
        lines.append(f"Knowledge {scores['knowledge']}% · Readiness {scores['readiness']}% · "
                     f"Retention {scores['retention']}%.")
    lines.append(f"Today's mission is sized to about {mission['est_label']} of focused work.")
    return lines
