---
title: AIMENTORA
emoji: 🎓
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# AIMENTORA — AI Mentor for UPSC

FastAPI application serving the AIMENTORA UPSC preparation platform.

Required secrets (Space Settings → Variables and secrets):

- `GEMINI_API_KEY` — Google Gemini API key (use the Tier 1 / paid-project key)
- `DATABASE_URL` — External PostgreSQL connection string
- `SECRET_KEY` — JWT signing secret (any long random string)
- `OPENAI_API_KEY` — optional second engine key (Groq key works with the base URL below)

Optional variables:

- `OPENAI_BASE_URL` — e.g. `https://api.groq.com/openai/v1` for Groq
- `OPENAI_CHAT_MODEL` — e.g. `llama-3.3-70b-versatile`
- `GEMINI_MODEL` — e.g. `gemini-2.5-flash` (default is `gemini-2.5-flash-lite`)
- `ALGORITHM` — `HS256`
- `ACCESS_TOKEN_EXPIRE_MINUTES` — `720`
- `EMBED_PROVIDER` — `gemini` or `openai` (keep whatever the existing data used)
- `ADMIN_EMAILS` — comma-separated admin login emails
