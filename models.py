from sqlalchemy import Column, Integer, BigInteger, String, ForeignKey, Text, Boolean, DateTime, Date, LargeBinary, Float, UniqueConstraint, Index
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


# ══════════════════════════════════════════════════════════════════════════════
#  Pedagogy Kernel (architecture §1.2) — verified, versioned TEACHING knowledge.
#  Recipes (subject-agnostic lesson structures) are code-defined in
#  pedagogy_kernel.RECIPES for v1; this table stores the concept-specific ASSETS.
#  Assets are generated once (learner-agnostic), gated by MANUAL verification
#  (v1), then reused for every learner — reuse-before-generate.
# ══════════════════════════════════════════════════════════════════════════════

class TeachingAsset(Base):
    """One piece of teaching knowledge for a concept + task (an analogy, comparison,
    worked example, mnemonic, PYQ insight, …). status gates reuse: only 'verified'
    assets are ever served to learners; 'draft' awaits the manual verification gate."""
    __tablename__ = "teaching_assets"
    id = Column(Integer, primary_key=True, index=True)
    concept = Column(String, index=True)          # concept key, e.g. "fundamental-rights"
    subject = Column(String, nullable=True)       # e.g. "Polity"
    task_type = Column(String, index=True)        # analogy | comparison | worked-example | ...
    kind = Column(String, default="asset")        # asset | misconception | remediation | scaffold
    recipe_key = Column(String, nullable=True)    # recipe this was authored for (optional)
    content = Column(Text)                          # the teaching text/content (markdown)
    provider = Column(String, nullable=True)      # engine that generated it (audit)
    status = Column(String, default="draft", index=True)   # draft | verified | retired
    version = Column(Integer, default=1)
    verified_by = Column(String, nullable=True)   # admin email who approved (manual gate)
    verify_detail = Column(Text, nullable=True)   # automated pre-check summary / notes
    archetype_hint = Column(String, nullable=True)   # future: per-archetype variant
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class LessonOutcome(Base):
    """Evidence loop seed (architecture §2.2 / asset_outcomes). One row per lesson a
    learner experiences via the Teaching Engine — the raw signal that will later tune
    recipe / strategy policies. V1 just COLLECTS; nothing learns from it yet."""
    __tablename__ = "lesson_outcomes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    concept = Column(String, index=True)
    subject = Column(String, nullable=True)
    recipe = Column(String, index=True)
    archetype = Column(String, index=True)
    barrier = Column(String, nullable=True)
    completed = Column(Boolean, default=False)          # finished reading the lesson
    mini_check_passed = Column(Boolean, nullable=True)  # None = not attempted
    reread = Column(Boolean, default=False)
    # Pilot instrumentation: a pre-lesson confidence baseline (contextualises every
    # score) and a post-lesson rating + free-text feedback (satisfaction + qualitative).
    confidence_before = Column(String, nullable=True)   # never | low | somewhat | high
    confidence_after = Column(String, nullable=True)    # same scale, post-lesson (→ gain)
    rating = Column(Integer, nullable=True)             # 1-5 "would use again"
    helpful = Column(Text, nullable=True)               # most helpful part (optional)
    confusing = Column(Text, nullable=True)             # confusing/inaccurate part (optional)
    # Version attribution (governance): tie each outcome to the exact content/recipe
    # in effect so a change in learning results is attributable to a specific version.
    recipe_version = Column(String, nullable=True)
    kernel_version = Column(String, nullable=True)
    minicheck_version = Column(String, nullable=True)
    schema_version = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ══════════════════════════════════════════════════════════════════════════════
#  Intelligence Layer (INTELLIGENCE_LAYER_PLAN.md v1.3 §4) — the materialized
#  Learner State + the prediction audit trail. These STORE state only; the math
#  lives in learner_kernel.py / prediction_engine.py (State/Prediction stay
#  separate — AI_MARGA_OS.md §4). Additive: no existing table is touched.
# ══════════════════════════════════════════════════════════════════════════════

class LearningProfile(Base):
    """The single source of truth for a learner's state — one row per learner.
    Split into Current State (fast, recomputed every event) and Learning DNA
    (slow-moving traits). NO readiness column — readiness is a Prediction, never
    stored state. Written by learner_kernel.recompute_profile()."""
    __tablename__ = "learning_profile"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True, index=True)
    goal_ref = Column(String, nullable=True)          # (exam, scope, target_date)
    state_json = Column(Text, nullable=True)          # Current State — {dim: {value, confidence}}
    dna_json = Column(Text, nullable=True)            # Learning DNA (§5.7) — slow traits
    stage = Column(String, nullable=True)             # Foundation | Intermediate | Advanced
    growth_lever_json = Column(Text, nullable=True)   # {lever_key, rationale, drag}
    profile_version = Column(String, nullable=True)   # which dimension-formula version produced this
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                        onupdate=datetime.datetime.utcnow)


