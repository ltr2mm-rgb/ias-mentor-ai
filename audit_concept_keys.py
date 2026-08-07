"""
audit_concept_keys.py — READ-ONLY data audit for the Mission Vocabulary investigation
(docs/INVESTIGATION_mission_vocabulary.md, step 1 of remediation).

Scopes the null-`concept_key` landmine WITHOUT changing production:
  - how many questions have concept_key IS NULL, and what share of the bank;
  - the true landmines: null concept_key AND null topic AND null chapter
    (these fall back to ck="general" in /me/attempt, unmatchable by G3);
  - do the null-key rows cluster by subject / book / id-range (import batch)?
  - is 5572 an isolated anomaly or one of many?
  - vocabulary shape: how many concept_keys are NOT composite "<concept>|<subject>"
    (i.e. old-style coarse labels that survived), with samples.

SELECT-only; sets the session read-only; never deployed. Run like the others:

    # PowerShell:
    $env:DATABASE_URL = "<production Render Postgres URL>"
    python audit_concept_keys.py

Paste the printed JSON back. It contains counts, subjects, books, id ranges, and a
few sample concept_key strings — no credentials, no question text.
"""
import os, json
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit("DATABASE_URL is not set. Set it to the production Postgres URL first.")
if url.startswith("postgresql") and "render.com" in url and "sslmode=" not in url:
    url += ("&" if "?" in url else "?") + "sslmode=require"

engine = create_engine(url, pool_pre_ping=True)

# Note: empty-string guarded alongside NULL, since a blank tag behaves like a missing one.
QUERIES = {
    "totals": """
        SELECT
          COUNT(*)                                                       AS total_questions,
          COUNT(*) FILTER (WHERE concept_key IS NULL OR concept_key='')  AS null_or_blank_key,
          COUNT(*) FILTER (WHERE concept_key IS NOT NULL AND concept_key<>'') AS keyed
        FROM questions
    """,
    # True landmines: no concept_key AND no topic AND no chapter → /me/attempt falls back to "general",
    # which G3 cannot map back to these rows.
    "landmines_general_fallback": """
        SELECT COUNT(*) AS n
        FROM questions
        WHERE (concept_key IS NULL OR concept_key='')
          AND (topic       IS NULL OR topic='')
          AND (chapter     IS NULL OR chapter='')
    """,
    # Null-key rows that DO have a topic/chapter fallback (less severe, still not self-matching).
    "null_key_with_fallback": """
        SELECT COUNT(*) AS n
        FROM questions
        WHERE (concept_key IS NULL OR concept_key='')
          AND ( (topic IS NOT NULL AND topic<>'') OR (chapter IS NOT NULL AND chapter<>'') )
    """,
    "null_key_by_subject": """
        SELECT COALESCE(subject,'(null)') AS subject, COUNT(*) AS n
        FROM questions
        WHERE concept_key IS NULL OR concept_key=''
        GROUP BY subject ORDER BY n DESC
    """,
    "null_key_by_book": """
        SELECT COALESCE(book,'(null)') AS book, COUNT(*) AS n
        FROM questions
        WHERE concept_key IS NULL OR concept_key=''
        GROUP BY book ORDER BY n DESC LIMIT 30
    """,
    # id-range clustering (autoincrement id as an import-order / batch proxy).
    "null_key_by_id_bucket": """
        SELECT (id/1000)*1000 AS id_bucket, COUNT(*) AS n
        FROM questions
        WHERE concept_key IS NULL OR concept_key=''
        GROUP BY id_bucket ORDER BY id_bucket
    """,
    "null_key_id_span": """
        SELECT MIN(id) AS min_id, MAX(id) AS max_id, COUNT(*) AS n
        FROM questions
        WHERE concept_key IS NULL OR concept_key=''
    """,
    # Vocabulary shape: how many keyed rows are NOT composite "<...>|<...>" (old-style coarse labels
    # that survived), and a few samples of those.
    "noncomposite_keys": """
        SELECT COUNT(*) AS n_rows, COUNT(DISTINCT concept_key) AS n_distinct
        FROM questions
        WHERE concept_key IS NOT NULL AND concept_key<>'' AND concept_key NOT LIKE '%|%'
    """,
    "noncomposite_key_samples": """
        SELECT DISTINCT concept_key
        FROM questions
        WHERE concept_key IS NOT NULL AND concept_key<>'' AND concept_key NOT LIKE '%|%'
        ORDER BY concept_key LIMIT 40
    """,
    # Is 5572 alone, or do other rows share its (subject, null-key, null-topic/chapter) signature?
    "q5572_peers": """
        SELECT COUNT(*) AS n
        FROM questions
        WHERE (concept_key IS NULL OR concept_key='')
          AND subject = 'General Studies'
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
