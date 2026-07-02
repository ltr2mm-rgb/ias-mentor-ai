import os
import re
import io
import gc
import zipfile
import tempfile
import json
import random
import datetime
from urllib.request import urlopen, Request as _UrlRequest

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, Response, HTMLResponse
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text as sa_text

from auth import hash_password, verify_password, create_access_token, verify_token
from config import ADMIN_EMAILS
from database import SessionLocal, engine, get_db
from models import (
    Base, User as DBUser, MockTest as DBMockTest,
    Question as DBQuestion, TestAttempt as DBTestAttempt, Answer as DBAnswer,
    AdminEmail as DBAdminEmail, StudentProfile as DBStudentProfile,
    ReviewItem as DBReviewItem, QuestionFlag as DBQuestionFlag,
    ResolvedMistake as DBResolvedMistake, Bookmark as DBBookmark,
    KnowledgeSource as DBKnowledgeSource, KnowledgeChunk as DBKnowledgeChunk,
    SyllabusProgress as DBSyllabusProgress, GuidedProgress as DBGuidedProgress,
    DailyMissionDone as DBDailyMissionDone, MainsAnswer as DBMainsAnswer,
    ChatMessage as DBChatMessage,
    NcertPdf as DBNcertPdf,
)
from gemini_service import (
    generate_questions, generate_and_parse_questions,
    explain_concept, analyze_performance, chat_with_mentor,
    generate_mentor_report, generate_ncert_mcqs, generate_verified_questions,
    diagnose_mistake,
    generate_study_notes, generate_flashcards, generate_mnemonics,
    generate_mindmap, current_affairs_analysis, extract_mcqs_from_text,
    evaluate_mains_answer, weekly_mentor_narrative,
)
import syllabus_data
import geo_data
import syllabus_tracker_data
import study_planner
import program as guided_program
import prepos
import diagnostic

Base.metadata.create_all(bind=engine)

# Set True once pgvector is confirmed available on the (Postgres) database. While
# False, all semantic search transparently falls back to keyword (ILIKE) search.
VECTOR_OK = False

def _ensure_schema():
    """Lightweight migration: add columns newer code expects to pre-existing DBs.
    Works on both SQLite (local) and PostgreSQL (production)."""
    try:
        dialect = engine.dialect.name
        with engine.connect() as conn:
            # New per-question metadata columns for book/subject/topic-wise generation.
            new_q_cols = ["book", "chapter", "topic", "difficulty", "question_type"]
            if dialect == "sqlite":
                qcols = [r[1] for r in conn.execute(sa_text("PRAGMA table_info(questions)"))]
                if "subject" not in qcols:
                    conn.execute(sa_text("ALTER TABLE questions ADD COLUMN subject VARCHAR")); conn.commit()
                for col in new_q_cols:
                    if col not in qcols:
                        conn.execute(sa_text(f"ALTER TABLE questions ADD COLUMN {col} VARCHAR")); conn.commit()
                ucols = [r[1] for r in conn.execute(sa_text("PRAGMA table_info(users)"))]
                if "created_at" not in ucols:
                    conn.execute(sa_text("ALTER TABLE users ADD COLUMN created_at DATETIME")); conn.commit()
                if "phone" not in ucols:
                    conn.execute(sa_text("ALTER TABLE users ADD COLUMN phone VARCHAR")); conn.commit()
                # New per-answer learning-loop columns.
                acols = [r[1] for r in conn.execute(sa_text("PRAGMA table_info(answers)"))]
                if "time_taken" not in acols:
                    conn.execute(sa_text("ALTER TABLE answers ADD COLUMN time_taken INTEGER")); conn.commit()
                for col in ("confidence", "wrong_reason"):
                    if col not in acols:
                        conn.execute(sa_text(f"ALTER TABLE answers ADD COLUMN {col} VARCHAR")); conn.commit()
                # New DAF-style student_profiles columns.
                try:
                    pcols = [r[1] for r in conn.execute(sa_text("PRAGMA table_info(student_profiles)"))]
                    for col in ("category", "district", "prep_location", "prep_city",
                                "coaching_status", "coaching_method",
                                "prep_level", "knowledge_level", "comprehension_skill",
                                "reading_speed", "study_time_windows", "study_place",
                                "prep_intensity", "failure_stage", "failure_reason", "materials_owned",
                                "full_name", "parent_name", "dob", "gender",
                                "marital_status", "mains_language",
                                "phone", "email", "address",
                                "graduation_stream", "schooling_medium",
                                "degree_percentage", "additional_qualification",
                                "work_experience"):
                        if col not in pcols:
                            conn.execute(sa_text(f"ALTER TABLE student_profiles ADD COLUMN {col} VARCHAR")); conn.commit()
                    for col in ("diagnostic_gs", "diagnostic_csat", "age"):
                        if col not in pcols:
                            conn.execute(sa_text(f"ALTER TABLE student_profiles ADD COLUMN {col} INTEGER")); conn.commit()
                except Exception:
                    pass
                try:
                    kcols = [r[1] for r in conn.execute(sa_text("PRAGMA table_info(knowledge_sources)"))]
                    for col in ("description", "file_type", "taxonomy", "raw_b64", "proc_mode"):
                        if col not in kcols:
                            conn.execute(sa_text(f"ALTER TABLE knowledge_sources ADD COLUMN {col} TEXT")); conn.commit()
                except Exception:
                    pass
                try:
                    ncols = [r[1] for r in conn.execute(sa_text("PRAGMA table_info(ncert_pdfs)"))]
                    if "src_url" not in ncols:
                        conn.execute(sa_text("ALTER TABLE ncert_pdfs ADD COLUMN src_url TEXT")); conn.commit()
                except Exception:
                    pass
            else:
                conn.execute(sa_text("ALTER TABLE questions ADD COLUMN IF NOT EXISTS subject VARCHAR")); conn.commit()
                for col in new_q_cols:
                    conn.execute(sa_text(f"ALTER TABLE questions ADD COLUMN IF NOT EXISTS {col} VARCHAR")); conn.commit()
                conn.execute(sa_text("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP")); conn.commit()
                conn.execute(sa_text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR")); conn.commit()
                # New per-answer learning-loop columns.
                conn.execute(sa_text("ALTER TABLE answers ADD COLUMN IF NOT EXISTS time_taken INTEGER")); conn.commit()
                conn.execute(sa_text("ALTER TABLE answers ADD COLUMN IF NOT EXISTS confidence VARCHAR")); conn.commit()
                conn.execute(sa_text("ALTER TABLE answers ADD COLUMN IF NOT EXISTS wrong_reason VARCHAR")); conn.commit()
                # New DAF-style student_profiles columns.
                for col in ("category", "district", "prep_location", "prep_city",
                            "coaching_status", "coaching_method",
                            "prep_level", "knowledge_level", "comprehension_skill",
                            "reading_speed", "study_time_windows", "study_place",
                            "prep_intensity", "failure_stage", "failure_reason", "materials_owned",
                            "full_name", "parent_name", "dob", "gender",
                            "marital_status", "mains_language",
                            "phone", "email", "address",
                            "graduation_stream", "schooling_medium",
                            "degree_percentage", "additional_qualification",
                            "work_experience"):
                    conn.execute(sa_text(f"ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS {col} VARCHAR")); conn.commit()
                for col in ("diagnostic_gs", "diagnostic_csat", "age"):
                    conn.execute(sa_text(f"ALTER TABLE student_profiles ADD COLUMN IF NOT EXISTS {col} INTEGER")); conn.commit()
                # New knowledge_sources columns (description / file type / taxonomy / resume).
                for col in ("description", "file_type", "taxonomy", "raw_b64", "proc_mode"):
                    conn.execute(sa_text(f"ALTER TABLE knowledge_sources ADD COLUMN IF NOT EXISTS {col} TEXT")); conn.commit()
                # NCERT PDFs: source URL so chapters stream from source (DB stays tiny).
                conn.execute(sa_text("ALTER TABLE ncert_pdfs ADD COLUMN IF NOT EXISTS src_url TEXT")); conn.commit()
                # pgvector: semantic-search embeddings for the knowledge base (RAG).
                try:
                    conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS vector")); conn.commit()
                    conn.execute(sa_text(
                        "ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding vector(768)")); conn.commit()
                    try:
                        conn.execute(sa_text(
                            "CREATE INDEX IF NOT EXISTS idx_kchunks_embedding ON knowledge_chunks "
                            "USING hnsw (embedding vector_cosine_ops)")); conn.commit()
                    except Exception:
                        pass    # index is an optimisation; search still works without it
                    globals()["VECTOR_OK"] = True
                except Exception:
                    pass        # extension unavailable / no permission → stay on keyword search
    except Exception:
        pass

_ensure_schema()

# ── Verified previous-year question bank ──────────────────────────────────────
SYSTEM_USER_EMAIL = "official@iasmentor.system"
YEARWISE_DURATION_MIN = 120  # full year-wise PYQ papers default to 120 minutes
PYQ_BANK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyq_bank.json")

def _load_pyq_bank():
    """Read the verified previous-year question bank from disk once at startup."""
    if not os.path.exists(PYQ_BANK_FILE):
        return {"papers": []}
    try:
        with open(PYQ_BANK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"papers": []}

PYQ_BANK = _load_pyq_bank()

# Flatten every verified question and tag it with its year + paper. The same bank
# then serves two views: YEAR-WISE (full official papers) and SUBJECT-WISE
# (questions grouped/filtered by subject across all years). No AI is involved —
# these are real exam questions only.
PYQ_QUESTIONS = [
    {**q, "year": paper.get("year"), "paper": paper.get("paper", "UPSC Prelims GS Paper I")}
    for paper in PYQ_BANK.get("papers", [])
    for q in paper.get("questions", [])
]
PYQ_YEARS = sorted({q["year"] for q in PYQ_QUESTIONS if q.get("year")}, reverse=True)
PYQ_SUBJECTS = sorted({q["subject"] for q in PYQ_QUESTIONS if q.get("subject")})

def _load_json_file(fname, default):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

# Descriptive UPSC Mains previous-year questions (browse-only) and original
# AIVORA CSAT practice sets.
MAINS_BANK = _load_json_file("mains_pyq.json", {"papers": []})
MAINS_PAPERS = MAINS_BANK.get("papers", [])
MAINS_QUESTIONS = [
    {**q, "year": p.get("year"), "paper": p.get("paper"), "paper_code": p.get("paper_code")}
    for p in MAINS_PAPERS for q in p.get("questions", [])
]
MAINS_YEARS = sorted({p["year"] for p in MAINS_PAPERS if p.get("year")}, reverse=True)
_MAINS_PAPER_ORDER = ["GS1", "GS2", "GS3", "GS4", "ESSAY"]
MAINS_PAPER_DEFS = []
for code in _MAINS_PAPER_ORDER:
    nm = next((p.get("paper") for p in MAINS_PAPERS if p.get("paper_code") == code), None)
    if nm:
        MAINS_PAPER_DEFS.append({"code": code, "name": nm})
MAINS_SUBJECTS = sorted({q.get("subject") for q in MAINS_QUESTIONS if q.get("subject")})

CSAT_BANK = _load_json_file("csat_practice.json", {"areas": []})
CSAT_AREAS = CSAT_BANK.get("areas", [])

def seed_previous_year_papers():
    """Seed the full verified papers into the DB as ready-to-take mock tests owned
    by a system user (the YEAR-WISE view). Idempotent: each year's paper is created once."""
    data = PYQ_BANK
    if not data.get("papers"):
        return
    db = SessionLocal()
    try:
        sys_user = db.query(DBUser).filter(DBUser.email == SYSTEM_USER_EMAIL).first()
        if not sys_user:
            sys_user = DBUser(name="UPSC Official", email=SYSTEM_USER_EMAIL, hashed_password="!disabled")
            db.add(sys_user); db.commit(); db.refresh(sys_user)
        for paper in data.get("papers", []):
            paper_name = paper.get("paper", "UPSC Prelims GS Paper I")
            year = paper.get("year")
            title = f"{paper_name} — {year} (Official PYQ)"
            questions = paper.get("questions", [])
            if not questions:
                continue
            existing = db.query(DBMockTest).filter(DBMockTest.title == title).first()
            if existing:
                current_count = db.query(DBQuestion).filter(DBQuestion.mock_test_id == existing.id).count()
                first_q = (db.query(DBQuestion)
                           .filter(DBQuestion.mock_test_id == existing.id)
                           .order_by(DBQuestion.id).first())
                up_to_date = (current_count == len(questions)
                              and first_q is not None
                              and first_q.text == questions[0]["text"]
                              and first_q.subject  # ensure per-question subject is populated
                              and existing.duration_minutes == YEARWISE_DURATION_MIN)
                if up_to_date:
                    continue  # same count, content, subjects AND duration — nothing to do
                # Bank changed for this year: refresh the questions in place
                # (reusing the test row so any existing attempts stay linked).
                db.query(DBQuestion).filter(DBQuestion.mock_test_id == existing.id).delete()
                existing.description = paper.get("source_note", "")
                existing.total_questions = len(questions)
                existing.duration_minutes = YEARWISE_DURATION_MIN
                db.commit()
                db_test = existing
            else:
                db_test = DBMockTest(
                    title=title,
                    description=paper.get("source_note", ""),
                    subject="UPSC Prelims (Mixed)",
                    total_questions=len(questions),
                    duration_minutes=YEARWISE_DURATION_MIN,
                    user_id=sys_user.id,
                )
                db.add(db_test); db.commit(); db.refresh(db_test)
            for q in questions:
                db.add(DBQuestion(
                    text=q["text"], option_a=q["option_a"], option_b=q["option_b"],
                    option_c=q["option_c"], option_d=q["option_d"],
                    correct_answer=q["correct_answer"], explanation=q.get("explanation", ""),
                    subject=q.get("subject"),
                    mock_test_id=db_test.id,
                ))
            db.commit()
    finally:
        db.close()

seed_previous_year_papers()

app = FastAPI(title="IAS Mentor AI", description="AI-powered UPSC exam preparation platform", version="2.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> DBUser:
    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    email = payload.get("sub")
    db_user = db.query(DBUser).filter(DBUser.email == email).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user

def _admin_email_set(db: Session) -> set:
    """Built-in (config) admins plus any added via the admin UI (stored in DB)."""
    emails = set(ADMIN_EMAILS)
    try:
        emails |= {(a.email or "").lower() for a in db.query(DBAdminEmail).all()}
    except Exception:
        pass
    return emails

def is_admin(user: DBUser, db: Session) -> bool:
    return bool(user and (user.email or "").lower() in _admin_email_set(db))

def require_admin(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)) -> DBUser:
    if not is_admin(current_user, db):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# ── Schemas ──────────────────────────────────────────────────────────────────
class UserRegister(BaseModel):
    name: Optional[str] = None
    email: str
    password: str
    phone: Optional[str] = None
    target_year: Optional[str] = None
    home_state: Optional[str] = None

class UserLogin(BaseModel):
    email: Optional[str] = None
    identifier: Optional[str] = None   # email OR phone number
    password: str

class ForgotPasswordRequest(BaseModel):
    email: str
    phone: str
    new_password: str

class ProfileIn(BaseModel):
    # Personal details
    full_name: Optional[str] = None
    parent_name: Optional[str] = None
    dob: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    home_state: Optional[str] = None
    district: Optional[str] = None
    prep_location: Optional[str] = None
    prep_city: Optional[str] = None
    # Educational qualification
    education: Optional[str] = None
    graduation_stream: Optional[str] = None
    schooling_medium: Optional[str] = None
    degree_percentage: Optional[str] = None
    additional_qualification: Optional[str] = None
    # Mains exam details
    optional_subject: Optional[str] = None
    mains_language: Optional[str] = None
    medium: Optional[str] = None
    # Category
    category: Optional[str] = None
    # Working experience
    working_professional: Optional[bool] = False
    prep_intensity: Optional[str] = None
    work_experience: Optional[str] = None
    # Previous attempts
    attempts: Optional[str] = None
    failure_stage: Optional[str] = None
    coaching_status: Optional[str] = None
    failure_reason: Optional[str] = None
    # Other details to gauge level
    target_year: Optional[str] = None
    prep_level: Optional[str] = None
    knowledge_level: Optional[str] = None
    comprehension_skill: Optional[str] = None
    reading_speed: Optional[str] = None
    learning_style: Optional[str] = None
    study_hours: Optional[str] = None
    study_time_windows: Optional[str] = None
    study_place: Optional[str] = None
    strong_subjects: Optional[str] = None
    weak_subjects: Optional[str] = None

class DiagnosticStep(BaseModel):
    answered: Optional[List[dict]] = None   # [{id, selected}] accumulated by the client

class QuestionCreate(BaseModel):
    text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    explanation: Optional[str] = None

class MockTestCreate(BaseModel):
    title: str
    description: Optional[str] = None
    subject: str
    topic: Optional[str] = None
    total_questions: int
    duration_minutes: int
    auto_generate: bool = False  # NEW: auto-generate questions with AI

class AnswerSubmit(BaseModel):
    question_id: int
    selected_option: str
    confidence: Optional[str] = None       # sure | unsure | guess
    time_taken: Optional[int] = None       # seconds spent on this question

class RevisionAnswer(BaseModel):
    question_id: int
    selected_option: str
    confidence: Optional[str] = None

class WrongReasonIn(BaseModel):
    reason: str                            # conceptual | factual | careless | misread | guess

class AIGenerateRequest(BaseModel):
    subject: str
    topic: str
    num_questions: int = 5

class AIExplainRequest(BaseModel):
    topic: str
    context: Optional[str] = None

class AIChatRequest(BaseModel):
    message: str

class PreviousYearRequest(BaseModel):
    subject: Optional[str] = None     # None / "" / "All" = all subjects (subject-wise filter)
    year: Optional[str] = None        # e.g. "2023"; blank/None = all years (year-wise filter)
    num_questions: Optional[int] = None  # None / 0 = ALL matching questions
    duration_minutes: Optional[int] = None  # defaults to ~1 min/question if omitted

class NcertGenerateRequest(BaseModel):
    book_key: str                       # key from /ncert/books
    chapter: str                        # chapter name within that book
    num_questions: Optional[int] = 5
    difficulty: Optional[str] = "medium"
    question_type: Optional[str] = "all"   # factual | analytical | all

class VerifiedGenerateRequest(BaseModel):
    subject: Optional[str] = None
    topic: Optional[str] = None
    book: Optional[str] = None
    num_questions: Optional[int] = 5
    difficulty: Optional[str] = "medium"
    question_type: Optional[str] = "all"   # factual | analytical | all
    reuse: Optional[bool] = False          # reuse cached verified questions for this concept

# ── Frontend + Health ─────────────────────────────────────────────────────────
FRONTEND_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "index.html")
ADMIN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "admin.html")

_NOCACHE = {"Cache-Control": "no-cache, must-revalidate", "Pragma": "no-cache"}

@app.get("/", include_in_schema=False)
def serve_frontend():
    """Serve the single-page web app so one deployment hosts both the UI and API."""
    if os.path.exists(FRONTEND_FILE):
        return FileResponse(FRONTEND_FILE, headers=_NOCACHE)
    return {"message": "IAS Mentor AI API is running. Frontend file not found."}

@app.get("/admin", include_in_schema=False)
def serve_admin():
    """Serve the separate admin dashboard at /admin (its own login)."""
    if os.path.exists(ADMIN_FILE):
        return FileResponse(ADMIN_FILE, headers=_NOCACHE)
    return {"message": "Admin page not found."}

