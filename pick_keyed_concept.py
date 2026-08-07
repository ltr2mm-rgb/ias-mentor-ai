"""
pick_keyed_concept.py — READ-ONLY. Picks a currently-keyed concept suitable for the
fresh-learner G0->G5 verification, and returns its question ids + correct answers so the
browser journey can seed the projection and answer the mission correctly.

Chooses a concept_key that (a) is a valid concept_inventory.key, and (b) has enough
questions to complete a 5-step mission with margin. SELECT-only; session read-only.

Run like the others:
    $env:DATABASE_URL = "<production Render Postgres URL>"
    python pick_keyed_concept.py
Paste the JSON back — a concept_key and a list of {id, correct_answer, subject}. No
question text, no credentials.
"""
import os, json
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is not set. Set it to the production Postgres URL first.")
if url.startswith("postgresql") and "render.com" in url and "sslmode=" not in url:
    url += ("&" if "?" in url else "?") + "sslmode=require"

engine = create_engine(url, pool_pre_ping=True)


def run():
    out = {}
    with engine.connect() as c:
        c.execute(text("SET default_transaction_read_only = on"))

        # Candidates: keyed concepts that ARE valid inventory keys and have 6–12 questions
        # (enough for a 5-step mission plus seeding, small enough to fetch whole).
        cand_sql = text("""
            SELECT q.concept_key, COUNT(*) AS n
            FROM questions q
            JOIN concept_inventory ci ON ci.key = q.concept_key
            WHERE q.concept_key IS NOT NULL AND q.concept_key <> ''
            GROUP BY q.concept_key
            HAVING COUNT(*) BETWEEN 6 AND 12
            ORDER BY n DESC, q.concept_key ASC
            LIMIT 10
        """)
        candidates = [dict(r._mapping) for r in c.execute(cand_sql)]
        out["candidates"] = candidates
        if not candidates:
            out["__note"] = "no concept with 6-12 questions found; widen the range"
            print(json.dumps(out, indent=2, default=str))
            return

        chosen = candidates[0]["concept_key"]
        out["chosen_concept_key"] = chosen

        q_sql = text("""
            SELECT id, correct_answer, subject
            FROM questions
            WHERE concept_key = :ck
            ORDER BY id
        """)
        qs = [dict(r._mapping) for r in c.execute(q_sql, {"ck": chosen})]
        out["questions"] = qs
        out["n_questions"] = len(qs)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    run()
