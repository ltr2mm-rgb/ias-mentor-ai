"""
AIVORA study planner — generates a personalised, phase-wise UPSC preparation
schedule for the time a candidate has left until their target Prelims, using
AIVORA's own features for every task. Pure, deterministic Python.
"""
import datetime


def prelims_date(year: int) -> datetime.date:
    """Approximate UPSC CSE Prelims date = last Sunday of May of the given year."""
    d = datetime.date(year, 5, 31)
    while d.weekday() != 6:  # 6 == Sunday
        d -= datetime.timedelta(days=1)
    return d


# Subject blocks (Prelims-cum-Mains base). weeks = nominal weeks on a full timeline;
# they are scaled to fit the available foundation time. panel = AIVORA tab to open.
SUBJECTS = [
    {"key": "polity", "name": "Polity & Governance", "weeks": 4.0, "emoji": "⚖️",
     "sources": "NCERT (Class 9–12 Polity) → Laxmikanth",
     "tasks": [("Read the NCERTs", "ncert"), ("Subjectwise MCQs — batch of 25/day", "subjectwise"),
               ("Standard-book MCQs (Laxmikanth)", "bookwise"), ("Solve Polity PYQs", "pyq"),
               ("Tick topics in Syllabus Tracker", "syllabus")]},
    {"key": "modern_history", "name": "Modern History & Freedom Struggle", "weeks": 3.0, "emoji": "\U0001f3db️",
     "sources": "NCERT (Class 8 & old Modern India) → Spectrum",
     "tasks": [("Read the NCERTs", "ncert"), ("Subjectwise MCQs — batch of 25/day", "subjectwise"),
               ("Standard-book MCQs (Spectrum)", "bookwise"), ("Solve History PYQs", "pyq"),
               ("Tick topics in Syllabus Tracker", "syllabus")]},
    {"key": "anc_med_history", "name": "Ancient & Medieval History", "weeks": 2.0, "emoji": "\U0001f5ff",
     "sources": "NCERT (old Ancient/Medieval) → notes",
     "tasks": [("Read the NCERTs", "ncert"), ("Subjectwise MCQs — batch of 25/day", "subjectwise"),
               ("Solve History PYQs", "pyq"), ("Tick topics in Syllabus Tracker", "syllabus")]},
    {"key": "art_culture", "name": "Art & Culture", "weeks": 1.5, "emoji": "\U0001f3a8",
     "sources": "NCERT (Intro to Indian Art) → Nitin Singhania",
     "tasks": [("Read the NCERT", "ncert"), ("Subjectwise MCQs — batch of 25/day", "subjectwise"),
               ("Solve Art & Culture PYQs", "pyq"), ("Tick topics in Syllabus Tracker", "syllabus")]},
    {"key": "geography", "name": "Geography (Physical, Indian & World)", "weeks": 4.0, "emoji": "\U0001f30d",
     "sources": "NCERT (Class 6–12 Geography) → G.C. Leong",
     "tasks": [("Read the NCERTs", "ncert"), ("Subjectwise MCQs — batch of 25/day", "subjectwise"),
               ("Standard-book MCQs (Leong)", "bookwise"), ("Solve Geography PYQs", "pyq"),
               ("Tick topics in Syllabus Tracker", "syllabus")]},
    {"key": "economy", "name": "Economy", "weeks": 4.0, "emoji": "\U0001f4b9",
     "sources": "NCERT (Class 9–12 Economics) → Ramesh Singh / Mrunal",
     "tasks": [("Read the NCERTs", "ncert"), ("Subjectwise MCQs — batch of 25/day", "subjectwise"),
               ("Standard-book MCQs", "bookwise"), ("Solve Economy PYQs", "pyq"),
               ("Tick topics in Syllabus Tracker", "syllabus")]},
    {"key": "environment", "name": "Environment & Ecology", "weeks": 2.5, "emoji": "\U0001f33f",
     "sources": "NCERT (Class 12 Biology — ecology) → Shankar IAS",
     "tasks": [("Read the source chapters", "ncert"), ("Subjectwise MCQs — batch of 25/day", "subjectwise"),
               ("Standard-book MCQs (Shankar)", "bookwise"), ("Solve Environment PYQs", "pyq"),
               ("Tick topics in Syllabus Tracker", "syllabus")]},
    {"key": "science_tech", "name": "Science & Technology", "weeks": 2.0, "emoji": "\U0001f9ea",
     "sources": "NCERT (Class 8–10 Science) → current developments",
     "tasks": [("Read the NCERTs", "ncert"), ("Subjectwise MCQs — batch of 25/day", "subjectwise"),
               ("Solve Sci & Tech PYQs", "pyq"), ("Tick topics in Syllabus Tracker", "syllabus")]},
    {"key": "society", "name": "Indian Society", "weeks": 1.0, "emoji": "\U0001f465",
     "sources": "NCERT (Sociology) → notes",
     "tasks": [("Read the NCERTs", "ncert"), ("Subjectwise MCQs — batch of 25/day", "subjectwise"),
               ("Tick topics in Syllabus Tracker", "syllabus")]},
]

