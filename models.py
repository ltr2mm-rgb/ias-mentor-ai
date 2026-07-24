from sqlalchemy import Column, Integer, BigInteger, String, ForeignKey, Text, Boolean, DateTime, Date, LargeBinary, Float
from sqlalchemy.orm import relationship
from database import Base
import datetime


class ReaderNote(Base):
    """A candidate's highlight or note on an NCERT chapter (saved for revision).
    Tiny rows — text + normalized rectangle coords, never PDF bytes."""
    __tablename__ = "reader_notes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    book_key = Column(String, index=True)
    chapter_index = Column(Integer, default=0)
    kind = Column(String, default="note")     # 'note' | 'highlight'
    page = Column(Integer, nullable=True)      # 0-based page within the chapter PDF
    text = Column(Text, nullable=True)         # note body, or highlighted passage
    rects = Column(Text, nullable=True)        # JSON [{x,y,w,h}] normalized (highlights)
    color = Column(String, nullable=True)      # highlight colour
    label = Column(String, nullable=True)      # 'Important' | 'Revise' | 'Doubt' | 'Fact'
    revise_stage = Column(Integer, default=0)  # spaced-repetition stage (0..4)
    last_revised = Column(DateTime, nullable=True)
    next_review = Column(DateTime, nullable=True)   # when this item is next due for revision
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class NcertReading(Base):
    """Per-candidate reading progress for a whole NCERT book (drives the NCERT
    progress dashboard and 'continue reading'). One row per (user, book_key)."""
    __tablename__ = "ncert_reading"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    book_key = Column(String, index=True)
    status = Column(String, default="reading")   # 'reading' | 'completed'
    last_page = Column(Integer, default=0)        # 0-based furthest page reached
    pages_total = Column(Integer, default=0)      # total pages in the book
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                        onupdate=datetime.datetime.utcnow)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class NcertPdf(Base):
    """A single NCERT chapter PDF (extracted from the admin-uploaded book zip),
    stored in the DB so it persists across redeploys and is served in-app."""
    __tablename__ = "ncert_pdfs"
    id = Column(Integer, primary_key=True, index=True)
    book_key = Column(String, index=True)      # matches syllabus_data.NCERT_BOOKS key
    chapter_index = Column(Integer)            # 0-based order within the book
    filename = Column(String)                  # original PDF name
    src_url = Column(Text, nullable=True)      # source URL to stream from (keeps DB tiny)
    data = Column(LargeBinary, nullable=True)  # raw bytes ONLY for manual uploads w/o a URL
    size = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    phone = Column(String, nullable=True)
    hashed_password = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    mock_tests = relationship("MockTest", back_populates="user")
    test_attempts = relationship("TestAttempt", back_populates="user")


class MockTest(Base):
    __tablename__ = "mock_tests"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text)
    subject = Column(String)
    total_questions = Column(Integer)
    duration_minutes = Column(Integer)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="mock_tests")
    questions = relationship("Question", back_populates="mock_test")
    attempts = relationship("TestAttempt", back_populates="mock_test")


class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text)
    option_a = Column(Text)
    option_b = Column(Text)
    option_c = Column(Text)
    option_d = Column(Text)
    correct_answer = Column(String)
    explanation = Column(Text)
    subject = Column(String, nullable=True)  # per-question subject for analytics
    # Source/classification metadata for book/subject/topic-wise generation & filtering
    book = Column(String, nullable=True)
    chapter = Column(String, nullable=True)
    topic = Column(String, nullable=True)
    difficulty = Column(String, nullable=True)
    question_type = Column(String, nullable=True)
    # ── AML (Mastery Loop) reservoir metadata ──
    concept_key = Column(String, nullable=True, index=True)  # link to concept_inventory.key
    pattern = Column(String, nullable=True)                  # exam-skill axis: direct|statement_based|pairs|assertion_reason|elimination
    material_ref = Column(Text, nullable=True)               # JSON {book_key, chapter_index, page} parsed from citation
    mock_test_id = Column(Integer, ForeignKey("mock_tests.id"))
    mock_test = relationship("MockTest", back_populates="questions")


