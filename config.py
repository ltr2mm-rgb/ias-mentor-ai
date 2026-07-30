import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ias_mentor.db")
# Managed Postgres providers (Render/Heroku) hand out "postgres://" URLs, but
# SQLAlchemy 2.x requires the "postgresql://" scheme. Normalise it here.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Comma-separated list of admin emails. Accounts whose login email is in this
# list can access the /admin dashboard. Override with the ADMIN_EMAILS env var.
ADMIN_EMAILS = [
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "admin@aimentora.in,ltr2mm@gmail.com").split(",")
    if e.strip()
]
