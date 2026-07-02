"""
AIVORA Guided Program — turns the whole UPSC Prelims preparation into an ordered
queue of ready-to-do tasks. Each task carries an action AIVORA performs itself
(read an NCERT, auto-generate a 25-question verified test, launch a mock, etc.),
so the candidate just follows the queue and progress is tracked automatically.

Deterministic: the same profile always yields the same task IDs, so completion
persists across sessions.
"""
import datetime
import syllabus_data
import study_planner

# Order subjects move in (foundation). Weak subjects are pulled to the front.
SUBJECT_ORDER = [
    "Indian Polity", "Modern History", "Ancient History", "Medieval History",
    "Art & Culture", "Geography", "Indian Economy", "Environment & Ecology",
    "Science & Technology", "Indian Society", "International Relations", "World History",
]
TASKS_PER_DAY = {"0-2": 2, "2-4": 3, "4-6": 4, "6+": 5}


def _books_by_subject():
    m = {}
    for b in syllabus_data.NCERT_BOOKS:
        m.setdefault(b["subject"], []).append(b)
    return m


def _build_tasks(weak_subjects):
    weak = {w.strip().lower() for w in (weak_subjects or "").split(",") if w.strip()}
    books = _books_by_subject()
    order = [s for s in SUBJECT_ORDER if s in books]
    for s in books:
        if s not in order:
            order.append(s)
    # weak subjects first (stable)
    order.sort(key=lambda s: (not any(tok in s.lower() for tok in weak)))

    tasks = []

    def add(kind, title, subtitle, params, phase, is_weak=False):
        seedkey = params.get("book_key") or params.get("subject") or params.get("seq") or title
        tasks.append({
            "id": f"{kind}|{seedkey}",
            "kind": kind, "title": title, "subtitle": subtitle,
            "params": params, "phase": phase, "weak": is_weak,
        })

    # ── Foundation: subject by subject ──
    done = 0
    for s in order:
        is_weak = any(tok in s.lower() for tok in weak)
        for b in books[s]:
            add("read", f"Read: {b['book']}", s,
                {"book_key": b["key"], "read_url": b.get("read_url", "")}, "Foundation", is_weak)
            add("ncert_test", f"Test: {b['book']} (25 Qs)", s,
                {"book_key": b["key"], "count": 25}, "Foundation", is_weak)
        add("subject_test", f"{s} — mixed test (25 Qs)", s,
            {"subject": s, "count": 25}, "Foundation", is_weak)
        add("pyq", f"{s} — Previous-year questions", s,
            {"subject": s, "count": 25}, "Foundation", is_weak)
        done += 1
        if done % 2 == 0:
            add("revise", "Revision checkpoint", "Clear your due spaced-repetition cards",
                {"seq": f"frev{done}"}, "Foundation")

    # ── Consolidation ──
    add("revise", "Full revision round", "Spaced repetition across everything you've learned",
        {"seq": "crev"}, "Consolidation")
    add("weak", "Weak-area drill", "Target your lowest-accuracy topics",
        {"seq": "cweak"}, "Consolidation")
    add("pyq", "Mixed sectional test (25 Qs)", "All subjects — real PYQs",
        {"subject": "", "count": 25, "seq": "csect"}, "Consolidation")
    add("readiness", "Check your Readiness score", "See how exam-ready you are",
        {"seq": "cready"}, "Consolidation")

    # ── Prelims Sprint ──
    for i in range(1, 9):
        add("mock", f"Full-length Mock #{i}", "Exam Simulator — then study the analysis",
            {"seq": f"mock{i}"}, "Sprint")
        add("pyq_year", f"Year-wise PYQ paper #{i}", "Solve a full official paper",
            {"seq": f"pyqyr{i}"}, "Sprint")
        add("csat", f"CSAT practice set #{i}", "Keep CSAT sharp",
            {"area": "reasoning", "seq": f"csat{i}"}, "Sprint")
    add("revise", "Final revision sprint", "Flashcards + Mistake Notebook — the last fortnight",
        {"seq": "finrev"}, "Sprint")

    return tasks


def generate_program(target_year, hours_bucket, weak_subjects, today=None):
    today = today or datetime.date.today()
    plan = study_planner.generate_plan(target_year, hours_bucket, weak_subjects, today)
    tasks = _build_tasks(weak_subjects)
    tpd = TASKS_PER_DAY.get(hours_bucket if hours_bucket in TASKS_PER_DAY else "2-4", 3)

    days = []
    for i in range(0, len(tasks), tpd):
        chunk = tasks[i:i + tpd]
        days.append({"day": len(days) + 1, "phase": chunk[0]["phase"], "tasks": chunk})

    return {
        "days": days,
        "total_tasks": len(tasks),
        "tasks_per_day": tpd,
        "exam_label": plan["exam_label"],
        "exam_date": plan["exam_date"],
        "days_left": plan["days_left"],
        "hours_label": plan["hours_label"],
        "phase_counts": {ph: sum(1 for t in tasks if t["phase"] == ph)
                         for ph in ("Foundation", "Consolidation", "Sprint")},
    }


def all_task_ids(target_year, hours_bucket, weak_subjects):
    return {t["id"] for t in _build_tasks(weak_subjects)}