class TestAttempt(Base):
    __tablename__ = "test_attempts"
    id = Column(Integer, primary_key=True, index=True)
    score = Column(Integer)
    time_taken_seconds = Column(Integer)
    completed_at = Column(DateTime, default=datetime.datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="test_attempts")
    mock_test_id = Column(Integer, ForeignKey("mock_tests.id"))
    mock_test = relationship("MockTest", back_populates="attempts")
    answers = relationship("Answer", back_populates="test_attempt")


class Answer(Base):
    __tablename__ = "answers"
    id = Column(Integer, primary_key=True, index=True)
    selected_option = Column(String)
    is_correct = Column(Boolean)
    time_taken = Column(Integer, nullable=True)        # seconds spent on this question
    confidence = Column(String, nullable=True)         # sure | unsure | guess
    wrong_reason = Column(String, nullable=True)       # conceptual | factual | careless | misread | guess
    test_attempt_id = Column(Integer, ForeignKey("test_attempts.id"))
    test_attempt = relationship("TestAttempt", back_populates="answers")
    question_id = Column(Integer, ForeignKey("questions.id"))
    question = relationship("Question")


class AdminEmail(Base):
    __tablename__ = "admin_emails"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    added_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    user = relationship("User")
    # Personal details
    full_name = Column(String, nullable=True)
    parent_name = Column(String, nullable=True)        # parent / guardian name
    dob = Column(String, nullable=True)                # date of birth (ISO yyyy-mm-dd)
    age = Column(Integer, nullable=True)               # derived from dob
    gender = Column(String, nullable=True)
    marital_status = Column(String, nullable=True)
    mains_language = Column(String, nullable=True)     # Mains exam medium/language
    phone = Column(String, nullable=True)              # contact phone
    email = Column(String, nullable=True)              # contact email
    address = Column(Text, nullable=True)              # postal address
    # Background
    education = Column(String, nullable=True)
    graduation_stream = Column(String, nullable=True)       # discipline: Arts/Science/Commerce/Engg…
    schooling_medium = Column(String, nullable=True)        # English / regional medium of schooling
    degree_percentage = Column(String, nullable=True)       # graduation % / class band
    additional_qualification = Column(Text, nullable=True)  # PG / certifications / NET etc.
    optional_subject = Column(String, nullable=True)
    attempts = Column(String, nullable=True)          # e.g. "0", "1", "2", "3+"
    target_year = Column(String, nullable=True)        # e.g. "2026", "2027"
    working_professional = Column(Boolean, default=False)
    work_experience = Column(Text, nullable=True)      # free-text: role, org, years, nature of work
    # Study habits
    study_hours = Column(String, nullable=True)        # e.g. "0-2", "2-4", "4-6", "6+"
    learning_style = Column(String, nullable=True)     # visual / reading / practice / mixed
    home_state = Column(String, nullable=True)
    medium = Column(String, nullable=True)             # English / Hindi / Bilingual
    # Self-assessment
    strong_subjects = Column(Text, nullable=True)      # comma-separated
    weak_subjects = Column(Text, nullable=True)        # comma-separated
    # DAF-style fields
    category = Column(String, nullable=True)           # General / EWS / OBC / SC / ST / PwBD
    district = Column(String, nullable=True)           # district within home_state
    prep_location = Column(String, nullable=True)      # at home / another city
    prep_city = Column(String, nullable=True)          # which city, if relocated
    coaching_status = Column(String, nullable=True)    # AIVORA Package / Self Prep / Ongoing / Completed
    coaching_method = Column(String, nullable=True)    # Online / Offline / Self Preparation
    # ── Deep-personalisation intake (drives tailor-made daily tasks) ──
    prep_level = Column(String, nullable=True)          # how far along their prep is
    knowledge_level = Column(String, nullable=True)     # self-rated current knowledge
    comprehension_skill = Column(String, nullable=True) # comprehension/reasoning (CSAT) self-rating
    reading_speed = Column(String, nullable=True)       # slow-deep / average / fast skimmer
    study_time_windows = Column(String, nullable=True)  # when in the day they study
    study_place = Column(String, nullable=True)         # home / library / commuting / other
    prep_intensity = Column(String, nullable=True)      # full-time / part-time
    failure_stage = Column(String, nullable=True)       # none / prelims / mains / interview
    failure_reason = Column(String, nullable=True)      # where they fell short
    materials_owned = Column(Text, nullable=True)       # books/material they already have
    diagnostic_gs = Column(Integer, nullable=True)      # objective knowledge baseline (Phase 2 diagnostic)
    diagnostic_csat = Column(Integer, nullable=True)    # objective comprehension/reasoning baseline
    progress_history = Column(Text, nullable=True)      # JSON: daily snapshots for movement/deltas
    # ── AML (Mastery Loop) ──
    prep_mode = Column(String, nullable=True, default="hybrid")  # 'guided' | 'self' | 'hybrid'
    exam_date = Column(Date, nullable=True)                       # powers Time Optimization (Phase 2)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ReviewItem(Base):
    """Spaced-repetition schedule entry. One row per (user, question) the
    student has missed; resurfaced on a 1/7/30/90-day forgetting curve."""
    __tablename__ = "review_items"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), index=True)
    repetitions = Column(Integer, default=0)           # how many times reviewed correctly in a row
    interval_days = Column(Integer, default=1)         # current interval
    next_review = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    last_reviewed = Column(DateTime, nullable=True)
    mastered = Column(Boolean, default=False)
    times_seen = Column(Integer, default=0)
    times_correct = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class QuestionFlag(Base):
    """User-reported issue with a question — feeds the AI self-improvement loop."""
    __tablename__ = "question_flags"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), index=True)
    reason = Column(String, nullable=True)        # wrong_answer | unclear | wrong_subject | outdated | other
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ResolvedMistake(Base):
    """Marks a mistake the student has reviewed and understood (hidden from the active list)."""
    __tablename__ = "resolved_mistakes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Bookmark(Base):
    """A question the student starred to revisit later."""
    __tablename__ = "bookmarks"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class KnowledgeSource(Base):
    """An uploaded PDF (book or question bank). Raw file is NOT kept — only the
    derived chunks/MCQs are stored, so the knowledge base survives restarts."""
    __tablename__ = "knowledge_sources"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    subject = Column(String, index=True, nullable=True)
    kind = Column(String, nullable=True)              # book | mcq | both
    pages = Column(Integer, default=0)
    chunk_count = Column(Integer, default=0)
    mcq_count = Column(Integer, default=0)
    status = Column(String, default="processing")     # processing | done | error
    error = Column(Text, nullable=True)
    mock_test_id = Column(Integer, nullable=True)      # imported-MCQ test, if any
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    description = Column(Text, nullable=True)          # admin's free-text description
    file_type = Column(String, nullable=True)          # original file extension/type
    taxonomy = Column(Text, nullable=True)             # AI catalogue (JSON: subjects/topics/tags)
    # Resilience: keep the raw upload (base64) + processing mode until processing
    # SUCCEEDS, so an upload whose background job was killed (free-tier spin-down /
    # restart) can be auto-resumed on the next boot. Cleared once status = done.
    raw_b64 = Column(Text, nullable=True)
    proc_mode = Column(String, nullable=True)          # book | mcq | both
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class SyllabusProgress(Base):
    """One row per (user, syllabus topic) the student has marked complete."""
    __tablename__ = "syllabus_progress"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    topic_id = Column(String, index=True)              # e.g. "0.0.3.2"
    completed_at = Column(DateTime, default=datetime.datetime.utcnow)


