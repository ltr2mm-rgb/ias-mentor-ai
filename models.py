from sqlalchemy import Column, Integer, String, ForeignKey, Text, Boolean, DateTime, LargeBinary
from sqlalchemy.orm import relationship
from database import Base
import datetime


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
