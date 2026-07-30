from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

# Use check_same_thread=False for SQLite only
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# Render's EXTERNAL Postgres URLs require SSL when connecting from outside
# Render (e.g. from Hugging Face). Append sslmode=require if it's missing.
_url = DATABASE_URL
if _url.startswith("postgresql") and "render.com" in _url and "sslmode=" not in _url:
    _url += ("&" if "?" in _url else "?") + "sslmode=require"

engine = create_engine(_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