class GuidedProgress(Base):
    """One row per (user, guided-program task) the student has completed."""
    __tablename__ = "guided_progress"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    task_id = Column(String, index=True)               # e.g. "ncert_test|eco9_economics"
    completed_at = Column(DateTime, default=datetime.datetime.utcnow)


class DailyMissionDone(Base):
    """One row per (user, date, daily-mission task) the student completed that day."""
    __tablename__ = "daily_mission_done"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    day = Column(String, index=True)                   # ISO date "2026-06-28"
    task_key = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ChatMessage(Base):
    """One row per mentor-chat message (persistent companion memory)."""
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    role = Column(String)                              # user | assistant
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class MainsAnswer(Base):
    """A candidate's written Mains answer + its AI evaluation (feeds writing quality)."""
    __tablename__ = "mains_answers"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    question = Column(Text)
    answer = Column(Text)
    paper = Column(String, nullable=True)
    overall_pct = Column(Integer, default=0)
    overall_marks = Column(String, nullable=True)
    marks = Column(Integer, default=10)
    eval_json = Column(Text, nullable=True)            # full evaluation as JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class KnowledgeChunk(Base):
    """A passage of extracted book text — used to ground AI generation and to power
    the searchable library."""
    __tablename__ = "knowledge_chunks"
    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("knowledge_sources.id"), index=True)
    subject = Column(String, index=True, nullable=True)
    page = Column(Integer, nullable=True)
    text = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ConceptJob(Base):
    """A background concept-extraction job. The uploaded file is held ONLY as a
    temporary base64 blob (raw_b64) while it is being processed — it survives a
    restart so the job can auto-resume, and is CLEARED the instant extraction
    finishes or fails, so no copyrighted source is ever retained. Only the derived
    concept metadata (non-copyrightable public facts) persists in `concepts`."""
    __tablename__ = "concept_jobs"
    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String, index=True)              # groups files uploaded together
    filename = Column(String)
    status = Column(String, default="queued", index=True)  # queued|processing|done|error
    raw_b64 = Column(Text, nullable=True)              # TEMPORARY upload bytes; cleared when done
    concepts = Column(Text, nullable=True)             # JSON: extracted concept metadata (persists)
    item_count = Column(Integer, default=0)
    pages = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    stage = Column(String, nullable=True)              # queued|reading|extracting|done|error
    progress = Column(Integer, default=0)              # 0-100 (for the progress bar)
    started_at = Column(DateTime, nullable=True)       # when processing began (for the ETA)


