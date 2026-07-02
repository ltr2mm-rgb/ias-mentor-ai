# IAS Mentor AI

An AI-powered UPSC / IAS exam preparation platform. A FastAPI backend serves
mock tests, scoring, leaderboards, and AI features (question generation,
concept explanations, performance analysis, and a mentor chat) powered by
Google Gemini. A standalone single-page frontend (`frontend/index.html`)
talks to the API.

## Project structure

```
ias-mentor-ai/
├── main.py              # FastAPI app + all route handlers
├── auth.py              # Password hashing + JWT helpers
├── config.py            # Loads settings from .env
├── database.py          # SQLAlchemy engine / session
├── models.py            # ORM models (User, MockTest, Question, ...)
├── schemas.py           # Pydantic schemas
├── gemini_service.py    # Google Gemini integration
├── frontend/
│   └── index.html       # Standalone web client (calls the API)
├── tests/
│   ├── debug_test.py    # DB / auth / config / register smoke test
│   └── test_gemini.py   # Gemini API connectivity check
├── requirements.txt
├── render.yaml          # Render.com deploy config
├── .env.template        # Copy to .env and fill in your values
├── .gitignore
└── ias_mentor.db        # SQLite database (created at runtime; gitignored)
```

> The backend modules live at the project root on purpose: they import each
> other by top-level name (e.g. `from database import ...`) and the Render
> deploy runs `uvicorn main:app` from here. Keep them together.

## 1. Set up your environment

```bash
# Create and activate a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## 2. Configure your .env file

Copy `.env.template` to `.env` and fill in your values:

```
GEMINI_API_KEY=your_actual_gemini_api_key
SECRET_KEY=any_long_random_string_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
DATABASE_URL=sqlite:///./ias_mentor.db
```

`.env` is gitignored — your real secrets never get committed.

## 3. Run the server

```bash
uvicorn main:app --reload
```

- API: http://localhost:8000
- Interactive docs (Swagger UI): http://localhost:8000/docs

## 4. Run the smoke tests

```bash
python tests/debug_test.py    # checks DB, auth, config, register flow
python tests/test_gemini.py   # checks the Gemini API connection
```

## 5. Typical API workflow

1. **Register** → `POST /register`
2. **Login** → `POST /login` (copy the `access_token`)
3. **Create a mock test** → `POST /mock-tests/`
4. **Add questions manually** or generate them with `POST /ai/generate-questions/`
5. **Take the test** → `GET /mock-tests/{id}/questions/`
6. **Submit answers** → `POST /mock-tests/{id}/submit/`
7. **View results** → `GET /attempts/{attempt_id}/results/`
8. **Get AI analysis** → `POST /ai/analyze/{attempt_id}/`

## Deployment

Deployed on Render via `render.yaml` (`uvicorn main:app --host 0.0.0.0 --port $PORT`).
Set `GEMINI_API_KEY` and `SECRET_KEY` in the Render dashboard (they are marked
`sync: false` and are never stored in the repo).
