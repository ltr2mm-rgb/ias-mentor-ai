"""
confirm_5572.py — READ-ONLY follow-up for the Mission Vocabulary investigation.

Locks the migration diagnosis: does question 5572 still carry concept_key
"Indian History" (it did on 2026-07-29), and re-runs the two queries whose output
got cut from the top of the earlier paste — (b) direct target count and (0) the
stored mission target for m-2-1.

SELECT-only; sets the session read-only; never deployed. Run it exactly like
confirm_vocab.py:

    # PowerShell:
    $env:DATABASE_URL = "<production Render Postgres URL>"
    python confirm_5572.py

Paste the printed JSON back. It contains a question's concept_key/subject, a count,
and the mission's stored concept_ids — no credentials.
"""
import os, json
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is not set. Set it to the production Postgres URL first.")

if url.startswith("postgresql") and "render.com" in url and "sslmode=" not in url:
    url += ("&" if "?" in url else "?") + "sslmode=require"

engine = create_engine(url, pool_pre_ping=True)

QUERIES = {
    "q5572_current_concept_key": """
        SELECT id, concept_key, subject
        FROM questions
        WHERE id = 5572
    """,
    "b_direct_target_count": """
        SELECT COUNT(*) AS n
        FROM questions
        WHERE concept_key = 'Indian History'
    """,
    "0_stored_mission_target": """
        SELECT event_id, user_id, seq, concept_ids, meta
        FROM learner_events
        WHERE activity_type = 'MISSION_CREATED'
          AND user_id = 2
          AND meta::jsonb ->> 'mission_id' = 'm-2-1'
    """,
}


def _jsonable(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def run():
    out = {}
    with engine.connect() as c:
        c.execute(text("SET default_transaction_read_only = on"))
        for name, q in QUERIES.items():
            try:
                rows = [dict(r._mapping) for r in c.execute(text(q))]
                for row in rows:
                    for k, val in list(row.items()):
                        row[k] = _jsonable(val)
                out[name] = rows
            except Exception as e:
                out[name] = {"__error": str(e)}
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    run()