class ConceptInventory(Base):
    """The PERMANENT concept library. Every finished extraction job merges its
    concepts here (deduped by concept+subject), so the library survives job
    clearing, restarts and redeploys. Rows hold only derived concept metadata —
    concept names, classifications and public facts — never source text, in
    keeping with the zero-footprint copyright policy."""
    __tablename__ = "concept_inventory"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)      # normalised concept|subject dedup key
    concept = Column(String, index=True)
    subject = Column(String, index=True, nullable=True)
    subtopic = Column(String, nullable=True)
    pattern = Column(String, nullable=True)            # how it tends to be asked
    difficulty = Column(String, nullable=True)
    importance = Column(String, nullable=True)
    key_facts = Column(Text, nullable=True)            # JSON list of public facts
    frequency = Column(Integer, default=1)             # merged appearance count
    sources = Column(Integer, default=1)               # how many files contributed
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class InterviewPrep(Base):
    """Interview module phase 1: the aspirant's DAF-style details and the AI-
    generated personalised interview question bank built from them. One row per
    user, regenerated in place."""
    __tablename__ = "interview_preps"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    daf = Column(Text, nullable=True)         # JSON: the DAF answers used for generation
    questions = Column(Text, nullable=True)   # JSON: {"themes":[{"title","why","questions":[{"q","hint"}]}]}
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class MockScore(Base):
    """A mock / test-series score the aspirant LOGS manually (an offline test, or
    one taken on any other platform). This powers the Test Tracker analytics and
    is deliberately separate from MockTest, which is an AI-generated in-app paper."""
    __tablename__ = "mock_scores"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    stage = Column(String, default="prelims")      # prelims | csat | mains
    test_name = Column(String, nullable=True)       # e.g. "Vision PT 12"
    series = Column(String, nullable=True)          # e.g. "Vision IAS", "Vajiram"
    taken_on = Column(String, index=True)           # ISO date "2026-07-05"
    max_marks = Column(Float, default=200)          # paper's max (200 GS / 200 CSAT / 250 Mains)
    score = Column(Float, default=0)                # net score after negative marking
    total_q = Column(Integer, nullable=True)
    correct = Column(Integer, nullable=True)
    wrong = Column(Integer, nullable=True)
    unattempted = Column(Integer, nullable=True)
    accuracy = Column(Float, nullable=True)         # 0-100 (%), auto-computed if not supplied
    weak_areas = Column(Text, nullable=True)        # comma-separated subjects
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ExamGoal(Base):
    """Per-user exam targets + dates that drive the Test Tracker goal bars and the
    days-to-exam countdown. One row per user, updated in place."""
    __tablename__ = "exam_goals"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    target_score = Column(Integer, nullable=True)       # target net Prelims score
    target_accuracy = Column(Integer, nullable=True)    # target accuracy %
    prelims_date = Column(String, nullable=True)        # ISO date
    mains_date = Column(String, nullable=True)          # ISO date
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class CsatPyqPaper(Base):
    """A full CSAT (Paper II) previous-year paper AUTHORED BY THE SITE ADMIN via the
    in-app CSAT Paper Builder — passages, questions, options and answers stored as
    JSON. This is the owner's own content, served year-wise in the CSAT PYQs tab
    alongside the built-in aptitude bank. One row per year, updated in place."""
    __tablename__ = "csat_pyq_papers"
    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, unique=True, index=True)
    title = Column(String, nullable=True)
    # JSON: {"passages":[{"id","text"}], "questions":[{"q_no","passage_id","text",
    #        "option_a","option_b","option_c","option_d","correct_answer","type"}]}
    data = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