HOURS_BUCKETS = {
    "0-2": {"label": "0–2 hrs/day", "routine": [
        ("Current affairs", "30 min — read + note", "studyhub"),
        ("Today's subject", "NCERT/standard reading", "ncert"),
        ("Practice", "1 batch of 25 MCQs", "subjectwise")]},
    "2-4": {"label": "2–4 hrs/day", "routine": [
        ("Current affairs", "30–40 min — read + note", "studyhub"),
        ("Subject study", "NCERT then standard source", "ncert"),
        ("Practice", "Subjectwise — 25 MCQs", "subjectwise"),
        ("Revision", "Clear today's due cards", "revision")]},
    "4-6": {"label": "4–6 hrs/day", "routine": [
        ("Current affairs", "45 min — read + note", "studyhub"),
        ("Subject study (deep)", "NCERT + standard + notes", "ncert"),
        ("Practice", "Subjectwise — 25–50 MCQs", "subjectwise"),
        ("PYQs", "Solve a subject set", "pyq"),
        ("Revision", "Spaced-repetition + mistakes", "revision"),
        ("CSAT", "alternate days — 1 set", "pyq")]},
    "6+": {"label": "6+ hrs/day", "routine": [
        ("Current affairs", "45–60 min — read + note", "studyhub"),
        ("Subject 1 (deep)", "NCERT + standard + notes", "ncert"),
        ("Practice", "Subjectwise — 50 MCQs", "subjectwise"),
        ("Subject 2 / PYQs", "second subject or PYQ set", "pyq"),
        ("Revision", "Spaced-repetition + Mistake Notebook", "revision"),
        ("CSAT", "daily — 1 set", "pyq")]},
}


def _fmt(d: datetime.date) -> str:
    return d.strftime("%d %b %Y")


def _add_weeks(d: datetime.date, weeks: float) -> datetime.date:
    return d + datetime.timedelta(days=round(weeks * 7))