class PredictionHistory(Base):
    """Append-only audit of every Prediction emitted — NOT learner-facing. Lets
    pilots answer 'why did readiness move on Tuesday?' and attribute a change to a
    specific engine version. Written by prediction_engine.predict()."""
    __tablename__ = "prediction_history"
    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    metric = Column(String, index=True)               # readiness | prelims_score | forgetting_date | ...
    value = Column(String, nullable=True)             # scalar or JSON-encoded
    confidence = Column(Float, nullable=True)
    stability = Column(Float, nullable=True)
    horizon_days = Column(Integer, nullable=True)
    engine_version = Column(String, nullable=True)    # e.g. "readiness-v1.3"
    data_basis_json = Column(Text, nullable=True)     # {mcqs, revisions, sessions, mocks}
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class DecisionRecord(Base):
    """One row per recommendation the Decision Engine made. Paired later with a
    DecisionOutcome so every recommendation becomes a supervised-learning example
    (the evidence architecture). Written by decision_outcomes.open_decision()."""
    __tablename__ = "decision_records"
    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    action = Column(String, nullable=True)             # revise|practise|teach|increase_difficulty|...
    target = Column(String, nullable=True)             # display name of the target concept
    target_key = Column(String, nullable=True, index=True)  # concept_key, for 'executed?' matching
    reason = Column(Text, nullable=True)               # the behavioral explanation shown to the learner
    expected_gain = Column(Float, nullable=True)       # predicted readiness delta at decision time
    engine_version = Column(String, nullable=True)     # e.g. "decision-v1.3"
    # ── reproducibility stamps: reconstruct exactly WHY a recommendation was made ──
    prediction_version = Column(String, nullable=True) # e.g. "readiness-v1.3"
    profile_version = Column(String, nullable=True)    # e.g. "profile-v1.3"
    explanation_version = Column(String, nullable=True)# e.g. "explain-v1.3"
    planner_version = Column(String, nullable=True)    # e.g. "mission-v1.3"
    experiment_id = Column(BigInteger, nullable=True, index=True)  # → experiments.id (A/B)
    baseline_readiness = Column(Float, nullable=True)  # readiness at decision time (outcome baseline)
    horizon_hours = Column(Integer, default=24)        # when the outcome should be measured
    settled = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class DecisionOutcome(Base):
    """The measured result of a DecisionRecord, written once it matures. Together
    the pair is one training example: (state+decision) → actual_gain. Written by
    decision_outcomes.settle_decisions()."""
    __tablename__ = "decision_outcomes"
    id = Column(BigInteger, primary_key=True, index=True)
    decision_id = Column(BigInteger, index=True)       # → decision_records.id
    user_id = Column(Integer, index=True)
    executed = Column(Boolean, nullable=True)          # did the learner act on the target?
    completion_rate = Column(Float, nullable=True)     # fraction of mission steps done
    readiness_change = Column(Float, nullable=True)    # readiness(after) − baseline
    retention_change = Column(Float, nullable=True)
    learner_rating = Column(Integer, nullable=True)    # 1-5, optional
    actual_gain = Column(Float, nullable=True)         # the supervised label
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class EngineHealthLog(Base):
    """Operational telemetry — one row per pipeline run. NOT learner-facing: it
    measures the ENGINE (latency per stage, success/failure) so production health
    is observable. Best-effort; a failure to log never affects the learner path.
    Written by engine_health.record(); aggregated by engine_health.metrics()."""
    __tablename__ = "engine_health_log"
    id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=True)
    source_event = Column(String, nullable=True)       # AttemptRecorded | RevisionCompleted | ...
    ok = Column(Boolean, default=True, index=True)     # did the run complete cleanly?
    failed_stage = Column(String, nullable=True)       # first stage that raised, if any
    kernel_ms = Column(Float, nullable=True)
    prediction_ms = Column(Float, nullable=True)
    delta_ms = Column(Float, nullable=True)
    explanation_ms = Column(Float, nullable=True)
    decision_ms = Column(Float, nullable=True)
    mission_ms = Column(Float, nullable=True)
    total_ms = Column(Float, nullable=True)
    settle_ok = Column(Boolean, nullable=True)         # did outcome-settlement succeed this run?
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class Experiment(Base):
    """A first-class recommendation experiment (A/B) — the operational metadata the
    engine version string can't hold: when it ran, who was eligible, why it stopped,
    whether it was promoted or rolled back. The intelligence engine does NOT read
    this; the learner never sees it. It exists for operations, dashboards, and future
    research. Managed by experiment_registry.py; referenced by DecisionRecord.experiment_id."""
    __tablename__ = "experiments"
    id = Column(BigInteger, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    description = Column(Text, nullable=True)
    status = Column(String, default="draft", index=True)  # draft|running|stopped|promoted|rolled_back
    control_policy = Column(String, nullable=True)         # e.g. "decision-baseline"
    treatment_policy = Column(String, nullable=True)       # e.g. "decision-v1.4"
    eligibility = Column(String, nullable=True, default="all")  # v1: 'all' (extend later)
    split = Column(Float, default=0.5)                     # fraction assigned to treatment
    owner = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    # ── build binding: which exact deployed build ran this experiment ──
    # captured at creation so the experiment stays tied to the build even after
    # Platform 1.1+ exists, instead of inferring it from git history later.
    platform_version = Column(String, nullable=True)       # e.g. "1.0"
    git_sha = Column(String, nullable=True)                # deploy-time build SHA
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# ── ADR-003: Learning Event Bus ─────────────────────────────────────────────
class LearnerEvent(Base):
    """Append-only learner evidence log — the single source of truth (ADR-003).
    Never updated, never deleted. The Learner Projection (materialised state) is
    derived from this stream and is fully rebuildable by replaying it in `seq`
    order. `event_id` gives idempotency; `seq` is a server-assigned monotonic
    sequence PER user (ordering). concept_ids/topic_ids/meta are JSON text so the
    schema is portable across SQLite (tests) and Postgres (prod)."""
    __tablename__ = "learner_events"
    id = Column(Integer, primary_key=True, index=True)          # storage PK (autoincrement, both DBs)
    event_id = Column(String, unique=True, index=True, nullable=False)  # client UUID → idempotency
    user_id = Column(Integer, index=True, nullable=False)
    seq = Column(BigInteger, nullable=False)                    # monotonic per user (ordering)
    ts_client = Column(DateTime, nullable=True)                 # client-reported event time
    ingested_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    module = Column(String, index=True, nullable=True)          # mcq|self_prep|current_affairs|...
    activity_type = Column(String, index=True, nullable=True)   # MCQ_ATTEMPTED|... (ADR-001 catalogue)
    concept_ids = Column(Text, nullable=True)                   # JSON list[str] (ADR-004)
    topic_ids = Column(Text, nullable=True)                     # JSON list[str]
    duration = Column(Integer, nullable=True)                   # seconds
    score = Column(Float, nullable=True)
    confidence = Column(String, nullable=True)                  # sure|somewhat|unsure|null
    schema_version = Column(Integer, default=1, nullable=False)
    meta = Column(Text, nullable=True)                          # JSON object (envelope `metadata`)
    __table_args__ = (
        UniqueConstraint("user_id", "seq", name="uq_learner_events_user_seq"),
        Index("ix_learner_events_user_seq", "user_id", "seq"),
    )


# ── ADR-001/003: Learner Projection (M2) ────────────────────────────────────
class LearnerProjection(Base):
    """Materialised Learner Projection — a DERIVED, rebuildable read-model of the
    LearnerEvent stream (ADR-001). NEVER authoritative: if this row is deleted,
    replaying the events reconstructs an identical `payload`. The first four
    columns are operational metadata; the domain state lives in `payload` (JSON)
    until there is a demonstrated need to normalise parts of it.

    `projection_version` is independent of the event `schema_version`: the former
    is 'how do we interpret events?' (the reducer algorithm), the latter is 'how
    is the event encoded?'. Bumping projection_version triggers a full rebuild
    without touching a single historical event."""
    __tablename__ = "learner_projections"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False)
    last_seq = Column(BigInteger, default=0, nullable=False)     # highest event seq folded in
    projection_version = Column(String, nullable=True)           # reducer algorithm version
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                        onupdate=datetime.datetime.utcnow)
    payload = Column(Text, nullable=True)                        # JSON: deterministic stored state


# ── ADR-005/007: Mission Outcome Projection (M5 Phase A) ────────────────────
class MissionOutcomeProjection(Base):
    """Materialised Mission Outcome projection — a DERIVED, rebuildable read-model
    of the MISSION_* + MCQ_ATTEMPTED streams (ADR-005/007). Like LearnerProjection
    it is NEVER authoritative: delete this row and a full replay reconstructs an
    identical `payload` (EQ-01). One `MissionOutcome` is derived per mission; the
    evaluator aggregates them by `policy_version` (EQ-02). Only deterministic
    fields are stored here — retention/time-relative deltas are read-time views
    (M2 discipline), never part of replay equality.

    `outcome_version` is the reducer-algorithm version (independent of the event
    `schema_version`); bumping it forces a rebuild without touching any event."""
    __tablename__ = "mission_outcome_projections"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False)
    last_seq = Column(BigInteger, default=0, nullable=False)     # highest event seq folded in
    outcome_version = Column(String, nullable=True)              # reducer algorithm version
    updated_at = Column(DateTime, default=datetime.datetime.utcnow,
                        onupdate=datetime.datetime.utcnow)
    payload = Column(Text, nullable=True)                        # JSON: deterministic outcomes state