#  AIVORA Mastery Loop (AML) — Phase 0 telemetry & knowledge-state tables
#  These only STORE data; no adaptive/teaching logic lives here.
# ══════════════════════════════════════════════════════════════════════════════

class ConceptAttempt(Base):
    """Learning-event telemetry — one row per question a student answers in the
    adaptive flow. The raw log the whole engine is built on; captured from day one
    because response time + confidence are unrecoverable if not stored now."""
    __tablename__ = "concept_attempts"
    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    question_id = Column(Integer, index=True)
    concept_key = Column(String, index=True)
    subject = Column(String, nullable=True)
    subtopic = Column(String, nullable=True)
    pattern = Column(String, nullable=True)          # exam-skill axis
    correct = Column(Boolean)
    selected = Column(String, nullable=True)         # A|B|C|D
    difficulty = Column(String, nullable=True)       # at time of serve
    response_ms = Column(Integer, nullable=True)     # behavioural signal: speed
    confidence = Column(String, nullable=True)       # 'sure'|'somewhat'|'guess'
    hint_used = Column(Boolean, default=False)
    attempt_number = Column(Integer, default=1)      # nth time on THIS question
    exposure_count = Column(Integer, default=1)      # times ever seen this question
    attempt_context = Column(String, nullable=True)  # diagnostic|practice|revision|mock|assessment
    revision_stage = Column(Integer, nullable=True)
    failure_reason = Column(String, nullable=True)   # nullable now; classified later
    session_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class ConceptMastery(Base):
    """Per-(student, concept) knowledge state. Always derived from ConceptAttempt.
    Composite PK (user_id, concept_key)."""
    __tablename__ = "concept_mastery"
    user_id = Column(Integer, primary_key=True, index=True)
    concept_key = Column(String, primary_key=True, index=True)
    subject = Column(String, nullable=True)
    subtopic = Column(String, nullable=True)
    mastery = Column(Float, default=0.5)             # uncertain, not zero, on cold start
    confidence_n = Column(Integer, default=0)        # attempts backing the estimate
    attempts = Column(Integer, default=0)
    correct = Column(Integer, default=0)
    streak = Column(Integer, default=0)
    state = Column(String, default="unknown")        # UI label only
    confidence_trend = Column(String, nullable=True) # rising|falling|flat
    stability = Column(Float, nullable=True)         # retention estimate
    last_seen = Column(DateTime, nullable=True)
    revise_stage = Column(Integer, default=0)        # SM-2 spaced-rep stage
    next_review = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class SkillMastery(Base):
    """Per-(student, question-pattern) exam-skill state — 'statement analysis',
    'elimination', etc. Same mastery math as concepts, grouped by pattern.
    Composite PK (user_id, pattern)."""
    __tablename__ = "skill_mastery"
    user_id = Column(Integer, primary_key=True, index=True)
    pattern = Column(String, primary_key=True)
    mastery = Column(Float, default=0.5)
    attempts = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