@app.get("/health", tags=["Health"])
def health():
    return {"message": "IAS Mentor AI API v2.0 is running ✅"}

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/register", tags=["Auth"])
def register(user: UserRegister, db: Session = Depends(get_db)):
    email = (user.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email is required")
    if not (user.password or "") or len(user.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    phone_digits = "".join(c for c in (user.phone or "") if c.isdigit())
    if len(phone_digits) < 10:
        raise HTTPException(status_code=400, detail="A valid phone number (at least 10 digits) is required")
    if db.query(DBUser).filter(DBUser.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = DBUser(name=(user.name or "").strip() or None, email=email,
                      phone=phone_digits, hashed_password=hash_password(user.password))
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    # Seed a starter profile if onboarding details were provided at sign-up.
    ty = (user.target_year or "").strip()
    st = (user.home_state or "").strip()
    if ty or st:
        try:
            db.add(DBStudentProfile(user_id=new_user.id, target_year=ty or None, home_state=st or None))
            db.commit()
        except Exception:
            db.rollback()
    return {"status": "success", "message": "User registered successfully", "data": {"id": new_user.id, "email": new_user.email}}

@app.post("/login", tags=["Auth"])
def login(user: UserLogin, db: Session = Depends(get_db)):
    ident = (user.identifier or user.email or "").strip()
    db_user = None
    if ident:
        if "@" in ident:
            db_user = db.query(DBUser).filter(DBUser.email == ident.lower()).first()
        else:
            digits = "".join(c for c in ident if c.isdigit())
            if digits:
                # match on stored phone (stored as digits-only at registration)
                db_user = db.query(DBUser).filter(DBUser.phone == digits).first()
            if not db_user:
                # fall back to treating the value as an email/login string
                db_user = db.query(DBUser).filter(DBUser.email == ident.lower()).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email/phone or password")
    token = create_access_token({"sub": db_user.email})
    return {"status": "success", "message": "Login successful", "data": {"access_token": token, "token_type": "bearer", "name": db_user.name or db_user.email, "is_admin": is_admin(db_user, db)}}

@app.post("/forgot-password", tags=["Auth"])
def forgot_password(req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Self-service reset: verify identity with the registered email + phone, then
    set a new password. (No email/SMS infra needed; phone is the verification factor.)"""
    email = (req.email or "").strip().lower()
    db_user = db.query(DBUser).filter(DBUser.email == email).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="No account found with that email")
    if not db_user.phone:
        raise HTTPException(status_code=400, detail="This account has no phone on record. Please contact support to reset your password.")
    given = "".join(c for c in (req.phone or "") if c.isdigit())
    stored = "".join(c for c in (db_user.phone or "") if c.isdigit())
    # Match on the last 10 digits (handles country-code differences).
    if not given or given[-10:] != stored[-10:]:
        raise HTTPException(status_code=400, detail="Phone number does not match our records for this email")
    if not (req.new_password or "") or len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters")
    db_user.hashed_password = hash_password(req.new_password)
    db.commit()
    return {"status": "success", "message": "Password reset successfully. You can now log in."}

@app.post("/__migrate_import", tags=["Admin"])
def __migrate_import(key: str = ""):
    """ONE-TIME data import: copy every table from OLD_DATABASE_URL into the current
    database. Key-gated; disable by clearing the MIGRATION_KEY env var when done."""
    expected = os.getenv("MIGRATION_KEY", "")
    if not expected or key != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    old_url = os.getenv("OLD_DATABASE_URL", "")
    if not old_url:
        raise HTTPException(status_code=400, detail="OLD_DATABASE_URL is not set")
    if old_url.startswith("postgres://"):
        old_url = old_url.replace("postgres://", "postgresql://", 1)
    from sqlalchemy import create_engine as _ce
    old_engine = _ce(old_url)
    copied, skipped = {}, {}
    tables = list(Base.metadata.sorted_tables)
    try:
        with old_engine.connect() as oconn:
            with engine.begin() as nconn:
                for t in reversed(tables):
                    try:
                        nconn.execute(sa_text(f'TRUNCATE TABLE "{t.name}" RESTART IDENTITY CASCADE'))
                    except Exception:
                        pass
                for t in tables:
                    try:
                        rows = [dict(r._mapping) for r in oconn.execute(t.select())]
                    except Exception as e:
                        skipped[t.name] = str(e)[:140]
                        continue
                    for i in range(0, len(rows), 500):
                        if rows[i:i + 500]:
                            nconn.execute(t.insert(), rows[i:i + 500])
                    copied[t.name] = len(rows)
                for t in tables:
                    if "id" in t.c:
                        try:
                            nconn.execute(sa_text(
                                f"SELECT setval(pg_get_serial_sequence('\"{t.name}\"','id'), "
                                f"GREATEST((SELECT COALESCE(MAX(id),1) FROM \"{t.name}\"),1))"))
                        except Exception:
                            pass
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)[:300]}")
    finally:
        old_engine.dispose()
    return {"status": "success", "copied": copied, "skipped": skipped,
            "total_rows": sum(copied.values())}

@app.get("/me", tags=["Auth"])
def whoami(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"status": "success", "name": current_user.name or current_user.email,
            "email": current_user.email, "is_admin": is_admin(current_user, db)}

# ── Student Profile ─────────────────────────────────────────────────────────────
_PROFILE_FIELDS = [
    # Personal details
    "full_name", "parent_name", "dob", "age", "gender", "marital_status",
    "home_state", "district", "phone", "email", "address",
    # Educational qualification
    "education", "graduation_stream", "schooling_medium", "degree_percentage",
    "additional_qualification",
    # Mains exam details
    "optional_subject", "mains_language", "medium",
    # Category
    "category",
    # Working experience
    "working_professional", "prep_intensity", "work_experience",
    # Preparation setup
    "prep_location", "prep_city",
    # Previous attempts
    "attempts", "failure_stage", "coaching_status", "failure_reason",
    # Other details to gauge level
    "target_year", "prep_level", "knowledge_level", "comprehension_skill",
    "reading_speed", "learning_style", "study_hours", "study_time_windows",
    "study_place", "strong_subjects", "weak_subjects",
]

# Fields not counted toward the completion percentage (optional/conditional)
_PROFILE_OPTIONAL = {"working_professional", "prep_intensity", "work_experience",
                     "prep_city", "parent_name", "age", "failure_reason", "study_place",
                     "additional_qualification", "degree_percentage"}

def _profile_dict(p):
    if not p:
        return {f: ("" if f != "working_professional" else False) for f in _PROFILE_FIELDS}
    d = {f: getattr(p, f) for f in _PROFILE_FIELDS}
    for f in _PROFILE_FIELDS:
        if f != "working_professional" and d[f] is None:
            d[f] = ""
    d["working_professional"] = bool(d.get("working_professional"))
    return d

def _profile_completion(d):
    keys = [k for k in _PROFILE_FIELDS if k not in _PROFILE_OPTIONAL]
    filled = sum(1 for k in keys if str(d.get(k) or "").strip())
    return round(100 * filled / len(keys))

# The personalisation signals the daily-mission engine reads off the profile.
_MISSION_SIGNALS = ("study_hours", "prep_intensity", "working_professional",
                    "weak_subjects", "learning_style", "reading_speed",
                    "knowledge_level", "comprehension_skill", "failure_stage",
                    "failure_reason", "diagnostic_gs", "diagnostic_csat")

def _mission_profile(p):
    return {f: getattr(p, f, None) for f in _MISSION_SIGNALS} if p else {}

@app.get("/geo/profile-options", tags=["Auth"])
def geo_profile_options(current_user: DBUser = Depends(get_current_user)):
    """Categories, states, state->districts, optionals etc. for the DAF profile dropdowns."""
    return geo_data.profile_options()

@app.get("/me/profile", tags=["Auth"])
def get_my_profile(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == current_user.id).first()
    d = _profile_dict(p)
    return {"status": "success", "profile": d, "completion": _profile_completion(d),
            "name": current_user.name or "", "email": current_user.email}

@app.put("/me/profile", tags=["Auth"])
def update_my_profile(payload: ProfileIn, current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == current_user.id).first()
    if not p:
        p = DBStudentProfile(user_id=current_user.id)
        db.add(p)
    data = payload.dict()
    for f in _PROFILE_FIELDS:
        if f in data and data[f] is not None:
            setattr(p, f, data[f])
    db.commit()
    db.refresh(p)
    d = _profile_dict(p)
    return {"status": "success", "profile": d, "completion": _profile_completion(d)}


# ── Adaptive Diagnostic (objective knowledge + comprehension baseline) ──────────
def _know_label(s):
    return "Strong" if s >= 75 else ("Good" if s >= 55 else ("Moderate" if s >= 35 else "Low"))

def _csat_label(s):
    return "Strong" if s >= 70 else ("Average" if s >= 45 else "Needs improvement")

@app.post("/me/diagnostic/step", tags=["Diagnostic"])
def diagnostic_step(payload: DiagnosticStep, current_user: DBUser = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Drive the adaptive diagnostic one step at a time. Send the answers given so
    far; get the next adapted question, or — when complete — the scored result,
    which is stored on the profile to calibrate the candidate's tailored plan."""
    answered = payload.answered or []
    q = diagnostic.next_question(answered)
    if q:
        return {"status": "success", "done": False, "question": q, "answered": len(answered)}
    res = diagnostic.score(answered)
    p = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == current_user.id).first()
    if not p:
        p = DBStudentProfile(user_id=current_user.id); db.add(p)
    p.diagnostic_gs = res["gs"]; p.diagnostic_csat = res["csat"]
    # Seed the self-rating fields from the objective result if the user left them blank.
    if not (p.knowledge_level or "").strip():
        p.knowledge_level = _know_label(res["gs"])
    if not (p.comprehension_skill or "").strip():
        p.comprehension_skill = _csat_label(res["csat"])
    db.commit()
    res["knowledge_label"] = _know_label(res["gs"])
    res["comprehension_label"] = _csat_label(res["csat"])
    return {"status": "success", "done": True, "result": res}

@app.get("/me/diagnostic/result", tags=["Diagnostic"])
def diagnostic_result(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    p = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == current_user.id).first()
    gs = p.diagnostic_gs if p else None
    csat = p.diagnostic_csat if p else None
    return {"status": "success", "taken": gs is not None,
            "gs": gs, "csat": csat,
            "knowledge_label": (_know_label(gs) if gs is not None else None),
            "comprehension_label": (_csat_label(csat) if csat is not None else None)}

# ── Syllabus Tracker ──────────────────────────────────────────────────────────
class SyllabusToggle(BaseModel):
    topic_id: str
    completed: bool = True

@app.get("/me/syllabus", tags=["Syllabus"])
def get_my_syllabus(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Full UPSC syllabus tree + this user's completed topic IDs and progress."""
    done = {r.topic_id for r in db.query(DBSyllabusProgress)
            .filter(DBSyllabusProgress.user_id == current_user.id).all()}
    valid = syllabus_tracker_data.all_topic_ids()
    done = {t for t in done if t in valid}
    return {"status": "success", "tree": syllabus_tracker_data.tree_with_ids(),
            "completed": sorted(done), "total": len(valid), "completed_count": len(done)}

@app.post("/me/syllabus/toggle", tags=["Syllabus"])
def toggle_syllabus_topic(payload: SyllabusToggle,
                          current_user: DBUser = Depends(get_current_user),
                          db: Session = Depends(get_db)):
    tid = (payload.topic_id or "").strip()
    if tid not in syllabus_tracker_data.all_topic_ids():
        raise HTTPException(status_code=400, detail="Unknown topic")
    row = db.query(DBSyllabusProgress).filter(
        DBSyllabusProgress.user_id == current_user.id,
        DBSyllabusProgress.topic_id == tid).first()
    if payload.completed and not row:
        db.add(DBSyllabusProgress(user_id=current_user.id, topic_id=tid))
    elif not payload.completed and row:
        db.delete(row)
    db.commit()
    total = db.query(DBSyllabusProgress).filter(DBSyllabusProgress.user_id == current_user.id).count()
    return {"status": "success", "completed": payload.completed,
            "completed_count": total, "total": syllabus_tracker_data.total_topics()}

@app.post("/me/syllabus/reset", tags=["Syllabus"])
def reset_syllabus(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(DBSyllabusProgress).filter(DBSyllabusProgress.user_id == current_user.id).delete()
    db.commit()
    return {"status": "success", "completed_count": 0, "total": syllabus_tracker_data.total_topics()}

# ── Study Planner ─────────────────────────────────────────────────────────────
@app.get("/me/study-plan", tags=["Planner"])
def my_study_plan(target_year: Optional[str] = None, hours: Optional[str] = None,
                  current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Generate a phase-wise AIVORA study schedule for the time left until Prelims.
    Pulls defaults from the student profile; query params override them."""
    p = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == current_user.id).first()
    ty = target_year or (p.target_year if p else None) or ""
    hb = hours or (p.study_hours if p else None) or "2-4"
    weak = (p.weak_subjects if p else None) or ""
    plan = study_planner.generate_plan(ty, hb, weak)
    plan["from_profile"] = {"target_year": (p.target_year if p else None),
                            "study_hours": (p.study_hours if p else None),
                            "weak_subjects": weak}
    return {"status": "success", "plan": plan}

# ── Guided Program (follow-along curriculum) ──────────────────────────────────
def _program_inputs(p):
    ty = (p.target_year if p else None) or ""
    hb = (p.study_hours if p else None) or "2-4"
    weak = (p.weak_subjects if p else None) or ""
    return ty, hb, weak

class GuidedToggle(BaseModel):
    task_id: str
    completed: bool = True

@app.get("/me/program", tags=["Planner"])
def my_program(target_year: Optional[str] = None, hours: Optional[str] = None,
               current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """The full guided task curriculum + the user's completed task IDs and progress."""
    p = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == current_user.id).first()
    ty, hb, weak = _program_inputs(p)
    if target_year:
        ty = target_year
    if hours:
        hb = hours
    prog = guided_program.generate_program(ty, hb, weak)
    done = {r.task_id for r in db.query(DBGuidedProgress)
            .filter(DBGuidedProgress.user_id == current_user.id).all()}
    valid = {t["id"] for d in prog["days"] for t in d["tasks"]}
    done = {t for t in done if t in valid}
    prog["completed"] = sorted(done)
    prog["completed_count"] = len(done)
    return {"status": "success", "program": prog}

@app.post("/me/program/toggle", tags=["Planner"])
def toggle_program_task(payload: GuidedToggle,
                        current_user: DBUser = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    p = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == current_user.id).first()
    ty, hb, weak = _program_inputs(p)
    tid = (payload.task_id or "").strip()
    if tid not in guided_program.all_task_ids(ty, hb, weak):
        raise HTTPException(status_code=400, detail="Unknown task")
    row = db.query(DBGuidedProgress).filter(
        DBGuidedProgress.user_id == current_user.id,
        DBGuidedProgress.task_id == tid).first()
    if payload.completed and not row:
        db.add(DBGuidedProgress(user_id=current_user.id, task_id=tid))
    elif not payload.completed and row:
        db.delete(row)
    db.commit()
    total = db.query(DBGuidedProgress).filter(DBGuidedProgress.user_id == current_user.id).count()
    return {"status": "success", "completed": payload.completed, "completed_count": total}

# ── PrepOS "Today" — the daily decision engine ────────────────────────────────
def _gather_answers(db, user_id):
    rows = (db.query(DBAnswer.is_correct, DBAnswer.time_taken, DBQuestion.subject,
                     DBQuestion.topic, DBQuestion.difficulty, DBTestAttempt.completed_at)
            .join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
            .join(DBQuestion, DBAnswer.question_id == DBQuestion.id)
            .filter(DBTestAttempt.user_id == user_id)
            .order_by(DBTestAttempt.completed_at.asc()).all())
    return [{"is_correct": bool(r[0]), "time_taken": r[1], "subject": r[2],
             "topic": r[3], "difficulty": r[4], "completed_at": r[5]} for r in rows]

def _next_guided_task(db, user, profile):
    ty = (profile.target_year if profile else None) or ""
    hb = (profile.study_hours if profile else None) or "2-4"
    weak = (profile.weak_subjects if profile else None) or ""
    prog = guided_program.generate_program(ty, hb, weak)
    done = {r.task_id for r in db.query(DBGuidedProgress)
            .filter(DBGuidedProgress.user_id == user.id).all()}
    for d in prog["days"]:
        for t in d["tasks"]:
            if t["id"] not in done and t["kind"] in ("read", "ncert_test", "subject_test", "pyq"):
                return {"id": t["id"], "kind": t["kind"], "title": t["title"], "params": t["params"]}
    return None

@app.get("/me/today", tags=["Planner"])
def my_today(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """The full PrepOS state: knowledge map, scorecard, forecast, today's mission, interventions."""
    today = datetime.date.today()
    profile = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == current_user.id).first()
    answers = _gather_answers(db, current_user.id)
    review_items = [{"times_seen": r.times_seen, "times_correct": r.times_correct,
                     "mastered": r.mastered, "next_review": r.next_review}
                    for r in db.query(DBReviewItem).filter(DBReviewItem.user_id == current_user.id).all()]
    attempts = [{"completed_at": a.completed_at, "score": a.score}
                for a in db.query(DBTestAttempt).filter(DBTestAttempt.user_id == current_user.id).all()]
    now = datetime.datetime.utcnow()
    review_due = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == current_user.id,
        DBReviewItem.next_review <= now,
        DBReviewItem.mastered == False).count()  # noqa: E712
    syl_done = db.query(DBSyllabusProgress).filter(DBSyllabusProgress.user_id == current_user.id).count()
    coverage_pct = round(100 * syl_done / max(1, syllabus_tracker_data.total_topics()))

    km = prepos.build_knowledge_map(answers, today)
    mains_evals = db.query(DBMainsAnswer.overall_pct).filter(
        DBMainsAnswer.user_id == current_user.id).order_by(DBMainsAnswer.id.desc()).limit(10).all()
    writing_avg = (sum(m[0] for m in mains_evals) / len(mains_evals)) if mains_evals else None
    scores = prepos.compute_scores(answers, review_items, attempts, coverage_pct, today, writing_avg)
    ty_label = ""
    try:
        ty_label = study_planner.generate_plan(
            (profile.target_year if profile else None) or "",
            (profile.study_hours if profile else None) or "2-4",
            (profile.weak_subjects if profile else None) or "")["exam_label"]
    except Exception:
        ty_label = "UPSC Prelims"
    fcast = prepos.forecast(scores, ty_label)
    nxt = _next_guided_task(db, current_user, profile)
    hb = (profile.study_hours if profile else None) or "2-4"
    mp = _mission_profile(profile)
    mission = prepos.daily_mission(km, review_due, hb, nxt, today, mp)
    inter = prepos.interventions(answers, km, attempts, today)
    checkins = prepos.checkins(mp, scores, km, attempts, answers, review_due, today)
    brief = prepos.briefing(current_user.name or current_user.email.split("@")[0], scores, mission, datetime.datetime.now())

    done_keys = {r.task_key for r in db.query(DBDailyMissionDone).filter(
        DBDailyMissionDone.user_id == current_user.id,
        DBDailyMissionDone.day == today.isoformat()).all()}
    for t in mission["tasks"]:
        t["done"] = t["key"] in done_keys

    return {"status": "success", "today": {
        "briefing": brief, "mission": mission, "scores": scores,
        "forecast": fcast, "knowledge_map": km, "interventions": inter,
        "exam_label": ty_label, "coverage": coverage_pct, "checkins": checkins,
    }}

class TodayDone(BaseModel):
    task_key: str
    completed: bool = True

@app.post("/me/today/done", tags=["Planner"])
def today_done(payload: TodayDone, current_user: DBUser = Depends(get_current_user),
               db: Session = Depends(get_db)):
    day = datetime.date.today().isoformat()
    row = db.query(DBDailyMissionDone).filter(
        DBDailyMissionDone.user_id == current_user.id,
        DBDailyMissionDone.day == day,
        DBDailyMissionDone.task_key == payload.task_key).first()
    if payload.completed and not row:
        db.add(DBDailyMissionDone(user_id=current_user.id, day=day, task_key=payload.task_key))
    elif not payload.completed and row:
        db.delete(row)
    db.commit()
    return {"status": "success", "completed": payload.completed}

# ── Mains answer writing + AI evaluation (feeds writing quality) ──────────────
class MainsEvalRequest(BaseModel):
    question: str
    answer: str
    marks: Optional[int] = 10
    paper: Optional[str] = None

@app.post("/me/mains/evaluate", tags=["Mains PYQ"])
def mains_evaluate(req: MainsEvalRequest, current_user: DBUser = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    q = (req.question or "").strip()
    a = (req.answer or "").strip()
    if not q or len(a) < 30:
        raise HTTPException(status_code=400, detail="Please write at least a few sentences for evaluation.")
    marks = req.marks or 10
    ev = evaluate_mains_answer(q, a, marks)
    row = DBMainsAnswer(user_id=current_user.id, question=q[:2000], answer=a[:8000],
                        paper=(req.paper or "")[:60], overall_pct=ev.get("overall_pct", 0),
                        overall_marks=str(ev.get("overall_marks", "")), marks=marks,
                        eval_json=json.dumps(ev))
    db.add(row); db.commit(); db.refresh(row)
    return {"status": "success", "id": row.id, "evaluation": ev}

@app.get("/me/mains/history", tags=["Mains PYQ"])
def mains_history(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(DBMainsAnswer).filter(DBMainsAnswer.user_id == current_user.id)
            .order_by(DBMainsAnswer.id.desc()).limit(30).all())
    out = []
    for r in rows:
        try:
            ev = json.loads(r.eval_json) if r.eval_json else {}
        except Exception:
            ev = {}
        out.append({"id": r.id, "question": r.question, "paper": r.paper,
                    "overall_pct": r.overall_pct, "overall_marks": r.overall_marks,
                    "marks": r.marks, "evaluation": ev,
                    "created_at": r.created_at.isoformat() if r.created_at else None})
    avg = round(sum(r.overall_pct for r in rows) / len(rows)) if rows else None
    return {"status": "success", "answers": out, "count": len(out), "writing_quality": avg}

# ── Weekly mentor report + trends ─────────────────────────────────────────────
@app.get("/me/report", tags=["Planner"])
def my_report(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    today = datetime.date.today()
    answers = _gather_answers(db, current_user.id)
    attempts = [{"completed_at": a.completed_at, "score": a.score}
                for a in db.query(DBTestAttempt).filter(DBTestAttempt.user_id == current_user.id).all()]
    report = prepos.weekly_report(answers, attempts, today)
    name = current_user.name or (current_user.email or "Aspirant").split("@")[0]
    narrative = weekly_mentor_narrative(report["summary"], name) if report["has_data"] else (
        "Welcome to AIVORA. Take a few tests this week and your first weekly report — with trends and a "
        "personal note from your AI mentor — will appear right here.")
    report["narrative"] = narrative
    return {"status": "success", "report": report}

# ── Mock Tests ────────────────────────────────────────────────────────────────
@app.post("/mock-tests/", tags=["Mock Tests"])
def create_mock_test(mock_test: MockTestCreate, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    db_test = DBMockTest(
        title=mock_test.title, description=mock_test.description,
        subject=mock_test.subject, total_questions=mock_test.total_questions,
        duration_minutes=mock_test.duration_minutes, user_id=current_user.id,
    )
    db.add(db_test)
    db.commit()
    db.refresh(db_test)

    questions_added = 0
    if mock_test.auto_generate:
        topic = mock_test.topic or mock_test.subject
        try:
            parsed = generate_and_parse_questions(mock_test.subject, topic, mock_test.total_questions)
            for q in parsed:
                db_q = DBQuestion(
                    text=q['text'], option_a=q['option_a'], option_b=q['option_b'],
                    option_c=q['option_c'], option_d=q['option_d'],
                    correct_answer=q['correct_answer'], explanation=q['explanation'],
                    mock_test_id=db_test.id,
                )
                db.add(db_q)
            db.commit()
            questions_added = len(parsed)
        except Exception as e:
            pass  # Test created, questions will need to be added manually

    return {
        "status": "success",
        "message": f"Mock test created{'with ' + str(questions_added) + ' AI questions' if questions_added else ''}",
        "mock_test_id": db_test.id,
        "questions_added": questions_added,
    }

@app.get("/previous-year-papers/", tags=["Mock Tests"])
def list_previous_year_papers(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """List the real, verified previous-year papers seeded from the question bank."""
    sys_user = db.query(DBUser).filter(DBUser.email == SYSTEM_USER_EMAIL).first()
    if not sys_user:
        return {"status": "success", "papers": []}
    tests = db.query(DBMockTest).filter(DBMockTest.user_id == sys_user.id).order_by(DBMockTest.title.desc()).all()
    return {
        "status": "success",
        "papers": [
            {
                "id": t.id, "title": t.title, "description": t.description,
                "total_questions": t.total_questions, "duration_minutes": t.duration_minutes,
                "questions_added": db.query(DBQuestion).filter(DBQuestion.mock_test_id == t.id).count(),
            }
            for t in tests
        ],
    }

@app.get("/previous-year-papers/subjects/", tags=["Mock Tests"])
def previous_year_subjects(current_user: DBUser = Depends(get_current_user)):
    """SUBJECT-WISE index of the verified bank: how many real questions exist per
    subject (and per year), so the UI can offer subject-wise practice sets."""
    by_subject = {}
    for q in PYQ_QUESTIONS:
        s = q.get("subject")
        if not s:
            continue
        entry = by_subject.setdefault(s, {"subject": s, "count": 0, "years": {}})
        entry["count"] += 1
        yr = q.get("year")
        if yr:
            entry["years"][yr] = entry["years"].get(yr, 0) + 1
    subjects = [
        {"subject": e["subject"], "count": e["count"],
         "years": sorted(e["years"].keys(), reverse=True)}
        for e in sorted(by_subject.values(), key=lambda x: x["subject"])
    ]
    return {
        "status": "success",
        "subjects": subjects,
        "years": PYQ_YEARS,
        "total_questions": len(PYQ_QUESTIONS),
    }

@app.post("/mock-tests/previous-year/", tags=["Mock Tests"])
def create_previous_year_test(request: PreviousYearRequest, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Build a ready-to-take mock test from the VERIFIED previous-year bank,
    filtered by subject and/or year. Real exam questions only — no AI generation."""
    subject = (request.subject or "").strip()
    year = (request.year or "").strip()
    all_subjects = (not subject) or subject.lower() in ("all", "all subjects")

    # Filter the verified bank by the requested subject and/or year.
    pool = PYQ_QUESTIONS
    if not all_subjects:
        pool = [q for q in pool if q.get("subject") == subject]
    if year:
        pool = [q for q in pool if str(q.get("year")) == year]

    if not pool:
        raise HTTPException(
            status_code=404,
            detail="No verified previous-year questions match that subject/year yet.",
        )

    # No count (subject-wise practice) => use ALL matching questions; otherwise cap.
    if not request.num_questions or request.num_questions <= 0:
        selected = random.sample(pool, len(pool))
    else:
        num = max(1, min(request.num_questions, 250))
        selected = random.sample(pool, min(num, len(pool)))

    label_subject = "All Subjects" if all_subjects else subject
    duration = request.duration_minutes if request.duration_minutes else max(10, len(selected))
    title = f"PYQ • {label_subject}" + (f" • {year}" if year else "")

    db_test = DBMockTest(
        title=title,
        description=(
            f"Verified previous-year UPSC questions — {label_subject}"
            + (f" ({year})" if year else " (all years)")
        ),
        subject=label_subject,
        total_questions=len(selected),
        duration_minutes=duration,
        user_id=current_user.id,
    )
    db.add(db_test)
    db.commit()
    db.refresh(db_test)

    for q in selected:
        db.add(DBQuestion(
            text=q["text"], option_a=q["option_a"], option_b=q["option_b"],
            option_c=q["option_c"], option_d=q["option_d"],
            correct_answer=q["correct_answer"], explanation=q.get("explanation", ""),
            subject=q.get("subject"),
            mock_test_id=db_test.id,
        ))
    db.commit()

    return {
        "status": "success",
        "message": f"Verified previous-year test created with {len(selected)} questions",
        "mock_test_id": db_test.id,
        "questions_added": len(selected),
        "available": len(pool),
        "duration_minutes": duration,
    }

# ── Mains PYQs (descriptive, browse-only) ─────────────────────────────────────
@app.get("/pyq/mains/index", tags=["Mains PYQ"])
def mains_index(current_user: DBUser = Depends(get_current_user)):
    """Available years, papers and subject themes for the Mains PYQ browser."""
    return {"status": "success", "years": MAINS_YEARS, "papers": MAINS_PAPER_DEFS,
            "subjects": MAINS_SUBJECTS, "total_questions": len(MAINS_QUESTIONS)}

@app.get("/pyq/mains/questions", tags=["Mains PYQ"])
def mains_questions(year: Optional[str] = None, paper_code: Optional[str] = None,
                    subject: Optional[str] = None,
                    current_user: DBUser = Depends(get_current_user)):
    """Filtered list of real descriptive UPSC Mains questions (read/practice only)."""
    pool = MAINS_QUESTIONS
    if year:
        pool = [q for q in pool if str(q.get("year")) == str(year)]
    if paper_code:
        pool = [q for q in pool if (q.get("paper_code") or "").upper() == paper_code.upper()]
    if subject and subject.lower() not in ("all", "all subjects"):
        pool = [q for q in pool if q.get("subject") == subject]
    # Sort newest year first, then by paper order
    order = {c: i for i, c in enumerate(_MAINS_PAPER_ORDER)}
    items = sorted(pool, key=lambda q: (-(q.get("year") or 0), order.get(q.get("paper_code"), 9)))
    out = [{"q": q.get("q"), "subject": q.get("subject"), "marks": q.get("marks"),
            "words": q.get("words"), "year": q.get("year"), "paper": q.get("paper"),
            "paper_code": q.get("paper_code")} for q in items]
    return {"status": "success", "count": len(out), "questions": out}

# ── CSAT practice (original AIVORA sets, attemptable as MCQs) ──────────────────
@app.get("/pyq/csat/areas", tags=["CSAT"])
def csat_areas(current_user: DBUser = Depends(get_current_user)):
    return {"status": "success",
            "areas": [{"code": a["code"], "name": a["name"],
                       "count": len(a.get("questions", []))} for a in CSAT_AREAS]}

class CSATStart(BaseModel):
    area: Optional[str] = None

@app.post("/pyq/csat/start", tags=["CSAT"])
def csat_start(req: CSATStart, db: Session = Depends(get_db),
               current_user: DBUser = Depends(get_current_user)):
    """Build an attemptable mock test from an AIVORA CSAT practice area."""
    area = next((a for a in CSAT_AREAS if a["code"] == (req.area or "")), None)
    if not area:
        raise HTTPException(status_code=404, detail="Unknown CSAT area")
    qs = area.get("questions", [])
    if not qs:
        raise HTTPException(status_code=404, detail="No questions in this area yet")
    title = f"CSAT Practice • {area['name']}"
    db_test = DBMockTest(title=title, description="AIVORA CSAT practice set (original, exam-pattern)",
                         subject="CSAT", total_questions=len(qs),
                         duration_minutes=max(10, len(qs) * 2), user_id=current_user.id)
    db.add(db_test); db.commit(); db.refresh(db_test)
    for q in qs:
        db.add(DBQuestion(
            text=q["text"], option_a=q["option_a"], option_b=q["option_b"],
            option_c=q["option_c"], option_d=q["option_d"],
            correct_answer=q["correct_answer"], explanation=q.get("explanation", ""),
            subject="CSAT", topic=area["name"], difficulty="medium",
            question_type="csat", mock_test_id=db_test.id))
    db.commit()
    return {"status": "success", "mock_test_id": db_test.id,
            "questions_added": len(qs), "duration_minutes": db_test.duration_minutes,
            "title": title}

@app.get("/mock-tests/", tags=["Mock Tests"])
def get_all_mock_tests(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    tests = db.query(DBMockTest).all()
    return {
        "status": "success",
        "mock_tests": [
            {
                "id": t.id, "title": t.title, "subject": t.subject,
                "total_questions": t.total_questions, "duration_minutes": t.duration_minutes,
                "questions_added": db.query(DBQuestion).filter(DBQuestion.mock_test_id == t.id).count(),
                "attempts_count": db.query(DBTestAttempt).filter(DBTestAttempt.mock_test_id == t.id).count(),
            }
            for t in tests
        ],
    }

@app.get("/mock-tests/{mock_test_id}/", tags=["Mock Tests"])
def get_mock_test(mock_test_id: int, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    db_test = db.query(DBMockTest).filter(DBMockTest.id == mock_test_id).first()
    if not db_test:
        raise HTTPException(status_code=404, detail="Mock test not found")
    question_count = db.query(DBQuestion).filter(DBQuestion.mock_test_id == mock_test_id).count()
    return {
        "status": "success",
        "mock_test": {
            "id": db_test.id, "title": db_test.title, "description": db_test.description,
            "subject": db_test.subject, "total_questions": db_test.total_questions,
            "duration_minutes": db_test.duration_minutes, "questions_added": question_count,
        },
    }

@app.post("/mock-tests/{mock_test_id}/questions/", tags=["Mock Tests"])
def add_question(mock_test_id: int, question: QuestionCreate, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    if not db.query(DBMockTest).filter(DBMockTest.id == mock_test_id).first():
        raise HTTPException(status_code=404, detail="Mock test not found")
    if question.correct_answer.upper() not in ("A", "B", "C", "D"):
        raise HTTPException(status_code=422, detail="correct_answer must be A, B, C, or D")
    db_q = DBQuestion(
        text=question.text, option_a=question.option_a, option_b=question.option_b,
        option_c=question.option_c, option_d=question.option_d,
        correct_answer=question.correct_answer.upper(), explanation=question.explanation,
        mock_test_id=mock_test_id,
    )
    db.add(db_q)
    db.commit()
    db.refresh(db_q)
    return {"status": "success", "message": "Question added", "question_id": db_q.id}

@app.post("/mock-tests/{mock_test_id}/ai-populate/", tags=["Mock Tests"])
def ai_populate_test(mock_test_id: int, topic: str, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Generate and save AI questions directly into an existing test."""
    db_test = db.query(DBMockTest).filter(DBMockTest.id == mock_test_id).first()
    if not db_test:
        raise HTTPException(status_code=404, detail="Mock test not found")
    try:
        parsed = generate_and_parse_questions(db_test.subject, topic, db_test.total_questions)
        for q in parsed:
            db_q = DBQuestion(
                text=q['text'], option_a=q['option_a'], option_b=q['option_b'],
                option_c=q['option_c'], option_d=q['option_d'],
                correct_answer=q['correct_answer'], explanation=q['explanation'],
                mock_test_id=mock_test_id,
            )
            db.add(db_q)
        db.commit()
        return {"status": "success", "questions_added": len(parsed)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

@app.get("/mock-tests/{mock_test_id}/questions/", tags=["Mock Tests"])
def get_mock_test_questions(mock_test_id: int, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    if not db.query(DBMockTest).filter(DBMockTest.id == mock_test_id).first():
        raise HTTPException(status_code=404, detail="Mock test not found")
    questions = db.query(DBQuestion).filter(DBQuestion.mock_test_id == mock_test_id).all()
    return {
        "status": "success",
        "questions": [{"id": q.id, "text": q.text, "option_a": q.option_a, "option_b": q.option_b, "option_c": q.option_c, "option_d": q.option_d, "subject": q.subject, "topic": q.topic} for q in questions],
    }

# Spaced-repetition forgetting curve (days). Index by `repetitions`.
SR_INTERVALS = [1, 7, 30, 90]

def _schedule_review_on_wrong(db, user_id, question_id):
    """A missed question enters (or resets in) the spaced-repetition queue."""
    item = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == user_id, DBReviewItem.question_id == question_id).first()
    now = datetime.datetime.utcnow()
    if not item:
        item = DBReviewItem(user_id=user_id, question_id=question_id)
        db.add(item)
    item.repetitions = 0
    item.interval_days = SR_INTERVALS[0]
    item.next_review = now + datetime.timedelta(days=SR_INTERVALS[0])
    item.mastered = False

def _advance_review(db, user_id, question_id, correct):
    """Update an item's schedule after a revision attempt (SM-2-lite)."""
    item = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == user_id, DBReviewItem.question_id == question_id).first()
    if not item:
        return
    now = datetime.datetime.utcnow()
    item.last_reviewed = now
    item.times_seen = (item.times_seen or 0) + 1
    if correct:
        item.times_correct = (item.times_correct or 0) + 1
        item.repetitions = (item.repetitions or 0) + 1
        if item.repetitions >= len(SR_INTERVALS):
            item.mastered = True
            item.interval_days = SR_INTERVALS[-1]
            item.next_review = now + datetime.timedelta(days=365)
        else:
            item.interval_days = SR_INTERVALS[item.repetitions]
            item.next_review = now + datetime.timedelta(days=item.interval_days)
    else:
        item.repetitions = 0
        item.interval_days = SR_INTERVALS[0]
        item.next_review = now + datetime.timedelta(days=SR_INTERVALS[0])
        item.mastered = False


@app.post("/mock-tests/{mock_test_id}/submit/", tags=["Mock Tests"])
def submit_mock_test(mock_test_id: int, answers: List[AnswerSubmit], db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    db_test = db.query(DBMockTest).filter(DBMockTest.id == mock_test_id).first()
    if not db_test:
        raise HTTPException(status_code=404, detail="Mock test not found")
    score = 0
    answer_objs = []
    total_time = 0
    for ans in answers:
        db_q = db.query(DBQuestion).filter(DBQuestion.id == ans.question_id, DBQuestion.mock_test_id == mock_test_id).first()
        if not db_q:
            continue
        is_correct = db_q.correct_answer == ans.selected_option.upper()
        if is_correct:
            score += 1
        tt = ans.time_taken if (ans.time_taken is not None and ans.time_taken >= 0) else None
        if tt:
            total_time += tt
        conf = (ans.confidence or "").lower().strip() or None
        if conf not in (None, "sure", "unsure", "guess"):
            conf = None
        answer_objs.append(DBAnswer(
            selected_option=ans.selected_option.upper(), is_correct=is_correct,
            question_id=ans.question_id, time_taken=tt, confidence=conf,
        ))
        # Wrong answers feed the spaced-repetition queue.
        if not is_correct:
            _schedule_review_on_wrong(db, current_user.id, db_q.id)
    db_attempt = DBTestAttempt(score=score, time_taken_seconds=total_time, user_id=current_user.id, mock_test_id=mock_test_id, answers=answer_objs)
    db.add(db_attempt)
    db.commit()
    db.refresh(db_attempt)
    total = db_test.total_questions
    return {
        "status": "success", "message": "Test submitted successfully",
        "score": score, "total_questions": total,
        "percentage": round((score / total) * 100, 1) if total else 0,
        "attempt_id": db_attempt.id,
    }

# ── NCERT MCQs (book-wise + chapter-wise, AI-verified) ────────────────────────
@app.get("/ncert/books", tags=["NCERT"])
def ncert_books(current_user: DBUser = Depends(get_current_user)):
    """List NCERT books available for chapter-wise practice (with their chapters)."""
    books = []
    for b in syllabus_data.NCERT_BOOKS:
        books.append({
            "key": b["key"], "book": b["book"], "subject": b["subject"],
            "grade": b["grade"], "chapters": b["chapters"],
            "read_url": b.get("read_url", ""),
        })
    return {"status": "success", "books": books}


# ── Admin-uploaded NCERT book PDFs (read fully in-app) ──────────────────────────
# NOTE: everything here is written to be MEMORY-LEAN — the free tier has little
# RAM, so we never hold a whole zip (or all chapters) in memory at once. Zips are
# streamed to a temp file on disk, and chapters are stored one at a time.
def _ncert_chapter_names(zf):
    """Names of the chapter PDFs inside the zip, in reading order. Front-matter /
    answer files (…ps.pdf, …an.pdf, cover) are skipped; chapter files end in a number."""
    items = []
    for name in zf.namelist():
        low = name.lower()
        if low.endswith("/") or not low.endswith(".pdf"):
            continue
        base = low.rsplit("/", 1)[-1]
        m = re.search(r'(\d+)\.pdf$', base)
        if not m:
            continue
        items.append((int(m.group(1)), base, name))
    items.sort(key=lambda x: (x[0], x[1]))
    return items


def _store_book_from_zip_path(db, book_key, zip_path):
    """Store each chapter PDF from a zip on disk, ONE at a time (commit + free
    between chapters), so peak memory stays at a single chapter."""
    stored = 0
    with zipfile.ZipFile(zip_path) as zf:
        items = _ncert_chapter_names(zf)
        if not items:
            return 0
        db.query(DBNcertPdf).filter(DBNcertPdf.book_key == book_key).delete()
        db.commit()
        for _num, base, fullname in items:
            try:
                data = zf.read(fullname)
            except Exception:
                continue
            if data[:4] != b"%PDF":
                del data
                continue
            obj = DBNcertPdf(book_key=book_key, chapter_index=stored,
                             filename=base[:200], data=data, size=len(data))
            db.add(obj)
            db.commit()
            db.expunge(obj)          # drop the big bytes from the session identity map
            stored += 1
            del data, obj
            gc.collect()
    return stored


def _download_ncert_to_tempfile(url, timeout=120):
    """Stream an NCERT zip to a temp file on disk (never fully in memory).
    Render's servers have open egress to ncert.nic.in. Returns the temp path."""
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "*/*",
        "Referer": "https://ncert.nic.in/textbook.php",
    }
    last = ""
    for _u in (url, url.replace("https://", "http://")):
        try:
            with urlopen(_UrlRequest(_u, headers=headers), timeout=timeout, context=ctx) as r:
                tf = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
                try:
                    while True:
                        chunk = r.read(1 << 20)   # 1 MB at a time
                        if not chunk:
                            break
                        tf.write(chunk)
                finally:
                    tf.close()
                if os.path.getsize(tf.name) > 0:
                    return tf.name
                os.remove(tf.name)
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__} {getattr(e, 'code', '')}".strip()
    raise HTTPException(status_code=502, detail=f"Could not download from NCERT ({last or 'unknown'}).")


@app.post("/admin/ncert/upload-zip", tags=["NCERT"])
async def admin_ncert_upload_zip(file: UploadFile = File(...), book_key: str = Form(...),
                                 admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Admin: upload the NCERT book zip (as downloaded from ncert.nic.in). We
    stream it to disk, extract each chapter PDF and store it — memory-lean."""
    book = syllabus_data.get_ncert_book(book_key)
    if not book:
        raise HTTPException(status_code=400, detail="Unknown NCERT book key.")
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            tf.write(chunk)
    finally:
        tf.close()
    tmp = tf.name
    try:
        if os.path.getsize(tmp) == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        try:
            stored = _store_book_from_zip_path(db, book_key, tmp)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="That doesn't look like a valid .zip file. Upload the zip downloaded from NCERT.")
        if not stored:
            raise HTTPException(status_code=400, detail="No chapter PDFs found inside the zip.")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
        gc.collect()
    return {"status": "success", "book_key": book_key, "chapters_stored": stored,
            "message": f"Stored {stored} chapter PDF(s) for {book['book']}."}


def _http_get(url, timeout=30, attempts=2):
    """Small server-side GET into memory (archive metadata + single chapter PDFs).
    Uses the same browser-like headers as the NCERT proxy (NCERT wants a Referer),
    with an http fallback and a bounded retry so a flaky moment recovers fast."""
    import ssl
    import time as _time
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://ncert.nic.in/textbook.php",
    }
    variants = [url]
    if url.startswith("https://"):
        variants.append(url.replace("https://", "http://", 1))
    last = None
    for i in range(max(1, attempts)):
        for u in variants:
            try:
                with urlopen(_UrlRequest(u, headers=headers), timeout=timeout, context=ctx) as r:
                    data = r.read()
                if data:
                    return data
            except Exception as e:  # noqa: BLE001
                last = e
        _time.sleep(0.7)
    if last:
        raise last
    raise RuntimeError("empty response")


def _record_chapter_urls(db, book_key, url_list):
    """Store just the chapter SOURCE URLs (no bytes) so the DB stays tiny; the
    reader streams each chapter from its source on demand."""
    db.query(DBNcertPdf).filter(DBNcertPdf.book_key == book_key).delete()
    db.commit()
    for i, (fn, src) in enumerate(url_list):
        db.add(DBNcertPdf(book_key=book_key, chapter_index=i, filename=(fn or "")[:200],
                          src_url=src, data=None, size=0))
    db.commit()
    return len(url_list)


def _import_from_archive(db, book_key, item_id):
    """Record a book's chapter URLs from an archive.org item (freely-distributed
    NCERT textbooks NCERT no longer hosts). No bytes are stored."""
    meta = json.loads(_http_get("https://archive.org/metadata/" + item_id).decode("utf-8", "ignore"))
    files = meta.get("files") or []
    chaps = []
    for f in files:
        nm = f.get("name", "")
        low = nm.lower()
        if not low.endswith(".pdf") or low.endswith("ps.pdf") or low.endswith("an.pdf"):
            continue
        m = re.search(r'(\d+)\.pdf$', low)   # chapter files end in a number
        if not m:
            continue
        chaps.append((int(m.group(1)), nm))
    chaps.sort(key=lambda x: (x[0], x[1]))
    if not chaps:
        return 0
    url_list = [(nm, "https://archive.org/download/" + item_id + "/" + nm) for _n, nm in chaps]
    return _record_chapter_urls(db, book_key, url_list)


def _ncert_zip_chapter_urls(zip_path):
    """From an NCERT book zip, list (filename, public chapter-PDF URL) in reading
    order — the chapter files also live at ncert.nic.in/textbook/pdf/<name>."""
    out = []
    with zipfile.ZipFile(zip_path) as zf:
        for _num, base, _full in _ncert_chapter_names(zf):
            out.append((base, "https://ncert.nic.in/textbook/pdf/" + base))
    return out


@app.post("/admin/ncert/import/{book_key}", tags=["NCERT"])
def admin_ncert_import(book_key: str, admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Admin: pull a book's chapters server-side and store them — no manual work.
    Source is the NCERT zip, or an archive.org mirror (for books NCERT dropped)."""
    book = syllabus_data.get_ncert_book(book_key)
    if not book:
        raise HTTPException(status_code=400, detail="Unknown NCERT book key.")
    url = (book.get("read_url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="No download link on file for this book — upload its zip manually.")
    if url.startswith("archive:"):
        try:
            stored = _import_from_archive(db, book_key, url[len("archive:"):])
        except Exception as e:  # noqa: BLE001
            try:
                db.rollback()
            except Exception:
                pass
            raise HTTPException(status_code=502, detail=f"Archive import failed: {type(e).__name__}: {str(e)[:180]}")
        if not stored:
            raise HTTPException(status_code=502, detail="No chapter PDFs found at the archive source.")
        return {"status": "success", "book_key": book_key, "chapters_stored": stored,
                "message": f"Imported {stored} chapter(s) for {book['book']}."}
    # NCERT-hosted book: fetch the zip once just to read the chapter list, then
    # store only the public chapter URLs (no bytes).
    tmp = _download_ncert_to_tempfile(url)
    try:
        try:
            url_list = _ncert_zip_chapter_urls(tmp)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=502, detail="NCERT returned something that isn't a valid zip. Try again, or upload manually.")
        if not url_list:
            raise HTTPException(status_code=502, detail="No chapter PDFs found in the downloaded zip.")
        stored = _record_chapter_urls(db, book_key, url_list)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
        gc.collect()
    return {"status": "success", "book_key": book_key, "chapters_stored": stored,
            "message": f"Imported {stored} chapter(s) for {book['book']} from NCERT."}


@app.post("/admin/db/free-ncert-space", tags=["NCERT"])
def admin_free_ncert_space(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Recovery: clear the stored NCERT PDF bytes to free the database (which went
    read-only after it filled up). Tries to force the session read-write first."""
    out = {}
    for stmt in ("SET default_transaction_read_only = off",
                 "SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE"):
        try:
            db.execute(sa_text(stmt)); out[stmt] = "ok"
        except Exception as e:  # noqa: BLE001
            out[stmt] = type(e).__name__
    try:
        out["rows_before"] = db.execute(sa_text("SELECT count(*) FROM ncert_pdfs")).scalar()
    except Exception as e:  # noqa: BLE001
        out["count_err"] = str(e)[:120]
    try:
        db.execute(sa_text("TRUNCATE TABLE ncert_pdfs"))
        db.commit()
        out["truncated"] = True
    except Exception as e:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:
            pass
        out["truncated"] = False
        out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    return out


@app.get("/admin/ncert/importable", tags=["NCERT"])
def admin_ncert_importable(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Admin: every NCERT book, whether it has a download link, and whether it's
    already stored — drives the one-click 'Import from NCERT' list."""
    have = {}
    for (bk,) in db.query(DBNcertPdf.book_key).all():
        have[bk] = have.get(bk, 0) + 1
    out = []
    for b in syllabus_data.NCERT_BOOKS:
        out.append({"book_key": b["key"], "book": b["book"], "subject": b["subject"],
                    "grade": b.get("grade", ""), "has_link": bool(b.get("read_url")),
                    "stored_chapters": have.get(b["key"], 0)})
    return {"status": "success", "books": out}


@app.get("/admin/ncert/uploaded", tags=["NCERT"])
def admin_ncert_uploaded(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Admin: which NCERT books have uploaded PDFs, with chapter counts & size."""
    rows = db.query(DBNcertPdf.book_key, DBNcertPdf.chapter_index, DBNcertPdf.size).all()
    agg = {}
    for bk, ci, sz in rows:
        a = agg.setdefault(bk, {"chapters": 0, "bytes": 0})
        a["chapters"] += 1
        a["bytes"] += (sz or 0)
    out = []
    for b in syllabus_data.NCERT_BOOKS:
        a = agg.get(b["key"])
        if a:
            out.append({"book_key": b["key"], "book": b["book"], "subject": b["subject"],
                        "chapters": a["chapters"], "mb": round(a["bytes"] / 1048576, 1)})
    return {"status": "success", "uploaded": out}


@app.delete("/admin/ncert/{book_key}", tags=["NCERT"])
def admin_ncert_delete(book_key: str, admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    n = db.query(DBNcertPdf).filter(DBNcertPdf.book_key == book_key).delete()
    db.commit()
    return {"status": "success", "removed": n}


@app.get("/ncert/uploaded-books", tags=["NCERT"])
def ncert_uploaded_books(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Which NCERT books have an in-app readable upload (book_key -> chapter count)."""
    rows = db.query(DBNcertPdf.book_key).all()
    counts = {}
    for (bk,) in rows:
        counts[bk] = counts.get(bk, 0) + 1
    return {"status": "success", "counts": counts}


@app.get("/ncert/book-pdf/{book_key}/{ch}", tags=["NCERT"])
def ncert_book_pdf(book_key: str, ch: int, db: Session = Depends(get_db)):
    """Serve one NCERT chapter PDF, same-origin, so it renders in-app. Streams from
    the chapter's source URL (DB holds only the link); manual uploads serve bytes."""
    row = (db.query(DBNcertPdf)
           .filter(DBNcertPdf.book_key == book_key, DBNcertPdf.chapter_index == ch)
           .first())
    if not row:
        raise HTTPException(status_code=404, detail="That chapter isn't available yet.")
    hdrs = {"Content-Disposition": "inline; filename=ncert-chapter.pdf",
            "Cache-Control": "public, max-age=86400"}
    if row.data:                       # manual upload kept raw bytes
        return Response(content=row.data, media_type="application/pdf", headers=hdrs)
    if row.src_url:                    # stream from the source (NCERT / archive)
        try:
            data = _http_get(row.src_url)
        except Exception:
            raise HTTPException(status_code=502, detail="Couldn't fetch this chapter from its source right now.")
        if not data or data[:4] != b"%PDF":
            raise HTTPException(status_code=502, detail="The source didn't return a valid PDF.")
        return Response(content=data, media_type="application/pdf", headers=hdrs)
    raise HTTPException(status_code=404, detail="That chapter isn't available yet.")


_BOOKPDF_PATH_RE = re.compile(r'^/ncert/book-pdf/[A-Za-z0-9_\-]+/\d+$')

@app.get("/read", response_class=HTMLResponse, tags=["NCERT"])
def read_pdf_viewer(u: str, t: str = "NCERT"):
    """A tiny standalone PDF viewer page. 'Open in new tab' points here so the
    chapter always DISPLAYS in the browser (rendered with PDF.js) instead of
    downloading — regardless of the browser's PDF-handling setting."""
    if not _BOOKPDF_PATH_RE.match(u or ""):
        raise HTTPException(status_code=400, detail="Invalid document reference.")
    safe_t = (t or "NCERT").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    safe_u = u.replace("&", "&amp;").replace('"', "&quot;")
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>__T__</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;background:#525659;font-family:-apple-system,Segoe UI,Roboto,sans-serif}
#bar{position:sticky;top:0;z-index:5;background:#323639;color:#fff;padding:9px 14px;display:flex;gap:14px;align-items:center;font-size:14px}
#bar b{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#bar a{color:#8ab4f8;text-decoration:none} #wrap{padding:14px 0;text-align:center}
canvas{display:block;margin:0 auto 12px;max-width:100%;box-shadow:0 2px 12px rgba(0,0,0,.5);background:#fff}
#msg{color:#fff;padding:2.5rem;font-size:15px}</style></head>
<body><div id="bar"><b>__T__</b><a href="__U__" download>Download</a></div>
<div id="wrap"><div id="msg">Loading…</div></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
<script>
(function(){
 try{pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';}catch(e){}
 (async function(){
  var wrap=document.getElementById('wrap');
  try{
   var pdf=await pdfjsLib.getDocument('__U__').promise;
   wrap.innerHTML='';
   var ww=Math.min(950, window.innerWidth-20);
   for(var p=1;p<=pdf.numPages;p++){
    var page=await pdf.getPage(p);
    var base=page.getViewport({scale:1});
    var scale=Math.max(0.6, Math.min(2.2, ww/base.width));
    var vp=page.getViewport({scale:scale});
    var c=document.createElement('canvas'); c.width=vp.width; c.height=vp.height;
    wrap.appendChild(c);
    await page.render({canvasContext:c.getContext('2d'), viewport:vp}).promise;
   }
  }catch(e){ wrap.innerHTML='<div id="msg">Couldn\\'t display this file. <a href="__U__" style="color:#8ab4f8">Open the raw PDF</a></div>'; }
 })();
})();
</script></body></html>"""
    html = html.replace("__T__", safe_t).replace("__U__", safe_u)
    return HTMLResponse(content=html)


_NCERT_PDF_RE = re.compile(r'^https://ncert\.nic\.in/textbook/pdf/[a-z0-9]+\.pdf$', re.I)

@app.get("/ncert/pdf", tags=["NCERT"])
def ncert_pdf_proxy(u: str):
    """Proxy an official NCERT chapter PDF so it can be read INSIDE the app.
    NCERT only offers whole-book .zip download links and blocks third-party PDF
    viewers, so we fetch the chapter PDF server-side and stream it same-origin.
    Public content only (no auth needed — an <iframe> can't send a bearer token),
    and locked to official ncert.nic.in chapter-PDF URLs."""
    if not _NCERT_PDF_RE.match(u or ""):
        raise HTTPException(status_code=400, detail="Only official NCERT chapter PDFs can be opened here.")
    import ssl
    _ctx = ssl.create_default_context()
    _ctx.check_hostname = False
    _ctx.verify_mode = ssl.CERT_NONE
    _headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "application/pdf,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://ncert.nic.in/textbook.php",
    }
    data = None
    last_err = ""
    for _url in (u, u.replace("https://", "http://")):   # some NCERT edges only serve http
        try:
            req = _UrlRequest(_url, headers=_headers)
            with urlopen(req, timeout=45, context=_ctx) as resp:
                data = resp.read()
            if data:
                break
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__} {getattr(e, 'code', '')}".strip()
    if not data:
        raise HTTPException(status_code=502,
                            detail=f"Could not fetch the NCERT PDF ({last_err or 'unknown'}). Use 'Open in new tab'.")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": "inline; filename=ncert-chapter.pdf",
                             "Cache-Control": "public, max-age=86400"})


@app.get("/reference-books", tags=["NCERT"])
def reference_books(current_user: DBUser = Depends(get_current_user)):
    """Standard reference books -> subject -> high-yield topics (for grounded generation)."""
    return {"status": "success", "reference_books": syllabus_data.REFERENCE_BOOKS}


@app.get("/subjects", tags=["NCERT"])
def subjects(current_user: DBUser = Depends(get_current_user)):
    """Subjects with their high-yield topics (for the Subjectwise practice tab)."""
    return {"status": "success", "subjects": syllabus_data.SUBJECT_TOPICS}


@app.post("/ncert/generate", tags=["NCERT"])
def ncert_generate(request: NcertGenerateRequest, db: Session = Depends(get_db),
                   current_user: DBUser = Depends(get_current_user)):
    """Generate a ready-to-take, AI-VERIFIED MCQ set from a specific NCERT book + chapter."""
    book = syllabus_data.get_ncert_book(request.book_key)
    if not book:
        raise HTTPException(status_code=404, detail="NCERT book not found")

    # "All chapters" => generate across the whole book (chapter left blank).
    chapter_raw = (request.chapter or "").strip()
    all_chapters = (not chapter_raw) or chapter_raw.lower() in ("all", "all chapters", "__all__")
    if not all_chapters and chapter_raw not in book["chapters"]:
        raise HTTPException(status_code=400, detail="Chapter not found in this book")
    gen_chapter = "" if all_chapters else chapter_raw
    label = "All Chapters" if all_chapters else chapter_raw

    num = max(1, min(int(request.num_questions or 5), 100))
    difficulty = (request.difficulty or "medium").lower()
    qtype = (request.question_type or "all").lower()
    try:
        questions = generate_ncert_mcqs(
            book=book["book"], chapter=gen_chapter,
            subject=book["subject"], num_questions=num, difficulty=difficulty,
            question_type=qtype,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")
    if not questions:
        raise HTTPException(status_code=502, detail="Could not generate verified questions. Please try again.")

    title = f"NCERT • {book['book']} • {label}"
    duration = max(5, len(questions))
    db_test = DBMockTest(
        title=title,
        description=f"AI-verified NCERT MCQs from {book['book']} — {label} ({difficulty})",
        subject=book["subject"],
        total_questions=len(questions),
        duration_minutes=duration,
        user_id=current_user.id,
    )
    db.add(db_test); db.commit(); db.refresh(db_test)
    for q in questions:
        db.add(DBQuestion(
            text=q["text"], option_a=q["option_a"], option_b=q["option_b"],
            option_c=q["option_c"], option_d=q["option_d"],
            correct_answer=q["correct_answer"], explanation=q.get("explanation", ""),
            subject=book["subject"],
            book=book["book"], chapter=(None if all_chapters else chapter_raw),
            topic=q.get("topic") or label,
            difficulty=difficulty, question_type=q.get("question_type", "direct"),
            mock_test_id=db_test.id,
        ))
    db.commit()
    return {
        "status": "success",
        "message": f"Generated {len(questions)} verified NCERT questions",
        "mock_test_id": db_test.id,
        "questions_added": len(questions),
        "duration_minutes": duration,
        "title": title,
    }


def _reuse_pool(db, user_id, subject, topic, difficulty, limit):
    """Pull previously-generated verified questions for this concept that the student
    hasn't answered yet — caching by concept to cut generation cost (roadmap §7)."""
    if limit <= 0:
        return []
    answered = {a.question_id for a in (db.query(DBAnswer.question_id)
                .join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
                .filter(DBTestAttempt.user_id == user_id).all())}
    q = db.query(DBQuestion).filter(DBQuestion.subject == subject)
    if topic:
        q = q.filter(DBQuestion.topic == topic)
    if difficulty:
        q = q.filter(DBQuestion.difficulty == difficulty)
    cands = q.order_by(DBQuestion.id.desc()).limit(400).all()
    seen_text, out = set(), []
    for dq in cands:
        if dq.id in answered or dq.text in seen_text or not dq.correct_answer:
            continue
        seen_text.add(dq.text)
        out.append({"text": dq.text, "option_a": dq.option_a, "option_b": dq.option_b,
                    "option_c": dq.option_c, "option_d": dq.option_d,
                    "correct_answer": dq.correct_answer, "explanation": dq.explanation or "",
                    "topic": dq.topic, "question_type": dq.question_type or "direct"})
        if len(out) >= limit:
            break
    return out

@app.post("/mock-tests/generate-verified/", tags=["Tests"])
def generate_verified_test(request: VerifiedGenerateRequest, db: Session = Depends(get_db),
                           current_user: DBUser = Depends(get_current_user)):
    """Generate an AI-VERIFIED test from a subject/topic (optionally grounded in a book)."""
    num = max(1, min(int(request.num_questions or 5), 100))
    difficulty = (request.difficulty or "medium").lower()
    qtype = (request.question_type or "all").lower()
    subject = request.subject or "General Studies"
    topic = (request.topic or "").strip()
    book = (request.book or "").strip()
    reused = []
    if getattr(request, "reuse", False) and not book:
        try:
            reused = _reuse_pool(db, current_user.id, subject, topic, difficulty, num // 2)
        except Exception:
            reused = []
    gen_needed = num - len(reused)
    source_context = ""
    try:
        if db.query(DBKnowledgeChunk).filter(DBKnowledgeChunk.subject == subject).first():
            source_context = _retrieve_context(db, subject, topic)
    except Exception:
        source_context = ""
    questions = []
    if gen_needed > 0:
        try:
            questions = generate_verified_questions(
                subject=subject, topic=topic, num_questions=gen_needed, difficulty=difficulty, book=book,
                question_type=qtype, source_context=source_context,
            )
        except Exception as e:
            if not reused:
                raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")
    questions = reused + (questions or [])
    if not questions:
        raise HTTPException(status_code=502, detail="Could not generate verified questions. Please try again.")

    label = topic or book or subject
    title = f"Verified • {subject}" + (f" • {label}" if label and label != subject else "")
    duration = max(5, len(questions))
    db_test = DBMockTest(
        title=title, description=f"AI-verified MCQs — {label} ({difficulty})",
        subject=subject, total_questions=len(questions),
        duration_minutes=duration, user_id=current_user.id,
    )
    db.add(db_test); db.commit(); db.refresh(db_test)
    for q in questions:
        db.add(DBQuestion(
            text=q["text"], option_a=q["option_a"], option_b=q["option_b"],
            option_c=q["option_c"], option_d=q["option_d"],
            correct_answer=q["correct_answer"], explanation=q.get("explanation", ""),
            subject=subject, book=book or None, topic=q.get("topic") or topic,
            difficulty=difficulty, question_type=q.get("question_type", "direct"),
            mock_test_id=db_test.id,
        ))
    db.commit()
    return {
        "status": "success", "message": f"Generated {len(questions)} verified questions",
        "mock_test_id": db_test.id, "questions_added": len(questions),
        "duration_minutes": duration, "title": title,
    }


# ── Results ───────────────────────────────────────────────────────────────────
@app.get("/attempts/{attempt_id}/results/", tags=["Results"])
def get_attempt_results(attempt_id: int, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    db_attempt = db.query(DBTestAttempt).filter(DBTestAttempt.id == attempt_id, DBTestAttempt.user_id == current_user.id).first()
    if not db_attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    # Map the user's submitted answers by question, then walk EVERY question in the
    # test so the review (and explanations) covers answered AND skipped questions.
    ans_map = {a.question_id: a for a in db.query(DBAnswer).filter(DBAnswer.test_attempt_id == attempt_id).all()}
    questions = db.query(DBQuestion).filter(DBQuestion.mock_test_id == db_attempt.mock_test_id).order_by(DBQuestion.id).all()
    results = []
    for q in questions:
        ans = ans_map.get(q.id)
        results.append({
            "question_id": q.id, "question_text": q.text,
            "option_a": q.option_a, "option_b": q.option_b, "option_c": q.option_c, "option_d": q.option_d,
            "selected_option": ans.selected_option if ans else None,
            "correct_answer": q.correct_answer,
            "is_correct": bool(ans.is_correct) if ans else False,
            "answered": ans is not None,
            "explanation": q.explanation,
        })
    total = db_attempt.mock_test.total_questions
    return {
        "status": "success", "score": db_attempt.score, "total_questions": total,
        "percentage": round((db_attempt.score / total) * 100, 1) if total else 0,
        "results": results,
    }

@app.get("/my-attempts/", tags=["Results"])
def get_my_attempts(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    attempts = db.query(DBTestAttempt).filter(DBTestAttempt.user_id == current_user.id).order_by(DBTestAttempt.completed_at.desc()).all()
    return {
        "status": "success",
        "attempts": [
            {
                "attempt_id": a.id, "mock_test_id": a.mock_test_id,
                "mock_test_title": a.mock_test.title, "subject": a.mock_test.subject,
                "score": a.score, "total_questions": a.mock_test.total_questions,
                "percentage": round((a.score / a.mock_test.total_questions) * 100, 1) if a.mock_test.total_questions else 0,
                "completed_at": a.completed_at.isoformat() if a.completed_at else None,
            }
            for a in attempts
        ],
    }

# ── Learning Loop: Mistakes · Weak Topics · Spaced Repetition ──────────────────
_OPT_LETTERS = ["A", "B", "C", "D"]

def _opt_text(q, letter):
    if not letter:
        return None
    return getattr(q, "option_" + letter.lower(), None)

def _classify_mistake(ans, q):
    """Heuristic auto-tag for a wrong answer when the student hasn't tagged it."""
    if ans.wrong_reason:
        return ans.wrong_reason
    conf = (ans.confidence or "").lower()
    tt = ans.time_taken or 0
    if conf == "guess":
        return "guess"
    if conf == "sure":
        return "conceptual"        # confidently wrong → a real knowledge gap
    if tt and tt <= 8:
        return "careless"          # very fast + wrong → likely misread/rushed
    return "review"                # default: needs review

@app.get("/me/mistakes", tags=["Learning"])
def my_mistakes(subject: Optional[str] = None, reason: Optional[str] = None,
                confidence: Optional[str] = None, include_resolved: bool = False,
                limit: int = 200, db: Session = Depends(get_db),
                current_user: DBUser = Depends(get_current_user)):
    """Wrong answers, de-duplicated to the most recent attempt per question, with
    filters, resolved-state, community difficulty and bookmark flags."""
    resolved_ids = {r.question_id for r in db.query(DBResolvedMistake).filter(
        DBResolvedMistake.user_id == current_user.id).all()}
    bookmarked_ids = {b.question_id for b in db.query(DBBookmark).filter(
        DBBookmark.user_id == current_user.id).all()}
    rows = (db.query(DBAnswer, DBQuestion, DBTestAttempt)
            .join(DBQuestion, DBAnswer.question_id == DBQuestion.id)
            .join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
            .filter(DBTestAttempt.user_id == current_user.id, DBAnswer.is_correct == False)
            .order_by(DBTestAttempt.completed_at.desc(), DBAnswer.id.desc())
            .all())
    seen = set()
    items = []
    subj_counter = {}
    resolved_count = 0
    for ans, q, att in rows:
        if q.id in seen:
            continue
        seen.add(q.id)
        is_resolved = q.id in resolved_ids
        if is_resolved:
            resolved_count += 1
        # Subject chips count all active (non-resolved) mistakes, independent of filters.
        if not is_resolved:
            s0 = q.subject or "General"
            subj_counter[s0] = subj_counter.get(s0, 0) + 1
        if is_resolved and not include_resolved:
            continue
        if subject and (q.subject or "").lower() != subject.lower():
            continue
        rsn = _classify_mistake(ans, q)
        if reason and rsn != reason.lower():
            continue
        if confidence and (ans.confidence or "").lower() != confidence.lower():
            continue
        items.append({
            "answer_id": ans.id, "question_id": q.id,
            "question_text": q.text,
            "options": {l: _opt_text(q, l) for l in _OPT_LETTERS},
            "your_answer": ans.selected_option,
            "your_answer_text": _opt_text(q, ans.selected_option),
            "correct_answer": q.correct_answer,
            "correct_answer_text": _opt_text(q, q.correct_answer),
            "explanation": q.explanation or "",
            "subject": q.subject or "General", "topic": q.topic or "", "book": q.book or "",
            "confidence": ans.confidence, "time_taken": ans.time_taken,
            "reason": rsn, "reason_is_auto": not bool(ans.wrong_reason),
            "resolved": is_resolved, "bookmarked": q.id in bookmarked_ids,
            "completed_at": att.completed_at.isoformat() if att.completed_at else None,
        })
        if len(items) >= max(1, min(limit, 500)):
            break
    ids = [it["question_id"] for it in items]
    if ids:
        comm = {}
        for qid, isc in db.query(DBAnswer.question_id, DBAnswer.is_correct).filter(
                DBAnswer.question_id.in_(ids)).all():
            d = comm.setdefault(qid, [0, 0])
            d[1] += 1
            d[0] += 1 if isc else 0
        for it in items:
            d = comm.get(it["question_id"])
            it["community_accuracy"] = round(d[0] / d[1] * 100) if d and d[1] else None
            it["community_attempts"] = d[1] if d else 0
    return {"status": "success", "count": len(items), "resolved_total": resolved_count,
            "by_subject": [{"subject": k, "count": v} for k, v in sorted(subj_counter.items(), key=lambda x: -x[1])],
            "mistakes": items}

@app.post("/me/mistakes/{question_id}/resolve", tags=["Learning"])
def resolve_mistake(question_id: int, db: Session = Depends(get_db),
                    current_user: DBUser = Depends(get_current_user)):
    """Toggle a mistake as understood/resolved (hidden from the active list)."""
    existing = db.query(DBResolvedMistake).filter(
        DBResolvedMistake.user_id == current_user.id,
        DBResolvedMistake.question_id == question_id).first()
    if existing:
        db.delete(existing); db.commit()
        return {"status": "success", "resolved": False}
    db.add(DBResolvedMistake(user_id=current_user.id, question_id=question_id)); db.commit()
    return {"status": "success", "resolved": True}

@app.post("/me/mistakes/{question_id}/revise", tags=["Learning"])
def add_mistake_to_revision(question_id: int, db: Session = Depends(get_db),
                            current_user: DBUser = Depends(get_current_user)):
    """Manually push a mistake into the spaced-repetition queue, due now."""
    if not db.query(DBQuestion).filter(DBQuestion.id == question_id).first():
        raise HTTPException(status_code=404, detail="Question not found")
    _schedule_review_on_wrong(db, current_user.id, question_id)
    db.commit()
    return {"status": "success", "scheduled": True}

@app.get("/me/revision/calendar", tags=["Learning"])
def revision_calendar(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Day-by-day spaced-repetition schedule for the next 14 days."""
    now = datetime.datetime.utcnow()
    td = datetime.timedelta
    items = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == current_user.id, DBReviewItem.mastered == False).all()
    overdue = 0
    perday = {}
    for it in items:
        if it.next_review is None:
            continue
        d = (it.next_review.date() - now.date()).days
        if d < 0:
            overdue += 1
        elif d <= 14:
            key = it.next_review.date().isoformat()
            perday[key] = perday.get(key, 0) + 1
    days = []
    for i in range(0, 14):
        dt = (now.date() + td(i))
        days.append({"date": dt.isoformat(), "label": dt.strftime("%a %d %b"),
                     "count": perday.get(dt.isoformat(), 0) + (overdue if i == 0 else 0),
                     "is_today": i == 0})
    return {"status": "success", "overdue": overdue, "days": days}

@app.put("/me/mistakes/{answer_id}/reason", tags=["Learning"])
def tag_mistake_reason(answer_id: int, payload: WrongReasonIn,
                       db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    ans = (db.query(DBAnswer).join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
           .filter(DBAnswer.id == answer_id, DBTestAttempt.user_id == current_user.id).first())
    if not ans:
        raise HTTPException(status_code=404, detail="Answer not found")
    reason = (payload.reason or "").lower().strip()
    if reason not in ("conceptual", "factual", "careless", "misread", "guess"):
        raise HTTPException(status_code=400, detail="Invalid reason")
    ans.wrong_reason = reason
    db.commit()
    return {"status": "success", "answer_id": answer_id, "reason": reason}

@app.get("/me/weak-topics", tags=["Learning"])
def my_weak_topics(min_attempts: int = 3, db: Session = Depends(get_db),
                   current_user: DBUser = Depends(get_current_user)):
    """Per subject+topic accuracy across all of the student's answers; weakest first."""
    rows = (db.query(DBAnswer, DBQuestion)
            .join(DBQuestion, DBAnswer.question_id == DBQuestion.id)
            .join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
            .filter(DBTestAttempt.user_id == current_user.id)
            .all())
    agg = {}
    subj_agg = {}
    for ans, q in rows:
        subj = q.subject or "General"
        topic = q.topic or "General"
        key = (subj, topic)
        a = agg.setdefault(key, {"attempted": 0, "correct": 0})
        a["attempted"] += 1
        a["correct"] += 1 if ans.is_correct else 0
        sa = subj_agg.setdefault(subj, {"attempted": 0, "correct": 0})
        sa["attempted"] += 1
        sa["correct"] += 1 if ans.is_correct else 0
    topics = []
    for (subj, topic), a in agg.items():
        if a["attempted"] < max(1, min_attempts):
            continue
        acc = round(a["correct"] / a["attempted"] * 100, 1)
        topics.append({"subject": subj, "topic": topic, "attempted": a["attempted"],
                       "correct": a["correct"], "accuracy": acc})
    topics.sort(key=lambda x: (x["accuracy"], -x["attempted"]))
    subjects = []
    for subj, a in subj_agg.items():
        acc = round(a["correct"] / a["attempted"] * 100, 1) if a["attempted"] else 0
        subjects.append({"subject": subj, "attempted": a["attempted"],
                         "correct": a["correct"], "accuracy": acc})
    subjects.sort(key=lambda x: x["accuracy"])
    return {"status": "success", "weak_topics": topics[:12], "subjects": subjects}

@app.get("/me/revision/due", tags=["Learning"])
def revision_due(include_upcoming: bool = False, db: Session = Depends(get_db),
                 current_user: DBUser = Depends(get_current_user)):
    """Questions due for spaced-repetition review right now."""
    now = datetime.datetime.utcnow()
    q = db.query(DBReviewItem).filter(DBReviewItem.user_id == current_user.id,
                                      DBReviewItem.mastered == False)
    due_items = q.filter(DBReviewItem.next_review <= now).order_by(DBReviewItem.next_review.asc()).all()
    total_scheduled = q.count()
    mastered_count = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == current_user.id, DBReviewItem.mastered == True).count()
    questions = []
    for it in due_items:
        dq = db.query(DBQuestion).filter(DBQuestion.id == it.question_id).first()
        if not dq:
            continue
        questions.append({
            "review_id": it.id, "question_id": dq.id, "text": dq.text,
            "option_a": dq.option_a, "option_b": dq.option_b,
            "option_c": dq.option_c, "option_d": dq.option_d,
            "subject": dq.subject or "General", "topic": dq.topic or "",
            "repetitions": it.repetitions or 0,
        })
    return {"status": "success", "due_count": len(questions),
            "total_scheduled": total_scheduled, "mastered": mastered_count,
            "questions": questions}

@app.post("/me/revision/submit", tags=["Learning"])
def revision_submit(answers: List[RevisionAnswer], db: Session = Depends(get_db),
                    current_user: DBUser = Depends(get_current_user)):
    """Grade a revision round and advance each question's spaced-repetition schedule."""
    correct = 0
    results = []
    for ans in answers:
        dq = db.query(DBQuestion).filter(DBQuestion.id == ans.question_id).first()
        if not dq:
            continue
        is_correct = dq.correct_answer == (ans.selected_option or "").upper()
        if is_correct:
            correct += 1
        _advance_review(db, current_user.id, dq.id, is_correct)
        results.append({
            "question_id": dq.id, "is_correct": is_correct,
            "correct_answer": dq.correct_answer,
            "your_answer": (ans.selected_option or "").upper(),
            "explanation": dq.explanation or "",
        })
    db.commit()
    return {"status": "success", "correct": correct, "total": len(results), "results": results}

@app.get("/me/learning/summary", tags=["Learning"])
def learning_summary(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Small counters for the dashboard learning-loop cards."""
    now = datetime.datetime.utcnow()
    mistakes = (db.query(DBAnswer.question_id)
                .join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
                .filter(DBTestAttempt.user_id == current_user.id, DBAnswer.is_correct == False)
                .distinct().count())
    due = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == current_user.id, DBReviewItem.mastered == False,
        DBReviewItem.next_review <= now).count()
    mastered = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == current_user.id, DBReviewItem.mastered == True).count()
    return {"status": "success", "mistakes": mistakes, "due_revisions": due, "mastered": mastered}

@app.post("/me/mistakes/{question_id}/diagnose", tags=["Learning"])
def diagnose_my_mistake(question_id: int, db: Session = Depends(get_db),
                        current_user: DBUser = Depends(get_current_user)):
    """AI, confidence-aware post-mortem of one wrong answer the student gave."""
    ans = (db.query(DBAnswer).join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
           .filter(DBTestAttempt.user_id == current_user.id,
                   DBAnswer.question_id == question_id, DBAnswer.is_correct == False)
           .order_by(DBAnswer.id.desc()).first())
    if not ans:
        raise HTTPException(status_code=404, detail="No wrong answer found for this question")
    q = db.query(DBQuestion).filter(DBQuestion.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    try:
        text = diagnose_mistake(
            question=q.text,
            options={l: getattr(q, "option_" + l.lower(), "") for l in ["A", "B", "C", "D"]},
            correct_letter=q.correct_answer, chosen_letter=ans.selected_option,
            confidence=ans.confidence or "", subject=q.subject or "", topic=q.topic or "",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Diagnosis error: {str(e)}")
    return {"status": "success", "question_id": question_id, "diagnosis": text}

@app.get("/me/insights", tags=["Learning"])
def my_insights(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Confidence calibration + mistake-pattern intelligence from captured data."""
    rows = (db.query(DBAnswer, DBQuestion)
            .join(DBQuestion, DBAnswer.question_id == DBQuestion.id)
            .join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
            .filter(DBTestAttempt.user_id == current_user.id)
            .all())
    total = len(rows)
    # Confidence calibration: per confidence level, correct vs wrong.
    conf = {c: {"correct": 0, "wrong": 0} for c in ["sure", "unsure", "guess", "untagged"]}
    reason_counts = {}
    careless = 0          # fast (<=8s) AND wrong
    fast_total = 0
    overconfident = 0     # sure but wrong
    lucky = 0             # guess but correct
    underselling = 0      # unsure but correct
    times = []
    for ans, q in rows:
        c = (ans.confidence or "untagged").lower()
        if c not in conf:
            c = "untagged"
        if ans.is_correct:
            conf[c]["correct"] += 1
        else:
            conf[c]["wrong"] += 1
        if c == "sure" and not ans.is_correct:
            overconfident += 1
        if c == "guess" and ans.is_correct:
            lucky += 1
        if c == "unsure" and ans.is_correct:
            underselling += 1
        if ans.time_taken is not None:
            times.append(ans.time_taken)
            if ans.time_taken <= 8:
                fast_total += 1
                if not ans.is_correct:
                    careless += 1
        if not ans.is_correct:
            r = ans.wrong_reason or _classify_mistake(ans, q)
            reason_counts[r] = reason_counts.get(r, 0) + 1
    # Guess quality: accuracy on guessed questions vs the 25% random baseline.
    g = conf["guess"]
    guess_attempted = g["correct"] + g["wrong"]
    guess_acc = round(g["correct"] / guess_attempted * 100, 1) if guess_attempted else None
    def _acc(d):
        n = d["correct"] + d["wrong"]
        return round(d["correct"] / n * 100, 1) if n else None
    calibration = [{"confidence": c, "correct": conf[c]["correct"], "wrong": conf[c]["wrong"],
                    "attempted": conf[c]["correct"] + conf[c]["wrong"], "accuracy": _acc(conf[c])}
                   for c in ["sure", "unsure", "guess", "untagged"]]
    avg_time = round(sum(times) / len(times), 1) if times else None
    return {
        "status": "success", "total_answers": total,
        "calibration": calibration,
        "flags": {
            "overconfident": overconfident,   # confidently wrong → real gaps
            "lucky_guesses": lucky,           # right by luck → don't trust these
            "underselling": underselling,     # unsure but right → trust yourself more
            "careless": careless,             # fast & wrong → slow down / read fully
        },
        "guess_quality": {"attempted": guess_attempted, "accuracy": guess_acc, "baseline": 25.0},
        "reason_breakdown": [{"reason": k, "count": v} for k, v in sorted(reason_counts.items(), key=lambda x: -x[1])],
        "avg_time_per_q": avg_time,
        "fast_answers": fast_total,
    }


# ── Phase 2: Coverage · Revision Plan · Readiness ─────────────────────────────
# Rough UPSC Prelims weight per subject (1=low, 2=med, 3=high), keyword-matched.
_SUBJECT_WEIGHTS = [
    (("polity", "constitution", "governance"), 3),
    (("economy", "economic"), 3),
    (("environment", "ecology", "biodiversity", "climate"), 3),
    (("geography",), 3),
    (("history", "art", "culture", "ancient", "medieval", "modern"), 3),
    (("current affairs", "current"), 3),
    (("science", "technology"), 2),
    (("international", "relations"), 1),
]

def _subject_weight(name):
    n = (name or "").lower()
    for keys, w in _SUBJECT_WEIGHTS:
        if any(k in n for k in keys):
            return w
    return 2

def _coverage_status(attempted, accuracy, days_since):
    if not attempted:
        return "untouched"
    if days_since is not None and days_since > 45:
        return "needs_revision"
    if accuracy >= 75 and attempted >= 15:
        return "strong"
    if attempted >= 15:
        return "covered"
    return "in_progress"

def _answer_rows(db, user_id):
    return (db.query(DBAnswer, DBQuestion, DBTestAttempt)
            .join(DBQuestion, DBAnswer.question_id == DBQuestion.id)
            .join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
            .filter(DBTestAttempt.user_id == user_id)
            .all())

@app.get("/me/coverage", tags=["Coverage"])
def my_coverage(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """How much of the syllabus the student has actually practiced, and how well."""
    now = datetime.datetime.utcnow()
    rows = _answer_rows(db, current_user.id)
    by_subject, by_book = {}, {}
    for ans, q, att in rows:
        subj = q.subject or "General"
        s = by_subject.setdefault(subj, {"attempted": 0, "correct": 0, "topics": set(), "last": None})
        s["attempted"] += 1
        s["correct"] += 1 if ans.is_correct else 0
        if q.topic:
            s["topics"].add(q.topic)
        if att.completed_at and (s["last"] is None or att.completed_at > s["last"]):
            s["last"] = att.completed_at
        if q.book:
            b = by_book.setdefault(q.book, {"subject": subj, "attempted": 0, "correct": 0, "last": None})
            b["attempted"] += 1
            b["correct"] += 1 if ans.is_correct else 0
            if att.completed_at and (b["last"] is None or att.completed_at > b["last"]):
                b["last"] = att.completed_at
    canon = {item["subject"]: len(item.get("topics", [])) for item in syllabus_data.SUBJECT_TOPICS}
    subjects, matched_canon = [], set()
    for subj, s in by_subject.items():
        acc = round(s["correct"] / s["attempted"] * 100, 1) if s["attempted"] else 0
        days = (now - s["last"]).days if s["last"] else None
        tt = None
        for cs, ct in canon.items():
            cl, sl = cs.lower(), subj.lower()
            if cl == sl or cl in sl or sl in cl:
                tt = ct
                matched_canon.add(cs)
                break
        topics_touched = len(s["topics"])
        cov_pct = round(min(topics_touched, tt) / tt * 100, 1) if tt else None
        subjects.append({
            "subject": subj, "attempted": s["attempted"], "accuracy": acc,
            "topics_touched": topics_touched, "total_topics": tt, "coverage_pct": cov_pct,
            "days_since": days, "weight": _subject_weight(subj),
            "status": _coverage_status(s["attempted"], acc, days),
        })
    subjects.sort(key=lambda x: (-x["weight"], -x["attempted"]))
    gaps = [{"subject": cs, "total_topics": ct, "weight": _subject_weight(cs)}
            for cs, ct in canon.items() if cs not in matched_canon]
    gaps.sort(key=lambda x: -x["weight"])
    ncert_names = {b["book"] for b in syllabus_data.NCERT_BOOKS}
    ref_names = {b["book"] for b in syllabus_data.REFERENCE_BOOKS}
    books = []
    for bk, b in by_book.items():
        acc = round(b["correct"] / b["attempted"] * 100, 1) if b["attempted"] else 0
        days = (now - b["last"]).days if b["last"] else None
        kind = "NCERT" if bk in ncert_names else ("Reference" if bk in ref_names else "Other")
        books.append({"book": bk, "subject": b["subject"], "attempted": b["attempted"],
                      "accuracy": acc, "days_since": days, "kind": kind,
                      "status": _coverage_status(b["attempted"], acc, days)})
    books.sort(key=lambda x: -x["attempted"])
    practiced = set(by_book.keys())
    return {
        "status": "success", "subjects": subjects, "gaps": gaps, "books": books,
        "summary": {
            "subjects_practiced": len(subjects),
            "canon_subjects": len(canon), "canon_practiced": len(matched_canon),
            "ncert_practiced": len(practiced & ncert_names), "ncert_total": len(ncert_names),
            "ref_practiced": len(practiced & ref_names), "ref_total": len(ref_names),
        },
    }

@app.get("/me/revision-plan", tags=["Coverage"])
def my_revision_plan(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Spaced-repetition calendar + a priority ranking of what to revise first."""
    now = datetime.datetime.utcnow()
    items = db.query(DBReviewItem).filter(DBReviewItem.user_id == current_user.id).all()
    overdue = today = this_week = later = mastered = 0
    for it in items:
        if it.mastered:
            mastered += 1
            continue
        if it.next_review is None:
            continue
        d = (it.next_review.date() - now.date()).days
        if d < 0:
            overdue += 1
        elif d == 0:
            today += 1
        elif d <= 7:
            this_week += 1
        else:
            later += 1
    # Priority = proficiency gap + forgetting + UPSC weight, per subject.
    rows = _answer_rows(db, current_user.id)
    agg = {}
    for ans, q, att in rows:
        subj = q.subject or "General"
        a = agg.setdefault(subj, {"attempted": 0, "correct": 0, "last": None})
        a["attempted"] += 1
        a["correct"] += 1 if ans.is_correct else 0
        if att.completed_at and (a["last"] is None or att.completed_at > a["last"]):
            a["last"] = att.completed_at
    priorities = []
    for subj, a in agg.items():
        if a["attempted"] < 3:
            continue
        acc = a["correct"] / a["attempted"] * 100
        days = (now - a["last"]).days if a["last"] else None
        weight = _subject_weight(subj)
        prof_gap = (100 - acc) / 100.0
        forgetting = min((days or 0) / 45.0, 1.0) if days is not None else 0.3
        score = round((0.4 * prof_gap + 0.35 * forgetting + 0.25 * ((weight - 1) / 2.0)) * 100, 1)
        priorities.append({"subject": subj, "score": score, "accuracy": round(acc, 1),
                           "days_since": days, "weight": weight, "attempted": a["attempted"]})
    priorities.sort(key=lambda x: -x["score"])
    return {
        "status": "success",
        "calendar": {"overdue": overdue, "today": today, "this_week": this_week,
                     "later": later, "mastered": mastered, "due_now": overdue + today},
        "priorities": priorities[:8],
    }

@app.get("/me/readiness", tags=["Coverage"])
def my_readiness(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """An honest 'if the exam were tomorrow' snapshot — a score RANGE, never a cutoff."""
    now = datetime.datetime.utcnow()
    rows = _answer_rows(db, current_user.id)
    total = len(rows)
    correct = sum(1 for ans, q, att in rows if ans.is_correct)
    wrong = total - correct
    overall_acc = round(correct / total * 100, 1) if total else 0
    # Score range from full attempts' net %, scaled to the 200-mark paper.
    attempts = db.query(DBTestAttempt).filter(DBTestAttempt.user_id == current_user.id).all()
    net_pcts = []
    for a in attempts:
        tq = a.mock_test.total_questions if a.mock_test else 0
        if not tq:
            continue
        att_correct = a.score or 0
        attempted = db.query(DBAnswer).filter(DBAnswer.test_attempt_id == a.id).count()
        att_wrong = max(0, attempted - att_correct)
        net = att_correct * 2.0 - att_wrong * (2.0 / 3.0)
        net_pcts.append(net / (tq * 2.0) * 100)
    score_range = None
    if net_pcts:
        avg = sum(net_pcts) / len(net_pcts)
        if len(net_pcts) > 1:
            var = sum((x - avg) ** 2 for x in net_pcts) / (len(net_pcts) - 1)
            spread = max(8.0, var ** 0.5)
        else:
            spread = 15.0
        center = avg / 100.0 * 200.0
        margin = spread / 100.0 * 200.0
        score_range = {"low": max(0, round(center - margin)), "high": min(200, round(center + margin)),
                       "mid": round(center), "tests_used": len(net_pcts)}
    # Per-subject strengths / focus areas.
    by_subject = {}
    for ans, q, att in rows:
        subj = q.subject or "General"
        s = by_subject.setdefault(subj, {"attempted": 0, "correct": 0})
        s["attempted"] += 1
        s["correct"] += 1 if ans.is_correct else 0
    strengths, focus = [], []
    for subj, s in by_subject.items():
        if s["attempted"] < 5:
            continue
        acc = round(s["correct"] / s["attempted"] * 100, 1)
        entry = {"subject": subj, "accuracy": acc, "attempted": s["attempted"], "weight": _subject_weight(subj)}
        if acc >= 65:
            strengths.append(entry)
        elif acc < 50:
            focus.append(entry)
    strengths.sort(key=lambda x: -x["accuracy"])
    focus.sort(key=lambda x: (x["accuracy"], -x["weight"]))
    # Readiness band from overall net %.
    net_total = correct * 2.0 - wrong * (2.0 / 3.0)
    net_pct = round(net_total / (total * 2.0) * 100, 1) if total else 0
    if net_pct >= 55:
        band = "Strong"
    elif net_pct >= 45:
        band = "Approaching"
    elif net_pct >= 33:
        band = "Developing"
    else:
        band = "Early"
    due_now = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == current_user.id, DBReviewItem.mastered == False,
        DBReviewItem.next_review <= now).count()
    return {
        "status": "success",
        "has_data": total > 0,
        "total_answered": total, "overall_accuracy": overall_acc, "net_pct": net_pct,
        "band": band, "score_range": score_range,
        "strengths": strengths[:5], "focus_areas": focus[:5],
        "due_now": due_now,
        "caveat": "A rough estimate from your own practice so far — not a prediction of the official cutoff.",
    }


# ── Phase 3: Exam Simulator (mock composer) ───────────────────────────────────
class SimulatorCompose(BaseModel):
    mode: Optional[str] = "balanced"       # balanced | weak | year
    num_questions: Optional[int] = 100
    year: Optional[str] = None
    duration_minutes: Optional[int] = None

@app.post("/me/simulator/compose", tags=["Simulator"])
def simulator_compose(req: SimulatorCompose, db: Session = Depends(get_db),
                      current_user: DBUser = Depends(get_current_user)):
    """Assemble a full-length exam-simulation paper from the VERIFIED PYQ bank.
    Modes: balanced (natural subject mix), weak (60% from your weak subjects),
    year (a specific past paper). Real exam questions only — no AI generation."""
    mode = (req.mode or "balanced").lower()
    num = max(5, min(int(req.num_questions or 100), 150))
    pool = PYQ_QUESTIONS
    if not pool:
        raise HTTPException(status_code=503, detail="Question bank is unavailable.")

    if mode == "year" and req.year:
        yr = str(req.year).strip()
        ypool = [q for q in pool if str(q.get("year")) == yr]
        if not ypool:
            raise HTTPException(status_code=404, detail="No questions for that year.")
        selected = random.sample(ypool, min(num, len(ypool)))
    elif mode == "weak":
        rows = _answer_rows(db, current_user.id)
        agg = {}
        for ans, q, att in rows:
            s = q.subject or "General"
            a = agg.setdefault(s, {"a": 0, "c": 0})
            a["a"] += 1
            a["c"] += 1 if ans.is_correct else 0
        weak = {s for s, a in agg.items() if a["a"] >= 3 and (a["c"] / a["a"] * 100) < 55}
        weak_pool = [q for q in pool if q.get("subject") in weak]
        rest_pool = [q for q in pool if q.get("subject") not in weak]
        target_weak = int(num * 0.6)
        sel_weak = random.sample(weak_pool, min(target_weak, len(weak_pool))) if weak_pool else []
        remaining = num - len(sel_weak)
        sel_rest = random.sample(rest_pool, min(remaining, len(rest_pool))) if rest_pool else []
        selected = sel_weak + sel_rest
        random.shuffle(selected)
        if not selected:
            selected = random.sample(pool, min(num, len(pool)))
    else:
        mode = "balanced"
        selected = random.sample(pool, min(num, len(pool)))

    dist = {}
    for q in selected:
        s = q.get("subject") or "General"
        dist[s] = dist.get(s, 0) + 1
    duration = req.duration_minutes or max(10, round(len(selected) * 1.2))
    title = "🧪 Exam Simulator • " + mode.title() + (f" • {req.year}" if mode == "year" and req.year else "")
    db_test = DBMockTest(
        title=title, description="Full-length exam simulation (verified PYQs)",
        subject="UPSC Prelims (Mixed)", total_questions=len(selected),
        duration_minutes=duration, user_id=current_user.id,
    )
    db.add(db_test); db.commit(); db.refresh(db_test)
    for q in selected:
        db.add(DBQuestion(
            text=q["text"], option_a=q["option_a"], option_b=q["option_b"],
            option_c=q["option_c"], option_d=q["option_d"],
            correct_answer=q["correct_answer"], explanation=q.get("explanation", ""),
            subject=q.get("subject"), mock_test_id=db_test.id,
        ))
    db.commit()
    return {
        "status": "success", "mock_test_id": db_test.id, "questions": len(selected),
        "duration_minutes": duration, "mode": mode,
        "distribution": [{"subject": k, "count": v} for k, v in sorted(dist.items(), key=lambda x: -x[1])],
    }

@app.get("/me/simulator/history", tags=["Simulator"])
def simulator_history(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Net-score across past simulator mocks — your improvement curve over attempts."""
    attempts = (db.query(DBTestAttempt).join(DBMockTest, DBTestAttempt.mock_test_id == DBMockTest.id)
                .filter(DBTestAttempt.user_id == current_user.id,
                        DBMockTest.title.like("%Exam Simulator%"))
                .order_by(DBTestAttempt.completed_at.asc()).all())
    hist = []
    for a in attempts:
        tq = a.mock_test.total_questions if a.mock_test else 0
        if not tq:
            continue
        c = a.score or 0
        attempted = db.query(DBAnswer).filter(DBAnswer.test_attempt_id == a.id).count()
        w = max(0, attempted - c)
        net = c * 2 - w * (2 / 3)
        hist.append({"attempt_id": a.id, "date": a.completed_at.isoformat() if a.completed_at else None,
                     "net": round(net, 1), "net_pct": round(net / (tq * 2) * 100, 1),
                     "score": c, "total": tq, "attempted": attempted})
    return {"status": "success", "count": len(hist), "history": hist}


# ── Phase 3 follow-ups: War Room + Adaptive Difficulty ────────────────────────
def _net_band(net_pct):
    if net_pct >= 55:
        return "Strong"
    if net_pct >= 45:
        return "Approaching"
    if net_pct >= 33:
        return "Developing"
    return "Early"

@app.get("/me/warroom", tags=["Coverage"])
def warroom(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Final-stretch command center: countdown, readiness, focus fire, and a plan."""
    now = datetime.datetime.utcnow()
    prof = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == current_user.id).first()
    days_to_exam, exam_label, target_year = None, None, None
    if prof and prof.target_year and str(prof.target_year).strip().isdigit():
        yr = int(prof.target_year)
        target_year = yr
        try:
            exam_date = datetime.date(yr, 5, 25)
            delta = (exam_date - now.date()).days
            if delta >= 0:
                days_to_exam = delta
                exam_label = f"~25 May {yr} (Prelims, approx.)"
        except Exception:
            pass
    rows = _answer_rows(db, current_user.id)
    total = len(rows)
    correct = sum(1 for ans, q, att in rows if ans.is_correct)
    wrong = total - correct
    net_pct = round((correct * 2 - wrong * (2 / 3)) / (total * 2) * 100, 1) if total else 0
    by_sub = {}
    for ans, q, att in rows:
        s = q.subject or "General"
        d = by_sub.setdefault(s, {"a": 0, "c": 0})
        d["a"] += 1
        d["c"] += 1 if ans.is_correct else 0
    focus = []
    for s, d in by_sub.items():
        if d["a"] < 3:
            continue
        acc = round(d["c"] / d["a"] * 100, 1)
        if acc < 60:
            focus.append({"subject": s, "accuracy": acc, "weight": _subject_weight(s), "attempted": d["a"]})
    focus.sort(key=lambda x: (x["accuracy"], -x["weight"]))
    due = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == current_user.id, DBReviewItem.mastered == False,
        DBReviewItem.next_review <= now).count()
    mistakes = (db.query(DBAnswer.question_id)
                .join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
                .filter(DBTestAttempt.user_id == current_user.id, DBAnswer.is_correct == False)
                .distinct().count())
    mastered = db.query(DBReviewItem).filter(
        DBReviewItem.user_id == current_user.id, DBReviewItem.mastered == True).count()
    return {
        "status": "success", "has_data": total > 0,
        "days_to_exam": days_to_exam, "exam_label": exam_label, "target_year": target_year,
        "net_pct": net_pct, "band": _net_band(net_pct),
        "focus": focus[:5], "due_revisions": due, "mistakes": mistakes, "mastered": mastered,
    }

@app.get("/me/adaptive/level", tags=["Coverage"])
def adaptive_level(subject: Optional[str] = None, topic: Optional[str] = None,
                   db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Recommend a difficulty for the next drill from rolling accuracy. With no
    subject, it picks the student's weakest subject to target."""
    rows = _answer_rows(db, current_user.id)
    chosen_subject, chosen_topic = subject, topic
    c = a = 0
    if subject:
        for ans, q, att in rows:
            if (q.subject or "") == subject and (not topic or (q.topic or "") == topic):
                a += 1
                c += 1 if ans.is_correct else 0
    else:
        by_sub = {}
        for ans, q, att in rows:
            s = q.subject or "General"
            d = by_sub.setdefault(s, {"a": 0, "c": 0})
            d["a"] += 1
            d["c"] += 1 if ans.is_correct else 0
        cand = [(s, d) for s, d in by_sub.items() if d["a"] >= 3]
        if cand:
            cand.sort(key=lambda x: x[1]["c"] / x[1]["a"])
            chosen_subject = cand[0][0]
            c, a = cand[0][1]["c"], cand[0][1]["a"]
    acc = round(c / a * 100, 1) if a else None
    if not a or a < 3 or acc is None:
        level, reason = "medium", "Not enough history yet — starting at medium difficulty."
    elif acc < 45:
        level, reason = "easy", f"You're at {acc}% here — locking in fundamentals with easier questions first."
    elif acc < 72:
        level, reason = "medium", f"You're at {acc}% — medium difficulty to push you upward."
    else:
        level, reason = "hard", f"Strong at {acc}% — stepping up to hard, exam-tough questions."
    return {"status": "success", "subject": chosen_subject, "topic": chosen_topic,
            "accuracy": acc, "attempted": a, "level": level, "reason": reason}

@app.get("/me/trends", tags=["Coverage"])
def my_trends(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """Progress over time: net-score trajectory, study streak, weekly activity, subject momentum."""
    from collections import Counter
    now = datetime.datetime.utcnow()
    td = datetime.timedelta
    rows = _answer_rows(db, current_user.id)
    by_att, answer_dates, subj_chrono = {}, [], {}
    for ans, q, att in rows:
        a = by_att.setdefault(att.id, {"att": att, "c": 0, "n": 0})
        a["c"] += 1 if ans.is_correct else 0
        a["n"] += 1
        if att.completed_at:
            answer_dates.append(att.completed_at.date())
            subj_chrono.setdefault(q.subject or "General", []).append((att.completed_at, ans.is_correct))
    series = []
    for aid, a in by_att.items():
        att = a["att"]; n = a["n"]; c = a["c"]; wrong = n - c
        total = att.mock_test.total_questions if att.mock_test else n
        net_pct = round((c * 2 - wrong * (2 / 3)) / (total * 2) * 100, 1) if total else 0
        series.append({
            "date": att.completed_at.isoformat() if att.completed_at else None,
            "ts": att.completed_at.timestamp() if att.completed_at else 0,
            "net_pct": net_pct, "accuracy": round(c / n * 100, 1) if n else 0,
            "score": c, "attempted": n,
            "title": att.mock_test.title if att.mock_test else "Test",
        })
    series.sort(key=lambda x: x["ts"])
    nets = [s["net_pct"] for s in series]
    improvement = None
    if len(nets) >= 4:
        k = max(1, len(nets) // 3)
        improvement = {"early": round(sum(nets[:k]) / k, 1), "recent": round(sum(nets[-k:]) / k, 1)}
    dayset = sorted(set(answer_dates))
    cur = 0
    if dayset:
        s = set(dayset)
        if dayset[-1] in (now.date(), now.date() - td(1)):
            check = dayset[-1]
            while check in s:
                cur += 1; check = check - td(1)
    longest = run = 0; prev = None
    for d in dayset:
        run = run + 1 if (prev is not None and (d - prev).days == 1) else 1
        longest = max(longest, run); prev = d
    cnt = Counter(answer_dates)
    weekly = [{"date": (now.date() - td(i)).isoformat(), "count": cnt.get(now.date() - td(i), 0)} for i in range(13, -1, -1)]
    subj_trend = []
    for s, lst in subj_chrono.items():
        if len(lst) < 6:
            continue
        lst.sort(key=lambda x: x[0])
        half = len(lst) // 2
        old, new = lst[:half], lst[half:]
        oacc = round(sum(1 for _, c in old if c) / len(old) * 100, 1)
        nacc = round(sum(1 for _, c in new if c) / len(new) * 100, 1)
        subj_trend.append({"subject": s, "old": oacc, "recent": nacc, "delta": round(nacc - oacc, 1)})
    subj_trend.sort(key=lambda x: -abs(x["delta"]))
    return {
        "status": "success", "series": series[-30:], "improvement": improvement,
        "streak": {"current": cur, "longest": longest, "active_days": len(dayset)},
        "weekly": weekly, "subject_trend": subj_trend[:8], "total_tests": len(series),
    }


# ── Smarter engine: flags · bookmarks · resolved · item difficulty ────────────
class FlagIn(BaseModel):
    reason: Optional[str] = "other"
    note: Optional[str] = None

@app.post("/me/questions/{question_id}/flag", tags=["Learning"])
def flag_question(question_id: int, payload: FlagIn, db: Session = Depends(get_db),
                  current_user: DBUser = Depends(get_current_user)):
    if not db.query(DBQuestion).filter(DBQuestion.id == question_id).first():
        raise HTTPException(status_code=404, detail="Question not found")
    reason = (payload.reason or "other").lower()
    if reason not in ("wrong_answer", "unclear", "wrong_subject", "outdated", "other"):
        reason = "other"
    existing = db.query(DBQuestionFlag).filter(
        DBQuestionFlag.user_id == current_user.id, DBQuestionFlag.question_id == question_id).first()
    if existing:
        existing.reason = reason; existing.note = (payload.note or "")[:500]
    else:
        db.add(DBQuestionFlag(user_id=current_user.id, question_id=question_id,
                              reason=reason, note=(payload.note or "")[:500]))
    db.commit()
    return {"status": "success", "question_id": question_id, "reason": reason}

@app.post("/me/bookmarks/{question_id}", tags=["Learning"])
def toggle_bookmark(question_id: int, db: Session = Depends(get_db),
                    current_user: DBUser = Depends(get_current_user)):
    if not db.query(DBQuestion).filter(DBQuestion.id == question_id).first():
        raise HTTPException(status_code=404, detail="Question not found")
    bm = db.query(DBBookmark).filter(
        DBBookmark.user_id == current_user.id, DBBookmark.question_id == question_id).first()
    if bm:
        db.delete(bm); db.commit()
        return {"status": "success", "bookmarked": False}
    db.add(DBBookmark(user_id=current_user.id, question_id=question_id)); db.commit()
    return {"status": "success", "bookmarked": True}

@app.get("/me/bookmarks", tags=["Learning"])
def list_bookmarks(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    bms = (db.query(DBBookmark, DBQuestion).join(DBQuestion, DBBookmark.question_id == DBQuestion.id)
           .filter(DBBookmark.user_id == current_user.id).order_by(DBBookmark.id.desc()).all())
    items = [{
        "question_id": q.id, "question_text": q.text,
        "options": {l: getattr(q, "option_" + l.lower(), None) for l in ["A", "B", "C", "D"]},
        "correct_answer": q.correct_answer, "explanation": q.explanation or "",
        "subject": q.subject or "General", "topic": q.topic or "",
    } for bm, q in bms]
    return {"status": "success", "count": len(items), "bookmarks": items}

@app.get("/admin/flagged-questions", tags=["Admin"])
def admin_flagged(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Questions students have flagged — drives the AI self-improvement loop."""
    rows = (db.query(DBQuestionFlag, DBQuestion)
            .join(DBQuestion, DBQuestionFlag.question_id == DBQuestion.id)
            .order_by(DBQuestionFlag.created_at.desc()).all())
    agg = {}
    for f, q in rows:
        a = agg.setdefault(q.id, {"question_id": q.id, "text": q.text, "subject": q.subject,
                                  "correct_answer": q.correct_answer, "count": 0, "reasons": {}})
        a["count"] += 1
        r = f.reason or "other"
        a["reasons"][r] = a["reasons"].get(r, 0) + 1
    items = sorted(agg.values(), key=lambda x: -x["count"])
    return {"status": "success", "count": len(items), "flagged": items}


# ── Knowledge Base: upload PDFs → chunks (grounding/library) + extracted MCQs ──
def _chunk_text(text, size=1100):
    text = " ".join((text or "").split())
    return [text[i:i + size] for i in range(0, len(text), size)] if text else []

def _vec_literal(vec):
    """Format a python float list as a pgvector literal: '[0.12,0.34,...]'."""
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def _semantic_chunks(db, query, subject=None, k=8):
    """Vector-search the knowledge base for the passages closest to `query`.
    Returns a list of text strings (closest first). Empty list if pgvector is
    off, the query can't be embedded, or nothing matches — callers fall back."""
    if not VECTOR_OK or not (query or "").strip():
        return []
    try:
        from gemini_service import embed_query
        qv = embed_query(query)
        if not qv:
            return []
        sql = ("SELECT text FROM knowledge_chunks "
               "WHERE embedding IS NOT NULL " +
               ("AND subject = :subj " if subject else "") +
               "ORDER BY embedding <=> (:qv)::vector LIMIT :k")
        params = {"qv": _vec_literal(qv), "k": int(k)}
        if subject:
            params["subj"] = subject
        rows = db.execute(sa_text(sql), params).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception:
        return []


def _retrieve_context(db, subject, topic="", limit_chars=2800):
    """Pull the most relevant uploaded book passages for grounding generation.
    Semantic (pgvector) search first; keyword/ILIKE as a fallback."""
    texts = _semantic_chunks(db, f"{subject} {topic}".strip(), subject=subject, k=8)
    if not texts:
        chunks = []
        if topic:
            chunks = (db.query(DBKnowledgeChunk)
                      .filter(DBKnowledgeChunk.subject == subject,
                              DBKnowledgeChunk.text.ilike(f"%{topic}%"))
                      .limit(6).all())
        if len(chunks) < 3:
            more = db.query(DBKnowledgeChunk).filter(DBKnowledgeChunk.subject == subject).limit(6).all()
            chunks = chunks + [c for c in more if c.id not in {x.id for x in chunks}]
        texts = [c.text for c in chunks]
    out, total = [], 0
    for t in texts:
        out.append(t)
        total += len(t or "")
        if total >= limit_chars:
            break
    return ("\n---\n".join(out))[:limit_chars]


def _retrieve_for_query(db, query, k=5, limit_chars=2400):
    """Cross-subject semantic retrieval for the mentor chat — grounds answers in
    whatever the student actually uploaded. Empty string when nothing fits."""
    texts = _semantic_chunks(db, query, subject=None, k=k)
    out, total = [], 0
    for t in texts:
        snippet = (t or "").strip()
        if not snippet:
            continue
        out.append(snippet)
        total += len(snippet)
        if total >= limit_chars:
            break
    return ("\n---\n".join(out))[:limit_chars]


def _embed_and_store_chunks(source_id, batch=128):
    """Embed every still-unembedded chunk of a source and persist the vectors.
    Best-effort and idempotent — safe to re-run. No-op without pgvector."""
    if not VECTOR_OK:
        return 0
    from gemini_service import embed_texts
    with engine.connect() as conn:
        rows = conn.execute(sa_text(
            "SELECT id, text FROM knowledge_chunks WHERE source_id = :sid AND embedding IS NULL"),
            {"sid": source_id}).fetchall()
    done = 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vecs = embed_texts([r[1] for r in part], task_type="RETRIEVAL_DOCUMENT")
        with engine.begin() as conn:
            for (cid, _txt), vec in zip(part, vecs):
                if not vec:
                    continue
                conn.execute(sa_text(
                    "UPDATE knowledge_chunks SET embedding = (:v)::vector WHERE id = :id"),
                    {"v": _vec_literal(vec), "id": cid})
                done += 1
    return done

def _extract_text_any(file_bytes, filename):
    """Extract (page_no, text) from ANY supported file. PDFs use PyMuPDF (with
    Gemini-vision OCR fallback for scanned pages); .docx via python-docx; text files
    decoded directly; images OCR'd via Gemini vision. Returns (pages, total, note)."""
    name = (filename or "").lower()
    note = ""
    if name.endswith(".pdf"):
        try:
            import fitz  # PyMuPDF
            from gemini_service import ocr_image
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            total = doc.page_count
            pages, ocr_used = [], 0
            for i in range(total):
                page = doc.load_page(i)
                txt = (page.get_text() or "").strip()
                if len(txt) < 20 and ocr_used < 400:        # likely scanned → OCR
                    try:
                        pix = page.get_pixmap(dpi=150)
                        otxt = ocr_image(pix.tobytes("png"), "image/png")
                        if otxt:
                            txt = otxt; ocr_used += 1
                    except Exception:
                        pass
                if txt:
                    pages.append((i + 1, txt))
            doc.close()
            if ocr_used:
                note = f"OCR used on {ocr_used} scanned page(s)."
            return pages, total, note
        except Exception:
            pass
        try:
            import io as _io
            from pypdf import PdfReader
            reader = PdfReader(_io.BytesIO(file_bytes))
            pages = []
            for i, p in enumerate(reader.pages):
                t = (p.extract_text() or "").strip()
                if t:
                    pages.append((i + 1, t))
            return pages, len(reader.pages), note
        except Exception as e:
            return [], 0, f"Could not read PDF: {str(e)[:140]}"
    if name.endswith(".docx"):
        try:
            import io as _io
            import docx
            d = docx.Document(_io.BytesIO(file_bytes))
            parts = [p.text for p in d.paragraphs if p.text and p.text.strip()]
            for tbl in d.tables:
                for row in tbl.rows:
                    cells = [c.text for c in row.cells if c.text and c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
            t = "\n".join(parts)
            return ([(1, t)] if t.strip() else []), 1, note
        except Exception as e:
            return [], 0, f"Could not read DOCX: {str(e)[:140]}"
    if name.endswith((".txt", ".md", ".csv", ".json")):
        try:
            t = file_bytes.decode("utf-8", "ignore")
            return ([(1, t)] if t.strip() else []), 1, note
        except Exception:
            return [], 0, "Could not decode text file."
    if name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif")):
        from gemini_service import ocr_image
        ext = name.rsplit(".", 1)[-1]
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "tif": "image/tiff"}.get(ext, "image/" + ext)
        t = ocr_image(file_bytes, mime)
        return ([(1, t)] if t.strip() else []), 1, ("OCR used." if t.strip() else "No readable text found in the image.")
    try:
        t = file_bytes.decode("utf-8", "ignore")
        if t.strip():
            return [(1, t)], 1, "Read as plain text."
    except Exception:
        pass
    return [], 0, "Unsupported file type — could not extract text."


def _process_file(source_id, file_bytes, filename, subject, mode, answer_bytes=None, answer_name=""):
    """Background worker: extract text from any file (OCR for scans/images) → store
    searchable chunks; for MCQ uploads extract MCQs into an importable test; then
    auto-catalogue the content (subjects/topics/tags). Restart-safe (derived data only)."""
    db = SessionLocal()
    try:
        src = db.query(DBKnowledgeSource).filter(DBKnowledgeSource.id == source_id).first()
        if not src:
            return
        page_texts, total_pages, note = _extract_text_any(file_bytes, filename)
        if not page_texts:
            src.status = "error"; src.error = note or "No readable text found."; db.commit(); return
        chunk_count = 0
        if mode in ("book", "both"):
            for pg, txt in page_texts:
                done = False
                for ch in _chunk_text(txt):
                    if chunk_count >= 6000:
                        done = True; break
                    db.add(DBKnowledgeChunk(source_id=source_id, subject=subject, page=pg, text=ch))
                    chunk_count += 1
                if done:
                    break
        src.pages = total_pages; src.chunk_count = chunk_count; db.commit()
        mcq_count = 0
        if mode in ("mcq", "both"):
            groups, buf = [], ""
            for _pg, txt in page_texts:
                buf += "\n" + txt
                if len(buf) > 4000:
                    groups.append(buf); buf = ""
            if buf.strip():
                groups.append(buf)
            groups = groups[:40]
            collected, seen = [], set()
            for g in groups:
                try:
                    qs = extract_mcqs_from_text(g, subject)
                except Exception:
                    qs = []
                for q in qs:
                    key = (q.get("text") or "")[:80]
                    if not key or key in seen:
                        continue
                    seen.add(key); collected.append(q)
                if len(collected) >= 500:
                    break
            if collected:
                db_test = DBMockTest(
                    title=f"📥 Imported • {src.filename}"[:120],
                    description=f"Imported from your upload — {subject}",
                    subject=subject or "Imported", total_questions=len(collected),
                    duration_minutes=max(5, len(collected)), user_id=src.uploaded_by)
                db.add(db_test); db.commit(); db.refresh(db_test)
                for q in collected:
                    db.add(DBQuestion(
                        text=q["text"], option_a=q["option_a"], option_b=q["option_b"],
                        option_c=q["option_c"], option_d=q["option_d"],
                        correct_answer=(q.get("correct_answer") or "A")[:1].upper(),
                        explanation=q.get("explanation", ""), subject=subject or None,
                        topic=q.get("topic") or None, difficulty="medium",
                        question_type="imported", mock_test_id=db_test.id))
                mcq_count = len(collected)
                src.mock_test_id = db_test.id
                db.commit()
        if answer_bytes:
            try:
                ans_pages, _t, _n = _extract_text_any(answer_bytes, answer_name or "answers.pdf")
                added = 0
                for _pg, txt in ans_pages:
                    for ch in _chunk_text(txt):
                        if added >= 400:
                            break
                        db.add(DBKnowledgeChunk(source_id=source_id, subject=subject,
                                                page=_pg, text="[Answer key] " + ch))
                        added += 1; chunk_count += 1
                src.chunk_count = chunk_count; db.commit()
            except Exception:
                pass
        # Embed all chunks for semantic (pgvector) retrieval. Best-effort.
        try:
            _embed_and_store_chunks(source_id)
        except Exception:
            pass
        # Auto-catalogue / taxonomy
        try:
            from gemini_service import catalogue_content
            sample = " ".join(t for _, t in page_texts)[:8000]
            tax = catalogue_content(sample, filename, subject)
            if not isinstance(tax, dict):
                tax = {}
            if note:
                tax["_processing_note"] = note
            if tax:
                src.taxonomy = json.dumps(tax)
                ps = (tax.get("primary_subject") or "").strip()
                if ps and (not subject or subject == "General"):
                    src.subject = ps[:60]
        except Exception:
            pass
        # Processing succeeded — drop the saved raw copy to free DB space.
        src.mcq_count = mcq_count; src.status = "done"; src.raw_b64 = None; db.commit()
    except Exception as e:
        try:
            src = db.query(DBKnowledgeSource).filter(DBKnowledgeSource.id == source_id).first()
            if src:
                # A real error (not a kill) — record it and drop the saved copy so it
                # isn't retried forever. Kills leave status='processing' for auto-resume.
                src.status = "error"; src.error = str(e)[:200]; src.raw_b64 = None; db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _reprocess_source(source_id):
    """Re-run processing for a source from its saved raw copy (resume after a kill).
    Idempotent: clears any partial derived data first so it never duplicates."""
    import base64 as _b64
    db = SessionLocal()
    data = None; fname = "upload.pdf"; subj = "General"; mode = "book"
    try:
        s = db.query(DBKnowledgeSource).filter(DBKnowledgeSource.id == source_id).first()
        if not s or not s.raw_b64:
            return
        try:
            data = _b64.b64decode(s.raw_b64)
        except Exception:
            return
        # Wipe any partial output from the killed run so the re-run is clean.
        db.query(DBKnowledgeChunk).filter(DBKnowledgeChunk.source_id == source_id).delete()
        if s.mock_test_id:
            try:
                db.query(DBQuestion).filter(DBQuestion.mock_test_id == s.mock_test_id).delete()
                db.query(DBMockTest).filter(DBMockTest.id == s.mock_test_id).delete()
            except Exception:
                pass
            s.mock_test_id = None
        s.status = "processing"; s.error = None; s.pages = 0; s.chunk_count = 0; s.mcq_count = 0
        mode = s.proc_mode or "book"; fname = s.filename or "upload.pdf"; subj = s.subject or "General"
        db.commit()
    except Exception:
        db.close(); return
    finally:
        db.close()
    if data is not None:
        _process_file(source_id, data, fname, subj, mode)


@app.on_event("startup")
def _resume_unfinished_uploads():
    """On boot, resume any upload whose processing was interrupted (e.g. the free
    instance spun down mid-job). Only those with a saved raw copy can resume."""
    import threading
    try:
        db = SessionLocal()
        ids = [s.id for s in db.query(DBKnowledgeSource).filter(
            DBKnowledgeSource.status == "processing",
            DBKnowledgeSource.raw_b64.isnot(None)).all()]
        db.close()
        for sid in ids:
            threading.Thread(target=_reprocess_source, args=(sid,), daemon=True).start()
    except Exception:
        pass


# Upload categories -> (processing mode, friendly label)
KNOWLEDGE_CATEGORIES = {
    "mcq_no_answers":   ("mcq",  "MCQs (no answers)"),
    "mcq_with_answers": ("mcq",  "MCQs (with answers)"),
    "book":             ("book", "Book"),
    "current_affairs":  ("both", "Current Affairs"),
    "strategy":         ("book", "Strategy"),
    "techniques":       ("book", "Techniques"),
    "mnemonics":        ("book", "Mnemonics"),
    "other":            ("book", "Other"),
}

@app.post("/admin/knowledge/upload", tags=["Knowledge"])
async def knowledge_upload(background: BackgroundTasks, file: UploadFile = File(...),
                           answer_file: Optional[UploadFile] = File(None),
                           subject: str = Form(""), category: str = Form("book"),
                           kind: str = Form(""), month: str = Form(""),
                           description: str = Form(""),
                           admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    # Accepts ANY file type. Text is extracted (with OCR for scans/images); no size cap.
    fname = (file.filename or "upload").strip() or "upload"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    cat = (category or "").lower().strip()
    if cat not in KNOWLEDGE_CATEGORIES:
        legacy = (kind or "book").lower()
        cat = {"mcq": "mcq_with_answers", "both": "current_affairs"}.get(legacy, "book")
    mode, label = KNOWLEDGE_CATEGORIES[cat]
    subj = (subject or "").strip() or "Mixed Subject/Topic"
    month = (month or "").strip()
    display = label + (f" • {month}" if (cat == "current_affairs" and month) else "")
    ext = (fname.rsplit(".", 1)[-1].lower() if "." in fname else "")
    ans_bytes, ans_name = None, ""
    if answer_file is not None and (answer_file.filename or "").strip():
        ans_bytes = await answer_file.read()
        ans_name = answer_file.filename or "answers"
    # Keep the raw file (base64) so processing can RESUME if the background job is
    # killed by a restart/spin-down. Capped at ~18MB raw to keep the DB write sane;
    # larger files still process, they just won't auto-resume. Cleared once done.
    import base64 as _b64
    raw_b64 = None
    try:
        if len(data) <= 18 * 1024 * 1024:
            raw_b64 = _b64.b64encode(data).decode("ascii")
    except Exception:
        raw_b64 = None
    src = DBKnowledgeSource(filename=fname[:200], subject=subj, kind=display,
                            status="processing", uploaded_by=admin.id,
                            description=((description or "").strip()[:2000] or None),
                            file_type=(ext or None), proc_mode=mode, raw_b64=raw_b64)
    db.add(src); db.commit(); db.refresh(src)
    background.add_task(_process_file, src.id, data, fname, subj, mode, ans_bytes, ans_name)
    return {"status": "success", "source_id": src.id,
            "message": "Upload received — extracting, OCR-reading & cataloguing in the background. Refresh to see progress."}

@app.get("/admin/knowledge/sources", tags=["Knowledge"])
def knowledge_sources(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    srcs = db.query(DBKnowledgeSource).order_by(DBKnowledgeSource.id.desc()).all()
    total_chunks = db.query(DBKnowledgeChunk).count()
    return {"status": "success", "total_chunks": total_chunks,
            "sources": [{
                "id": s.id, "filename": s.filename, "subject": s.subject, "kind": s.kind,
                "pages": s.pages or 0, "chunk_count": s.chunk_count or 0, "mcq_count": s.mcq_count or 0,
                "status": s.status, "error": s.error, "mock_test_id": s.mock_test_id,
                "description": s.description, "file_type": s.file_type,
                "resumable": bool(s.raw_b64),
                "taxonomy": (json.loads(s.taxonomy) if s.taxonomy else None),
                "created_at": s.created_at.isoformat() if s.created_at else None,
            } for s in srcs]}


@app.post("/admin/knowledge/reset-stuck", tags=["Knowledge"])
def reset_stuck_sources(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Mark uploads stuck in 'processing' (their background job was killed by a
    server restart) as 'error', so they stop showing as in-progress. The raw file
    isn't retained, so these must be re-uploaded to finish processing."""
    rows = db.query(DBKnowledgeSource).filter(DBKnowledgeSource.status == "processing").all()
    ids = []
    for s in rows:
        s.status = "error"
        s.error = "Processing was interrupted by a server restart. Please delete and re-upload this file."
        ids.append(s.id)
    db.commit()
    return {"status": "success", "reset": len(ids), "ids": ids}


@app.post("/admin/knowledge/resume", tags=["Knowledge"])
def resume_processing(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Manually re-trigger processing for uploads stuck in 'processing' that still
    have a saved raw copy. Uploads without a saved copy (older ones) can't resume —
    those are reported so the admin knows to delete + re-upload them."""
    import threading
    resumable = [s.id for s in db.query(DBKnowledgeSource).filter(
        DBKnowledgeSource.status == "processing", DBKnowledgeSource.raw_b64.isnot(None)).all()]
    no_copy = db.query(DBKnowledgeSource).filter(
        DBKnowledgeSource.status == "processing", DBKnowledgeSource.raw_b64.is_(None)).count()
    for sid in resumable:
        threading.Thread(target=_reprocess_source, args=(sid,), daemon=True).start()
    return {"status": "success", "resuming": resumable,
            "stuck_without_saved_file": no_copy}


@app.delete("/admin/knowledge/source/{source_id}", tags=["Knowledge"])
def delete_knowledge_source(source_id: int, admin: DBUser = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Delete a knowledge source and everything derived from it (chunks, and the
    imported MCQ test + its questions if one was created)."""
    s = db.query(DBKnowledgeSource).filter(DBKnowledgeSource.id == source_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Source not found")
    db.query(DBKnowledgeChunk).filter(DBKnowledgeChunk.source_id == source_id).delete()
    if s.mock_test_id:
        try:
            db.query(DBQuestion).filter(DBQuestion.mock_test_id == s.mock_test_id).delete()
            db.query(DBMockTest).filter(DBMockTest.id == s.mock_test_id).delete()
        except Exception:
            pass
    db.delete(s)
    db.commit()
    return {"status": "success", "deleted": source_id, "filename": s.filename}

@app.post("/admin/embeddings/backfill", tags=["Knowledge"])
def backfill_embeddings(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Embed chunks that don't yet have a vector (e.g. uploaded before RAG existed).
    Processes a bounded batch per call to stay within request limits — call again
    while `still_pending` > 0 until it reaches 0."""
    if not VECTOR_OK:
        return {"status": "skipped",
                "reason": "pgvector is not enabled on this database; semantic search is using keyword fallback."}
    import gemini_service
    from gemini_service import embed_texts
    was_pending = db.execute(sa_text(
        "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NULL")).scalar() or 0
    rows = db.execute(sa_text(
        "SELECT id, text FROM knowledge_chunks WHERE embedding IS NULL ORDER BY id LIMIT 300")).fetchall()
    done = 0
    for i in range(0, len(rows), 50):
        part = rows[i:i + 50]
        vecs = embed_texts([r[1] for r in part], task_type="RETRIEVAL_DOCUMENT")
        for (cid, _t), vec in zip(part, vecs):
            if not vec:
                continue
            db.execute(sa_text("UPDATE knowledge_chunks SET embedding = (:v)::vector WHERE id = :id"),
                       {"v": _vec_literal(vec), "id": cid})
            done += 1
        db.commit()
    still_pending = db.execute(sa_text(
        "SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NULL")).scalar() or 0
    try:
        provider = gemini_service.embed_provider()
    except Exception:
        provider = "gemini"
    return {"status": "success", "embedded_this_run": done,
            "was_pending": was_pending, "still_pending": still_pending,
            "embed_provider": provider,
            "embed_model": getattr(gemini_service, "EMBED_MODEL", ""),
            "last_error": getattr(gemini_service, "LAST_EMBED_ERROR", ""),
            "done": still_pending == 0}


@app.post("/admin/embeddings/reset", tags=["Knowledge"])
def reset_embeddings(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    """Clear ALL stored chunk vectors (set embedding = NULL). Needed once when you
    SWITCH embedding providers (e.g. Gemini → OpenAI): vectors from different models
    live in different spaces, so the whole index must be rebuilt with the new one.
    After calling this, run /admin/embeddings/backfill until still_pending = 0."""
    if not VECTOR_OK:
        return {"status": "skipped", "reason": "pgvector not enabled."}
    try:
        provider = __import__("gemini_service").embed_provider()
    except Exception:
        provider = "gemini"
    db.execute(sa_text("UPDATE knowledge_chunks SET embedding = NULL WHERE embedding IS NOT NULL"))
    db.commit()
    pending = db.execute(sa_text("SELECT COUNT(*) FROM knowledge_chunks")).scalar() or 0
    return {"status": "success", "cleared": True, "now_active_provider": provider,
            "chunks_to_reembed": pending}


@app.get("/knowledge/search", tags=["Knowledge"])
def knowledge_search(q: str = "", subject: Optional[str] = None, limit: int = 20,
                     current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    qq = (q or "").strip()
    if len(qq) < 2:
        return {"status": "success", "count": 0, "results": []}
    query = (db.query(DBKnowledgeChunk, DBKnowledgeSource)
             .join(DBKnowledgeSource, DBKnowledgeChunk.source_id == DBKnowledgeSource.id)
             .filter(DBKnowledgeChunk.text.ilike(f"%{qq}%")))
    if subject and subject.lower() not in ("", "all"):
        query = query.filter(DBKnowledgeChunk.subject == subject)
    rows = query.limit(max(1, min(limit, 50))).all()
    return {"status": "success", "count": len(rows),
            "results": [{"text": c.text, "subject": c.subject, "page": c.page,
                         "source": s.filename} for c, s in rows]}

@app.get("/knowledge/subjects", tags=["Knowledge"])
def knowledge_subjects(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    subs = [r[0] for r in db.query(DBKnowledgeChunk.subject).distinct().all() if r[0]]
    return {"status": "success", "subjects": sorted(subs), "has_library": bool(subs)}


# ── Phase 4: Content Depth (notes · flashcards · mnemonics · mind map · CA) ────
class ContentRequest(BaseModel):
    topic: str
    subject: Optional[str] = ""
    count: Optional[int] = 10

class CARequest(BaseModel):
    event: str

@app.post("/content/notes", tags=["Content"])
def content_notes(req: ContentRequest, current_user: DBUser = Depends(get_current_user)):
    if not (req.topic or "").strip():
        raise HTTPException(status_code=400, detail="Topic is required")
    try:
        return {"status": "success", "notes": generate_study_notes(req.topic.strip(), req.subject or "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")

@app.post("/content/flashcards", tags=["Content"])
def content_flashcards(req: ContentRequest, current_user: DBUser = Depends(get_current_user)):
    if not (req.topic or "").strip():
        raise HTTPException(status_code=400, detail="Topic is required")
    try:
        cards = generate_flashcards(req.topic.strip(), req.subject or "", req.count or 10)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")
    if not cards:
        raise HTTPException(status_code=502, detail="Could not generate flashcards. Try again.")
    return {"status": "success", "count": len(cards), "cards": cards}

@app.post("/content/mnemonics", tags=["Content"])
def content_mnemonics(req: ContentRequest, current_user: DBUser = Depends(get_current_user)):
    if not (req.topic or "").strip():
        raise HTTPException(status_code=400, detail="Topic is required")
    try:
        return {"status": "success", "mnemonics": generate_mnemonics(req.topic.strip(), req.subject or "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")

@app.post("/content/mindmap", tags=["Content"])
def content_mindmap(req: ContentRequest, current_user: DBUser = Depends(get_current_user)):
    if not (req.topic or "").strip():
        raise HTTPException(status_code=400, detail="Topic is required")
    try:
        return {"status": "success", "tree": generate_mindmap(req.topic.strip(), req.subject or "")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")

@app.post("/content/current-affairs", tags=["Content"])
def content_current_affairs(req: CARequest, current_user: DBUser = Depends(get_current_user)):
    if not (req.event or "").strip():
        raise HTTPException(status_code=400, detail="Event/topic is required")
    try:
        return {"status": "success", "analysis": current_affairs_analysis(req.event.strip())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation error: {str(e)}")


# ── Leaderboard ───────────────────────────────────────────────────────────────
@app.get("/leaderboard/", tags=["Results"])
def get_leaderboard(db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    users = db.query(DBUser).all()
    board = []
    for u in users:
        attempts = db.query(DBTestAttempt).filter(DBTestAttempt.user_id == u.id).all()
        if not attempts:
            continue
        avg = sum(
            (a.score / a.mock_test.total_questions * 100) for a in attempts if a.mock_test.total_questions
        ) / len(attempts)
        board.append({
            "name": u.name or u.email.split('@')[0],
            "email": u.email,
            "tests_taken": len(attempts),
            "avg_score": round(avg, 1),
            "is_me": u.id == current_user.id,
        })
    board.sort(key=lambda x: x['avg_score'], reverse=True)
    for i, entry in enumerate(board):
        entry['rank'] = i + 1
    return {"status": "success", "leaderboard": board}

# ── Admin dashboard ───────────────────────────────────────────────────────────
def _attempt_metrics(db, attempt):
    total = attempt.mock_test.total_questions or 0 if attempt.mock_test else 0
    attempted = db.query(DBAnswer).filter(DBAnswer.test_attempt_id == attempt.id).count()
    correct = attempt.score or 0
    wrong = max(0, attempted - correct)
    pct = round(correct / total * 100, 1) if total else 0.0
    net = round(correct * 2.0 - wrong * (2.0 / 3.0), 2)
    net_pct = round(net / (total * 2.0) * 100, 1) if total else 0.0
    accuracy = round(correct / attempted * 100, 1) if attempted else 0.0
    return {"attempted": attempted, "correct": correct, "wrong": wrong, "total": total,
            "pct": pct, "net": net, "net_pct": net_pct, "accuracy": accuracy}

@app.get("/admin/overview", tags=["Admin"])
def admin_overview(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    from collections import Counter
    users = db.query(DBUser).filter(DBUser.email != SYSTEM_USER_EMAIL).all()
    attempts = db.query(DBTestAttempt).all()
    pcts = [(a.score or 0) / a.mock_test.total_questions * 100
            for a in attempts if a.mock_test and a.mock_test.total_questions]
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    active7 = len({a.user_id for a in attempts if a.completed_at and a.completed_at >= cutoff})
    cnt = Counter(a.mock_test.title for a in attempts if a.mock_test)
    return {
        "status": "success",
        "total_candidates": len(users),
        "total_attempts": len(attempts),
        "avg_percentage": round(sum(pcts) / len(pcts), 1) if pcts else 0.0,
        "active_last_7_days": active7,
        "most_attempted": [{"title": t, "attempts": c} for t, c in cnt.most_common(5)],
    }

@app.get("/admin/candidates", tags=["Admin"])
def admin_candidates(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    rows = []
    for u in db.query(DBUser).filter(DBUser.email != SYSTEM_USER_EMAIL).all():
        atts = db.query(DBTestAttempt).filter(DBTestAttempt.user_id == u.id).all()
        pcts = [(a.score or 0) / a.mock_test.total_questions * 100
                for a in atts if a.mock_test and a.mock_test.total_questions]
        last = max([a.completed_at for a in atts if a.completed_at], default=None)
        rows.append({
            "id": u.id, "name": u.name or "", "email": u.email,
            "registered": u.created_at.isoformat() if u.created_at else None,
            "tests_taken": len(atts),
            "avg_pct": round(sum(pcts) / len(pcts), 1) if pcts else 0.0,
            "best_pct": round(max(pcts), 1) if pcts else 0.0,
            "last_active": last.isoformat() if last else None,
        })
    rows.sort(key=lambda r: r["last_active"] or "", reverse=True)
    return {"status": "success", "count": len(rows), "candidates": rows}

@app.get("/admin/candidates/{user_id}", tags=["Admin"])
def admin_candidate_detail(user_id: int, admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.query(DBUser).filter(DBUser.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Candidate not found")
    atts = (db.query(DBTestAttempt).filter(DBTestAttempt.user_id == u.id)
            .order_by(DBTestAttempt.completed_at.desc()).all())
    attempts = []
    for a in atts:
        m = _attempt_metrics(db, a)
        attempts.append({"attempt_id": a.id, "test": a.mock_test.title if a.mock_test else "",
                         "date": a.completed_at.isoformat() if a.completed_at else None, **m})
    rows = (db.query(DBQuestion.subject, DBAnswer.is_correct)
            .join(DBAnswer, DBAnswer.question_id == DBQuestion.id)
            .join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
            .filter(DBTestAttempt.user_id == u.id).all())
    subj = {}
    for s, ok in rows:
        if not s or s == "General":
            continue
        e = subj.setdefault(s, {"attempted": 0, "correct": 0})
        e["attempted"] += 1
        if ok:
            e["correct"] += 1
    by_subject = [{"subject": s, "attempted": e["attempted"], "correct": e["correct"],
                   "accuracy": round(e["correct"] / e["attempted"] * 100, 1) if e["attempted"] else 0.0}
                  for s, e in sorted(subj.items())]
    return {
        "status": "success",
        "candidate": {"id": u.id, "name": u.name or "", "email": u.email,
                      "registered": u.created_at.isoformat() if u.created_at else None,
                      "tests_taken": len(atts)},
        "attempts": attempts, "by_subject": by_subject,
    }

@app.get("/admin/activity", tags=["Admin"])
def admin_activity(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    events = []
    for u in db.query(DBUser).filter(DBUser.email != SYSTEM_USER_EMAIL).all():
        if u.created_at:
            events.append({"type": "register", "time": u.created_at.isoformat(),
                           "name": u.name or u.email, "email": u.email, "detail": "registered"})
    for a in (db.query(DBTestAttempt).order_by(DBTestAttempt.completed_at.desc()).limit(100).all()):
        t = a.mock_test.total_questions or 0 if a.mock_test else 0
        pct = round((a.score or 0) / t * 100, 1) if t else 0.0
        u = a.user
        events.append({"type": "attempt", "time": a.completed_at.isoformat() if a.completed_at else None,
                       "name": (u.name or u.email) if u else "", "email": u.email if u else "",
                       "detail": "scored " + str(pct) + "% on " + (a.mock_test.title if a.mock_test else "")})
    events = [e for e in events if e["time"]]
    events.sort(key=lambda e: e["time"], reverse=True)
    return {"status": "success", "activity": events[:60]}

class AdminEmailReq(BaseModel):
    email: str

@app.get("/admin/admins", tags=["Admin"])
def list_admins(admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    config_set = set(ADMIN_EMAILS)
    out = [{"email": e, "source": "built-in", "removable": False} for e in sorted(config_set)]
    for a in db.query(DBAdminEmail).order_by(DBAdminEmail.email).all():
        if (a.email or "").lower() in config_set:
            continue
        out.append({"email": a.email, "source": "added", "removable": True,
                    "added_by": a.added_by,
                    "created_at": a.created_at.isoformat() if a.created_at else None})
    return {"status": "success", "admins": out}

@app.post("/admin/admins", tags=["Admin"])
def add_admin(req: AdminEmailReq, admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    email = (req.email or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if email in set(ADMIN_EMAILS):
        raise HTTPException(status_code=400, detail="That email is already a built-in admin")
    if db.query(DBAdminEmail).filter(DBAdminEmail.email == email).first():
        raise HTTPException(status_code=400, detail="That email is already an admin")
    db.add(DBAdminEmail(email=email, added_by=admin.email))
    db.commit()
    return {"status": "success", "message": email + " added as admin",
            "note": "They get admin access once they register/log in with this email."}

@app.delete("/admin/admins", tags=["Admin"])
def remove_admin(email: str, admin: DBUser = Depends(require_admin), db: Session = Depends(get_db)):
    email = (email or "").strip().lower()
    if email in set(ADMIN_EMAILS):
        raise HTTPException(status_code=400, detail="Built-in admins can't be removed here")
    a = db.query(DBAdminEmail).filter(DBAdminEmail.email == email).first()
    if not a:
        raise HTTPException(status_code=404, detail="Admin email not found")
    db.delete(a)
    db.commit()
    return {"status": "success", "message": email + " removed from admins"}

# ── AI ────────────────────────────────────────────────────────────────────────
@app.post("/ai/generate-questions/", tags=["AI Features"])
def ai_generate_questions(request: AIGenerateRequest, current_user: DBUser = Depends(get_current_user)):
    try:
        result = generate_questions(request.subject, request.topic, request.num_questions)
        return {"status": "success", "generated_questions": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

@app.post("/ai/explain/", tags=["AI Features"])
def ai_explain(request: AIExplainRequest, current_user: DBUser = Depends(get_current_user)):
    try:
        result = explain_concept(request.topic, request.context)
        return {"status": "success", "explanation": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

@app.post("/ai/analyze/{attempt_id}/", tags=["AI Features"])
def ai_analyze_performance(attempt_id: int, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """AI Mentor Report: compute exact performance stats (net score with UPSC negative
    marking, attempt/accuracy split, subject-wise accuracy) and let the AI interpret them."""
    db_attempt = db.query(DBTestAttempt).filter(DBTestAttempt.id == attempt_id, DBTestAttempt.user_id == current_user.id).first()
    if not db_attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    questions = db.query(DBQuestion).filter(DBQuestion.mock_test_id == db_attempt.mock_test_id).all()
    ans_map = {a.question_id: a for a in db.query(DBAnswer).filter(DBAnswer.test_attempt_id == attempt_id).all()}

    total = len(questions)
    attempted = sum(1 for q in questions if q.id in ans_map)
    correct = sum(1 for q in questions if q.id in ans_map and ans_map[q.id].is_correct)
    wrong = attempted - correct
    blank = total - attempted
    accuracy = round(correct / attempted * 100, 1) if attempted else 0.0

    # UPSC Prelims marking: 2 marks per question, -1/3 of 2 (~0.66) per wrong answer.
    MARKS_PER_Q, NEG = 2.0, 2.0 / 3.0
    max_marks = round(total * MARKS_PER_Q, 2)
    net_marks = round(correct * MARKS_PER_Q - wrong * NEG, 2)
    net_pct = round(net_marks / max_marks * 100, 1) if max_marks else 0.0

    def _correct_text(q):
        return {"A": q.option_a, "B": q.option_b, "C": q.option_c, "D": q.option_d}.get(q.correct_answer, "")

    # Subject-wise breakdown (skip untagged questions so they don't form a fake subject)
    subj = {}
    this_test_missed = []  # detailed misses on THIS test, for topic extraction
    for q in questions:
        a = ans_map.get(q.id)
        if not (a and a.is_correct):  # wrong or blank
            this_test_missed.append({
                "subject": q.subject or "—", "text": q.text,
                "correct": _correct_text(q), "exp": (q.explanation or "")[:200],
            })
        s = q.subject
        if not s or s == "General":
            continue
        e = subj.setdefault(s, {"total": 0, "correct": 0, "attempted": 0})
        e["total"] += 1
        if a:
            e["attempted"] += 1
            if a.is_correct:
                e["correct"] += 1
    by_subject = []
    for s, e in sorted(subj.items()):
        acc = round(e["correct"] / e["total"] * 100, 1) if e["total"] else 0.0
        by_subject.append({"subject": s, "total": e["total"], "correct": e["correct"],
                           "attempted": e["attempted"], "accuracy": acc})

    # ── Candidate-wide history (across ALL of this user's attempts) ──────────────
    all_attempts = (db.query(DBTestAttempt)
                    .filter(DBTestAttempt.user_id == current_user.id)
                    .order_by(DBTestAttempt.completed_at).all())
    attempt_ids = [a.id for a in all_attempts]

    # Cumulative subject accuracy across every answer the candidate has ever given.
    overall_subj = {}
    if attempt_ids:
        rows = (db.query(DBQuestion.subject, DBAnswer.is_correct)
                .join(DBAnswer, DBAnswer.question_id == DBQuestion.id)
                .filter(DBAnswer.test_attempt_id.in_(attempt_ids)).all())
        for s, ok in rows:
            if not s or s == "General":
                continue  # ignore untagged questions in subject analytics
            e = overall_subj.setdefault(s, {"attempted": 0, "correct": 0})
            e["attempted"] += 1
            if ok:
                e["correct"] += 1
    overall_by_subject = []
    for s, e in sorted(overall_subj.items()):
        acc = round(e["correct"] / e["attempted"] * 100, 1) if e["attempted"] else 0.0
        overall_by_subject.append({"subject": s, "attempted": e["attempted"], "correct": e["correct"], "accuracy": acc})

    # Recurring misses across ALL the candidate's tests (for topic-pattern detection).
    history_missed = []
    if attempt_ids:
        for s, qtext in (db.query(DBQuestion.subject, DBQuestion.text)
                         .join(DBAnswer, DBAnswer.question_id == DBQuestion.id)
                         .filter(DBAnswer.test_attempt_id.in_(attempt_ids),
                                 DBAnswer.is_correct == False).limit(60).all()):  # noqa: E712
            if s and s != "General":
                history_missed.append((s, qtext))

    # Per-attempt trend (net % and accuracy over time).
    ans_counts = {}
    if attempt_ids:
        from sqlalchemy import func as sa_func
        for aid, cnt in (db.query(DBAnswer.test_attempt_id, sa_func.count(DBAnswer.id))
                         .filter(DBAnswer.test_attempt_id.in_(attempt_ids))
                         .group_by(DBAnswer.test_attempt_id).all()):
            ans_counts[aid] = cnt
    trend = []
    for a in all_attempts:
        a_total = a.mock_test.total_questions or 0
        a_att = ans_counts.get(a.id, 0)
        a_correct = a.score or 0
        a_wrong = max(0, a_att - a_correct)
        a_net = round(a_correct * MARKS_PER_Q - a_wrong * NEG, 2)
        a_max = round(a_total * MARKS_PER_Q, 2)
        trend.append({
            "title": a.mock_test.title,
            "date": a.completed_at.strftime("%d %b %Y") if a.completed_at else "",
            "net_percentage": round(a_net / a_max * 100, 1) if a_max else 0.0,
            "accuracy": round(a_correct / a_att * 100, 1) if a_att else 0.0,
        })
    overall_attempted = sum(ans_counts.values())
    overall_correct = sum(a.score or 0 for a in all_attempts)
    overall_accuracy = round(overall_correct / overall_attempted * 100, 1) if overall_attempted else 0.0

    candidate = {
        "name": current_user.name or (current_user.email.split("@")[0] if current_user.email else "Aspirant"),
        "tests_taken": len(all_attempts),
        "overall_accuracy": overall_accuracy,
        "overall_by_subject": overall_by_subject,
        "trend": trend[-8:],
    }

    stats = {
        "score": db_attempt.score, "total_questions": total,
        "attempted": attempted, "correct": correct, "wrong": wrong, "blank": blank,
        "accuracy": accuracy, "net_marks": net_marks, "max_marks": max_marks, "net_percentage": net_pct,
        "by_subject": by_subject,
        "candidate": candidate,
    }

    # Build a detailed stats summary for the AI (it must work from the ACTUAL missed
    # questions to name specific topics — not give generic subject advice).
    single_subject = len(by_subject) == 1
    persistent_weak = sorted([b for b in overall_by_subject if b["attempted"] >= 3], key=lambda x: x["accuracy"])[:3]
    trend_line = " -> ".join(f"{t['net_percentage']}%" for t in candidate["trend"]) or "n/a"

    this_missed_block = "\n".join(
        f"  - [{m['subject']}] {m['text'][:160]} | Correct: {m['correct'][:70]}"
        + (f" | Why: {m['exp']}" if m['exp'] else "")
        for m in this_test_missed[:14]
    ) or "  (none — all correct)"
    history_block = "\n".join(f"  - [{s}] {t[:120]}" for s, t in history_missed[:25]) or "  (no prior misses on record)"

    summary = (
        f"Candidate: {candidate['name']}\n"
        f"Tests taken: {candidate['tests_taken']} | Overall accuracy: {overall_accuracy}%\n"
        f"Net-score% trend (oldest->newest): {trend_line}\n\n"
        f"THIS TEST ({db_attempt.mock_test.title}): "
        + (f"single-subject test on {by_subject[0]['subject']}. " if single_subject else "")
        + f"net {net_pct}%, accuracy {accuracy}% (attempted {attempted}/{total}, {correct} correct, {wrong} wrong, {blank} blank), "
        f"negative-marking cost {round(wrong*NEG,1)} marks.\n"
        + ("" if single_subject else
           "This test by subject: " + "; ".join(f"{b['subject']} {b['accuracy']}%" for b in by_subject) + "\n")
        + "\nCUMULATIVE subject accuracy (all tests): "
        + ("; ".join(f"{b['subject']} {b['accuracy']}% (n={b['attempted']})" for b in overall_by_subject) or "only this test so far")
        + f"\nPersistent weak subjects (>=3 attempts): {', '.join(b['subject'] for b in persistent_weak) or 'not enough data yet'}\n\n"
        f"QUESTIONS MISSED ON THIS TEST (use these to name the exact topics/concepts they fail):\n{this_missed_block}\n\n"
        f"RECURRING MISSES ACROSS THEIR TESTS (find repeating themes/topics here):\n{history_block}"
    )

    try:
        report = generate_mentor_report(summary, candidate_name=candidate["name"])
    except Exception as e:
        report = None
        ai_error = str(e)
    if report is None:
        return {"status": "partial", "stats": stats, "report": None,
                "message": f"Stats computed, but AI narrative failed: {ai_error}"}
    return {"status": "success", "stats": stats, "report": report}

def _student_context(db, user):
    """A concise, factual snapshot of the student for the mentor to personalise on."""
    today = datetime.date.today()
    name = user.name or (user.email or "student").split("@")[0]
    parts = [f"Name: {name}"]
    prof = db.query(DBStudentProfile).filter(DBStudentProfile.user_id == user.id).first()
    if prof:
        if prof.target_year:
            try:
                exam = study_planner.prelims_date(int(str(prof.target_year)[:4]))
                dleft = (exam - today).days
                if dleft > 0:
                    parts.append(f"Target: Prelims {prof.target_year} (~{dleft} days left)")
            except Exception:
                pass
        if prof.study_hours:
            parts.append(f"Study time/day: {prof.study_hours} hrs")
        if prof.optional_subject:
            parts.append(f"Optional: {prof.optional_subject}")
        if prof.medium:
            parts.append(f"Medium: {prof.medium}")
        if prof.mains_language:
            parts.append(f"Mains language: {prof.mains_language}")
        if prof.coaching_status:
            parts.append(f"Prep mode: {prof.coaching_status}")
        # Educational background — helps gauge baseline knowledge.
        if prof.education:
            edu = prof.education
            if prof.graduation_stream:
                edu += f" ({prof.graduation_stream})"
            parts.append(f"Education: {edu}")
        if prof.schooling_medium:
            parts.append(f"Schooling medium: {prof.schooling_medium}")
        if prof.degree_percentage:
            parts.append(f"Graduation score: {prof.degree_percentage}")
        if prof.additional_qualification:
            parts.append(f"Additional qualifications: {prof.additional_qualification}")
        # Working commitment — governs how much time they realistically have.
        if prof.working_professional:
            wk = "Working"
            if prof.prep_intensity:
                wk += f" {prof.prep_intensity}"
            if prof.work_experience:
                wk += f" — {prof.work_experience}"
            parts.append(wk)
        # Self-rated level + diagnostic — where to pitch difficulty.
        if prof.prep_level:
            parts.append(f"Prep stage: {prof.prep_level}")
        if prof.knowledge_level:
            parts.append(f"Self-rated knowledge: {prof.knowledge_level}")
        if prof.comprehension_skill:
            parts.append(f"CSAT/reasoning: {prof.comprehension_skill}")
        if prof.diagnostic_gs is not None or prof.diagnostic_csat is not None:
            parts.append(f"Diagnostic — Knowledge {prof.diagnostic_gs}%, "
                         f"Reasoning {prof.diagnostic_csat}%")
        if prof.reading_speed:
            parts.append(f"Reading style: {prof.reading_speed}")
        if prof.learning_style:
            parts.append(f"Learning style: {prof.learning_style}")
        # Past attempts — where they fell short before.
        if prof.attempts:
            parts.append(f"Previous attempts: {prof.attempts}")
        if prof.failure_stage:
            parts.append(f"Fell short at: {prof.failure_stage}")
        if prof.failure_reason:
            parts.append(f"What held them back: {prof.failure_reason}")
        if prof.strong_subjects:
            parts.append(f"Self-declared strong areas: {prof.strong_subjects}")
        if prof.weak_subjects:
            parts.append(f"Self-declared weak areas: {prof.weak_subjects}")
    answers = _gather_answers(db, user.id)
    km = prepos.build_knowledge_map(answers, today) if answers else []
    if km:
        parts.append("Weakest subjects (mastery / retention): " +
                     ", ".join(f"{s['subject']} {s['mastery']}%/{s['retention']}%" for s in km[:3]))
        strong = sorted(km, key=lambda x: -x["mastery"])[:2]
        parts.append("Strongest: " + ", ".join(f"{s['subject']} {s['mastery']}%" for s in strong))
        review_items = [{"times_seen": r.times_seen, "times_correct": r.times_correct,
                         "mastered": r.mastered, "next_review": r.next_review}
                        for r in db.query(DBReviewItem).filter(DBReviewItem.user_id == user.id).all()]
        attempts = [{"completed_at": a.completed_at, "score": a.score}
                    for a in db.query(DBTestAttempt).filter(DBTestAttempt.user_id == user.id).all()]
        syl = db.query(DBSyllabusProgress).filter(DBSyllabusProgress.user_id == user.id).count()
        cov = round(100 * syl / max(1, syllabus_tracker_data.total_topics()))
        sc = prepos.compute_scores(answers, review_items, attempts, cov, today)
        parts.append(f"Scores — Knowledge {sc['knowledge']}%, Readiness {sc['readiness']}%, "
                     f"Retention {sc['retention']}%, Consistency {sc['consistency']}%, "
                     f"Success probability {sc['success_probability']}%. Answered {sc['answered']} questions.")
    else:
        parts.append("No practice attempts logged yet — they are just getting started.")
    try:
        review_due = db.query(DBReviewItem).filter(
            DBReviewItem.user_id == user.id, DBReviewItem.next_review <= datetime.datetime.utcnow(),
            DBReviewItem.mastered == False).count()  # noqa: E712
        hb = (prof.study_hours if prof else None) or "2-4"
        mission = prepos.daily_mission(km, review_due, hb, None, today, _mission_profile(prof))
        if mission["tasks"]:
            parts.append("Today's planned mission: " + "; ".join(t["title"] for t in mission["tasks"][:4]))
    except Exception:
        pass
    try:
        mc = (db.query(DBAnswer).join(DBTestAttempt, DBAnswer.test_attempt_id == DBTestAttempt.id)
              .filter(DBTestAttempt.user_id == user.id, DBAnswer.is_correct == False).count())  # noqa: E712
        if mc:
            parts.append(f"Total mistakes in their notebook: {mc}")
    except Exception:
        pass
    return "\n".join("- " + p for p in parts), name, km


def _mentor_suggestions(km, name):
    s = ["What should I do right now?"]
    if km:
        s.append(f"Teach me {km[0]['subject']}")
        s.append("Explain my most recent mistake")
        s.append("Am I on track to clear Prelims?")
    else:
        s.append("How do I start my UPSC preparation?")
        s.append("Make me a study routine")
    s.append("I'm feeling low — motivate me")
    return s[:5]


@app.get("/me/mentor/history", tags=["AI Features"])
def mentor_history(current_user: DBUser = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (db.query(DBChatMessage).filter(DBChatMessage.user_id == current_user.id)
            .order_by(DBChatMessage.id.desc()).limit(40).all())
    rows = list(reversed(rows))
    _ctx, name, km = _student_context(db, current_user)
    return {"status": "success",
            "messages": [{"role": r.role, "content": r.content} for r in rows],
            "suggestions": _mentor_suggestions(km, name),
            "greeting": (f"Namaste {name}! 🙏 I'm AIVORA — your guide, teacher, mentor and companion. "
                         f"I know your progress and I'm here for the whole journey. What's on your mind today?")}


@app.post("/ai/chat/", tags=["AI Features"])
def ai_chat(request: AIChatRequest, current_user: DBUser = Depends(get_current_user),
            db: Session = Depends(get_db)):
    msg = (request.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Say something to your mentor.")
    try:
        context, _name, _km = _student_context(db, current_user)
        passages = _retrieve_for_query(db, msg)
        if passages:
            context = (context +
                       "\n\nRelevant material from the student's AIVORA library (ground your answer in "
                       "this, prefer it over general knowledge, and don't invent facts beyond it):\n" +
                       passages)
        history = [{"role": r.role, "content": r.content} for r in
                   reversed(db.query(DBChatMessage).filter(DBChatMessage.user_id == current_user.id)
                            .order_by(DBChatMessage.id.desc()).limit(10).all())]
        reply = chat_with_mentor(msg, context, history)
        db.add(DBChatMessage(user_id=current_user.id, role="user", content=msg[:4000]))
        db.add(DBChatMessage(user_id=current_user.id, role="assistant", content=(reply or "")[:8000]))
        db.commit()
        return {"status": "success", "response": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

@app.post("/questions/{question_id}/explain/", tags=["AI Features"])
def ai_explain_question(question_id: int, db: Session = Depends(get_db), current_user: DBUser = Depends(get_current_user)):
    """On-demand AI explanation for a specific question (used on the review screen)."""
    q = db.query(DBQuestion).filter(DBQuestion.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    correct_text = {"A": q.option_a, "B": q.option_b, "C": q.option_c, "D": q.option_d}.get(q.correct_answer, "")
    message = (
        "Explain this UPSC Prelims question for an aspirant. State briefly why the correct "
        "option is right and why the others are wrong. Be concise and exam-focused.\n\n"
        f"Question: {q.text}\n"
        f"A) {q.option_a}\nB) {q.option_b}\nC) {q.option_c}\nD) {q.option_d}\n"
        f"Correct answer: {q.correct_answer}) {correct_text}"
    )
    try:
        result = chat_with_mentor(message)
        return {"status": "success", "explanation": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")
