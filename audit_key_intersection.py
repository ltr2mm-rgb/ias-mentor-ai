"""
audit_key_intersection.py — READ-ONLY. Does the QUESTION vocabulary line up with the
CONCEPT-INVENTORY vocabulary that /me/attempt validates against?

Background: /me/attempt records a concept on an MCQ_ATTEMPTED event only if
canon(question.concept_key) is in concept_inventory.key (the _valid_concept_keys gate).
If keyed questions use slugs that are NOT inventory keys, their attempts drop to
concept_ids=[], the projection never learns the concept, and missions can't form — for
FRESH learners too, not just pre-divergence data.

This measures the overlap. SELECT-only; session set read-only; never deployed.

Run like the others:
    $env:DATABASE_URL = "<production Render Postgres URL>"
    python audit_key_intersection.py
Paste the JSON back — counts and a few sample key strings, no credentials.
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
    # Inventory vocabulary shape.
    "inventory_shape": """
        SELECT COUNT(*) AS total_keys,
               COUNT(*) FILTER (WHERE key LIKE '%|%')     AS composite_keys,
               COUNT(*) FILTER (WHERE key NOT LIKE '%|%')  AS noncomposite_keys
        FROM concept_inventory
    """,
    # Row-level: of keyed questions, how many have a concept_key that IS a valid inventory
    # key (attempt would register) vs is NOT (attempt would drop to []).
    "question_rows_vs_inventory": """
        SELECT
          COUNT(*)                                  AS keyed_question_rows,
          COUNT(*) FILTER (WHERE ci.key IS NOT NULL) AS registerable_rows,
          COUNT(*) FILTER (WHERE ci.key IS NULL)     AS would_drop_rows
        FROM questions q
        LEFT JOIN concept_inventory ci ON ci.key = q.concept_key
        WHERE q.concept_key IS NOT NULL AND q.concept_key <> ''
    """,
    # Distinct-key view (same question, deduped by key).
    "distinct_keys_vs_inventory": """
        SELECT
          COUNT(DISTINCT q.concept_key)                                   AS distinct_qkeys,
          COUNT(DISTINCT q.concept_key) FILTER (WHERE ci.key IS NOT NULL) AS distinct_in_inventory
        FROM questions q
        LEFT JOIN concept_inventory ci ON ci.key = q.concept_key
        WHERE q.concept_key IS NOT NULL AND q.concept_key <> ''
    """,
    "registerable_key_samples": """
        SELECT DISTINCT q.concept_key
        FROM questions q
        JOIN concept_inventory ci ON ci.key = q.concept_key
        WHERE q.concept_key IS NOT NULL AND q.concept_key <> ''
        ORDER BY q.concept_key LIMIT 15
    """,
    "would_drop_key_samples": """
        SELECT DISTINCT q.concept_key
        FROM questions q
        LEFT JOIN concept_inventory ci ON ci.key = q.concept_key
        WHERE q.concept_key IS NOT NULL AND q.concept_key <> '' AND ci.key IS NULL
        ORDER BY q.concept_key LIMIT 15
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
