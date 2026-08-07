import os
from dotenv import load_dotenv

load_dotenv()

# APP_ENV names the environment. It is OPTIONAL and defaults to empty — see the
# SECRET_KEY gate below, which is deliberately secure-by-default: an unset or
# unrecognised APP_ENV is treated as "possibly production", never as dev.
APP_ENV = os.getenv("APP_ENV", "").strip().lower()

# Only these EXPLICIT values permit the insecure dev fallback secret. Anything else
# — including unset, "unknown", "production", "staging" — must supply a real
# SECRET_KEY or the process refuses to start.
_DEV_ENVS = ("development", "dev", "local", "test", "testing", "ci")

# ── SECRET_KEY (fail-closed by default) ───────────────────────────────────────
# H1 fix: the old shared literal "change-me-in-production" default meant a deploy
# that forgot to set SECRET_KEY would sign JWTs with a publicly known key — and
# admin authority derives purely from the token's `sub`, so anyone could forge an
# admin token.
#
# The gate is deliberately INVERTED relative to the obvious design ("fail closed only
# when APP_ENV == production"): this repo does NOT reliably set APP_ENV in production —
# platform_version.py reports it as "unknown" by default, and setting it is still an
# open operational-readiness item in CHANGELOG.md. Keying the gate on APP_ENV=="production"
# would therefore leave a real production deploy silently running on the fallback key,
# i.e. the vulnerability would survive its own fix. So: a strong SECRET_KEY is REQUIRED
# unless the environment explicitly identifies itself as dev/test.
_INSECURE_DEFAULTS = {"", "change-me-in-production"}
_DEV_FALLBACK_SECRET = "dev-only-insecure-secret-not-for-deployment"

SECRET_KEY = os.getenv("SECRET_KEY", "")
if SECRET_KEY in _INSECURE_DEFAULTS:
    if APP_ENV not in _DEV_ENVS:
        raise RuntimeError(
            "SECRET_KEY is missing or set to a known insecure default "
            f"(APP_ENV={APP_ENV or 'unset'!r}). Refusing to start: JWTs signed with a "
            "publicly known key let anyone forge an admin token.\n"
            "  Deployed environments: set a strong, unique SECRET_KEY.\n"
            "  Local development / CI: set SECRET_KEY (see .env.template), or set "
            "APP_ENV=development to use the clearly-marked dev-only fallback."
        )
    # Explicit dev/test environment only: a clearly-marked dev key that is NOT the
    # old shared production default.
    SECRET_KEY = _DEV_FALLBACK_SECRET

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

# ── CORS allow-list ───────────────────────────────────────────────────────────
# Wildcard allow_origins=["*"] combined with allow_credentials=True is insecure
# (and, per the CORS spec, ignored by browsers for credentialed requests). We use
# an explicit allow-list instead. Override per environment with CORS_ALLOW_ORIGINS
# (comma-separated).
#
# The default deliberately contains ONLY the production web origins — no localhost.
# This app serves its own front-end (main.py serves frontend/index.html, which calls
# the API with relative URLs via `const API = ''`), so browser traffic is SAME-ORIGIN
# and never performs a CORS check at all. Local development therefore does not need a
# localhost entry, and shipping one would only widen the production allow-list for no
# benefit. Genuine cross-origin consumers must be added explicitly per environment.
CORS_ALLOW_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "https://aimentora.in,https://www.aimentora.in",
    ).split(",")
    if o.strip()
]
