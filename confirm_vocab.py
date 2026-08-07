"""
confirm_vocab.py — READ-ONLY diagnostic for the Mission Vocabulary investigation
(docs/INVESTIGATION_mission_vocabulary.md).

Runs confirmation queries (0), (a), (b), (c), (d) against the production database and
prints the results as JSON. SELECT-only — it sets the session to read-only before
running anything, so it CANNOT write, and it is never deployed. This is the
evidence-gathering step the freeze note prescribes; it is not a production code change.

Run it LOCALLY (from the project dir / same venv as the app, so the Postgres driver is
available):

    # PowerShell (Windows):
    $env:DATABASE_URL = "<production Render Postgres External URL>"
    python confirm_vocab.py

    # bash:
    DATABASE_URL="<production Render Postgres External URL>" python confirm_vocab.py

Where to find DATABASE_URL (keep it LOCAL — do not paste the URL into chat, it contains a
password):
    - Cloud Run:  gcloud run services describe aivora --region asia-south1 \
                    --project aivora-production \
                    --format="value(spec.template.spec.containers[0].env)"
    - or the Render dashboard → your Postgres instance → "External Database URL".

Then paste ONLY the printed JSON back into the investigation thread. The output contains
concept keys, counts, the stored mission target, and event metadata — no credentials.
"""
import os, json
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit(
        "DATABASE_URL is not set. Set it to the production Postgres URL first "
        "(locally; do NOT paste it into chat)."
    )

# Mirror database.py's Render SSL handling so the connection behaves identically to the app.
if url.startswith("postgresql") and "render.com" in url and "sslmode=" not in url:
    url += ("&" if "?" in url else "?") + "sslmode=require"

engine = create_engine(url, pool_pre_ping=True)

QUERIES = {
    "0_stored_mission_target": """
        SELECT event_id, user_id, seq, concept_ids, meta
        FROM learner_events
        WHERE activity_type = 'MISSION_CREATED'
          AND user_id = 2
          AND meta::jsonb ->> 'mission_id' = 'm-2-1'
    """,
    "a_question_vocabulary": """
        SELECT concept_key, subject, COUNT(*) AS n
        FROM questions
        GROUP BY concept_key, subject
        ORDER BY n DESC
    """,
    "b_direct_target_lookup": """
        SELECT COUNT(*) AS n
        FROM questions
        WHERE concept_key = 'Indian History'
    """,
    "c_inventory_history_domain": """
        SELECT key, concept, subject
        FROM concept_inventory
        WHERE concept ILIKE '%history%' OR key ILIKE '%history%' OR subject ILIKE '%history%'
    """,
    "d_attempt_provenance_user2": """
        SELECT concept_ids,
               COUNT(*)            AS n,
               MIN(module)         AS module,
               MIN(schema_version) AS min_schema,
               MAX(schema_version) AS max_schema,
               MIN(ingested_at)    AS first_seen,
               MAX(ingested_at)    AS last_seen,
               MIN(meta)           AS sample_meta
        FROM learner_events
        WHERE user_id = 2 AND activity_type = 'MCQ_ATTEMPTED'
        GROUP BY concept_ids
        ORDER BY n DESC
    """,
}


def _jsonable(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def run():
    out = {}
    with engine.connect() as c:
        # Safety belt: reject any accidental write for the whole session.
        c.execute(text("SET default_transaction_read_only = on"))
        for name, q in QUERIES.items():
            try:
                rows = [dict(r._mapping) for r in c.execute(text(q))]
                for row in rows:
                    for k, val in list(row.items()):
                        row[k] = _jsonable(val)
                out[name] = rows
            except Exception as e:  # keep going so one failing query doesn't hide the rest
                out[name] = {"__error": str(e)}
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    run()
