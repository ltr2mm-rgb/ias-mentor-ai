# Deploying IAS Mentor AI to aimentora.in

This version makes the app **production-durable**: it runs on Render with a free
**PostgreSQL** database, so user accounts and test history survive every redeploy
(required for login and the AI Mentor Report's progress tracking).

One service serves both the website and the API. Plan on ~20–30 minutes.

You'll use two free accounts — **GitHub** (stores code) and **Render** (runs the
site) — plus your domain's DNS for `aimentora.in`.

---

## Part A — Put the code on GitHub

1. Sign in at **github.com**. Click **+** (top-right) → **New repository**.
2. Name it **ias-mentor-ai**, leave it Public or Private, do NOT add a README.
   Click **Create repository**.
3. On the empty repo, click **uploading an existing file**.
4. Unzip **ias-mentor-ai-deploy.zip** and drag in ALL its files (main.py, the
   `frontend` folder, requirements.txt, render.yaml, etc.).
   - ⚠️ Do NOT upload `.env` or any `.db` file (the zip already excludes them).
5. Click **Commit changes**.

---

## Part B — Deploy on Render as a Blueprint (this creates the database too)

Because `render.yaml` now defines both the web service AND a free Postgres
database, deploy it as a **Blueprint** so Render creates both and links them.

1. Go to **dashboard.render.com** → **New +** → **Blueprint**.
2. Connect your GitHub and pick the **ias-mentor-ai** repo. (If it's not listed,
   click "Configure account" and grant access.)
3. Render reads `render.yaml` and shows it will create:
   - a Web Service **ias-mentor-ai**
   - a PostgreSQL database **ias-mentor-db** (Free)
   It already wires `DATABASE_URL` to the database and auto-generates `SECRET_KEY`.
4. It will prompt for the one secret it can't generate — **GEMINI_API_KEY**.
   Paste your real Gemini key (copy it from your local `.env`).
5. Click **Apply** / **Create**. Render provisions the DB and builds the service
   (a few minutes). When the web service shows **Live**, open its URL
   (like `https://ias-mentor-ai.onrender.com`).

> Prefer the manual route? You can instead do **New + → Web Service**, then create
> **New + → PostgreSQL (Free)** separately, and in the web service's Environment
> tab set `DATABASE_URL` to the database's **Internal Connection String**. The
> Blueprint route above does this for you.

---

## Part C — Test the live site

1. **Register** an account, then **Login**.
2. Open **📜 Previous Year Questions** → **By Year** (16 papers should appear) and
   **By Subject**.
3. Take a paper, submit, and open **🤖 AI Mentor Report**.
4. Log out and back in — your attempt should still be there (Postgres persistence).

If AI steps error out, recheck **GEMINI_API_KEY** in Render → Environment.

---

## Part D — Point aimentora.in at the new site

1. Render → your **ias-mentor-ai** service → **Settings** → **Custom Domains** →
   **Add Custom Domain**. Add both `aimentora.in` and `www.aimentora.in`.
2. Render shows the DNS records to create. Typically:
   - `www.aimentora.in` → a **CNAME** to your `...onrender.com` hostname.
   - `aimentora.in` (root/apex) → an **ALIAS/ANAME** to the same host, or the
     **A record** IP Render gives you (use ALIAS/ANAME if your DNS provider
     supports it; otherwise the A record).
3. Log in to wherever **aimentora.in**'s DNS is managed (your domain registrar)
   and add exactly those records. If a conflicting old record points the domain at
   your previous deployment, update/replace it.
4. Back in Render, click **Verify**. DNS + SSL can take minutes to a few hours.
   When verified, `https://aimentora.in` serves the new app with a free SSL cert.

---

## Updating later

Edit a file → on GitHub upload the changed file (or "Add file → Upload files") →
Render auto-redeploys. The database and your data are untouched by redeploys.

## Notes

- **Free Postgres limits:** Render's free Postgres is generous but has storage
  limits and, on some plans, an expiry window — if you outgrow it, upgrade the
  database plan (the app needs no code change; the `DATABASE_URL` stays wired).
  Alternatives with no expiry: **Neon** or **Supabase** free Postgres — just set
  `DATABASE_URL` to their connection string.
- **Free web service sleeps** after inactivity and takes a few seconds to wake on
  the first request — normal on the free tier; upgrade to keep it always-on.
- **Question bank** re-seeds from `pyq_bank.json` automatically on startup, so the
  16 years of papers are always present; only user accounts/attempts live in Postgres.