def generate_plan(target_year, hours_bucket, weak_subjects, today=None):
    today = today or datetime.date.today()
    # Resolve exam date — if this year's prelims is <45 days away or past, roll to next year.
    try:
        ty = int(str(target_year)[:4])
    except Exception:
        ty = today.year + 1
    exam = prelims_date(ty)
    if (exam - today).days < 45:
        ty = max(ty + 1, today.year + 1)
        exam = prelims_date(ty)
    days_left = (exam - today).days
    weeks_left = max(1, round(days_left / 7))

    hb = hours_bucket if hours_bucket in HOURS_BUCKETS else "2-4"

    # Phase budget (in days): reserve sprint + consolidation, rest for foundation.
    sprint_days = int(min(70, max(28, days_left * 0.28)))
    consolidation_days = int(min(28, max(10, days_left * 0.12)))
    foundation_days = max(7, days_left - sprint_days - consolidation_days)
    foundation_weeks = foundation_days / 7.0

    # Prioritise weak subjects: bump their weeks and sort them earlier.
    weak = {w.strip().lower() for w in (weak_subjects or "").split(",") if w.strip()}
    subs = []
    for s in SUBJECTS:
        wks = s["weeks"]
        is_weak = any(tok in s["name"].lower() or tok in s["key"] for tok in weak)
        if is_weak:
            wks += 1.0
        subs.append({**s, "wks": wks, "weak": is_weak})
    subs.sort(key=lambda x: (not x["weak"]))  # weak subjects first

    # Scale nominal weeks to fit foundation window.
    nominal = sum(s["wks"] for s in subs)
    scale = foundation_weeks / nominal if nominal else 1.0

    cursor = today
    blocks = []
    for s in subs:
        wk = max(0.5, round(s["wks"] * scale * 2) / 2)  # round to nearest half-week
        start = cursor
        end = _add_weeks(start, wk)
        blocks.append({
            "subject": s["name"], "emoji": s["emoji"], "weak": s["weak"],
            "weeks": wk, "range": f"{_fmt(start)} – {_fmt(end)}",
            "sources": s["sources"], "tasks": [{"label": l, "panel": p} for l, p in s["tasks"]],
        })
        cursor = end

    foundation_end = cursor
    consolidation_end = min(exam, foundation_end + datetime.timedelta(days=consolidation_days))
    sprint_start = consolidation_end

    phases = [
        {"name": "Foundation & Subject Building", "emoji": "\U0001f3d7️",
         "range": f"{_fmt(today)} – {_fmt(foundation_end)}",
         "summary": "Cover every subject end-to-end: read the NCERTs, move to the standard source, "
                    "lock it in with Subjectwise MCQs (batches of 25), solve that subject's PYQs, and "
                    "tick each topic off in the Syllabus Tracker. Weak subjects are scheduled first.",
         "blocks": blocks,
         "goals": ["Finish NCERTs + one standard source per subject",
                   "Build the mistake notebook from day one",
                   "Keep current affairs going daily"]},
        {"name": "Consolidation & Revision", "emoji": "\U0001f501",
         "range": f"{_fmt(foundation_end)} – {_fmt(consolidation_end)}",
         "summary": "Stop adding new material. Revise everything with spaced repetition, clear your "
                    "Mistake Notebook, drill Weak Areas, and take subject-wise / sectional sets to find gaps.",
         "blocks": [],
         "goals": ["One full revision round of all subjects",
                   "Clear the Mistake Notebook", "Sectional tests + Weak-Area drills",
                   "Start 1 full mock/week to build stamina"],
         "tasks": [{"label": "Spaced-repetition revision", "panel": "revision"},
                   {"label": "Mistake Notebook", "panel": "mistakes"},
                   {"label": "Weak-Area drills", "panel": "weak"},
                   {"label": "Sectional / subject sets", "panel": "subjectwise"},
                   {"label": "Check Readiness score", "panel": "readiness"}]},
        {"name": "Prelims Sprint", "emoji": "\U0001f9ea",
         "range": f"{_fmt(sprint_start)} – {_fmt(exam)}",
         "summary": "Go full exam-mode: 2–3 full-length mocks a week in the Exam Simulator with deep "
                    "analysis, solve year-wise PYQ papers, rapid static revision, and daily CSAT. "
                    "The analysis matters more than the score.",
         "blocks": [],
         "goals": ["2–3 full mocks/week + analysis", "Year-wise PYQ papers",
                   "Daily CSAT practice", "Rapid revision via flashcards & mistakes",
                   "Current-affairs final revision"],
         "tasks": [{"label": "Full-length mock (Exam Simulator)", "panel": "simulator"},
                   {"label": "Year-wise PYQ papers", "panel": "pyq"},
                   {"label": "CSAT — daily set", "panel": "pyq"},
                   {"label": "War Room — adaptive drills", "panel": "warroom"},
                   {"label": "Rapid revision", "panel": "revision"},
                   {"label": "Track Readiness", "panel": "readiness"}]},
    ]

    milestones = [
        {"when": _fmt(foundation_end), "what": "Whole syllabus covered once — Syllabus Tracker should be near 100%."},
        {"when": _fmt(consolidation_end), "what": "First full revision done; Mistake Notebook cleared."},
        {"when": _fmt(exam - datetime.timedelta(days=14)), "what": "Last 2 weeks: only revision + mocks. No new topics."},
        {"when": _fmt(exam), "what": "\U0001f3af UPSC Prelims (estimated). You're exam-ready."},
    ]

    ongoing = [
        {"label": "\U0001f4f0 Current affairs — every day", "panel": "studyhub"},
        {"label": "\U0001f9ee CSAT — 2–3 times a week (daily in the sprint)", "panel": "pyq"},
        {"label": "\U0001f501 Revision — clear due cards daily", "panel": "revision"},
        {"label": "\U0001f5d2️ Syllabus Tracker — tick as you finish", "panel": "syllabus"},
    ]

    return {
        "exam_label": f"UPSC Prelims {ty}",
        "exam_date": _fmt(exam),
        "days_left": days_left,
        "weeks_left": weeks_left,
        "hours_label": HOURS_BUCKETS[hb]["label"],
        "hours_bucket": hb,
        "phases": phases,
        "daily_routine": [{"slot": a, "detail": b, "panel": p} for a, b, p in HOURS_BUCKETS[hb]["routine"]],
        "ongoing": ongoing,
        "milestones": milestones,
        "note": "This plan adapts to the time you have left and your study hours. Treat it as a flexible "
                "skeleton — if you fall behind on a subject, compress the next one rather than skipping mocks.",
    }