class MentorTopic(Base):
    __tablename__ = "mentor_topics"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    topic = Column(String, index=True)
    level = Column(String, default="introduced")
    times_seen = Column(Integer, default=1)
    first_seen = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow)
    revised = Column(Boolean, default=False)
    revise_due = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class TeachingEvent(Base):
    """Teaching Engine memory (see TEACHING_ENGINE.md §12) — one row per taught-then-
    checked concept: which barrier, which strategy, and whether the immediate check
    passed. This is the seed of the Evidence Engine: over time it reveals which
    strategy works for which learner/barrier, and it lets the engine prefer what has
    worked for THIS learner and avoid what hasn't."""
    __tablename__ = "teaching_events"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    target = Column(String, index=True)          # concept/subject taught
    barrier = Column(String, nullable=True)       # diagnosed barrier key
    layer = Column(String, nullable=True)         # knowledge | cognitive | behaviour
    strategy = Column(String, nullable=True)      # teaching strategy used
    attempt = Column(Integer, default=0)          # 0 = first lesson, 1+ = re-teach
    correct = Column(Integer, default=0)
    total = Column(Integer, default=0)
    passed = Column(Boolean, default=False)
    stage = Column(String, nullable=True)         # prelims | mains | interview
    seconds = Column(Integer, default=0)          # time-to-mastery: lesson→check duration
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

# ══════════════════════════════════════════════════════════════════════════════
#  Guided Success Programme (GSP) — Phase-1 spine · per-user journey state
#  (Module definitions live in gsp.py as data; only user state is persisted here.)
# ══════════════════════════════════════════════════════════════════════════════

class GspEnrollment(Base):
    """One row per enrolled student — the Guidance Engine's macro state."""
    __tablename__ = "gsp_enrollment"
    user_id = Column(Integer, primary_key=True, index=True)
    track = Column(String, default="prelims")          # prelims | mains | interview
    current_stage = Column(Integer, default=1)
    current_module = Column(String, nullable=True)     # e.g. "M-FR-0"
    placed_level = Column(String, nullable=True)       # Foundation | Standard Books | ...
    intensity = Column(String, default="standard")     # standard | accelerated | support
    readiness_pct = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class GspModuleProgress(Base):
    """Per-(student, module) journey progress. state='mastered' is the gate pass."""
    __tablename__ = "gsp_module_progress"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    module_id = Column(String, index=True)             # e.g. "M-FR-3"
    state = Column(String, default="available")        # locked | available | in_progress | mastered
    mastery = Column(Float, default=0.0)
    checkpoint_score = Column(Integer, nullable=True)
    mastered_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
