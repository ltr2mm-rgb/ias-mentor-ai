"""
verify_journey.py — fresh-learner G0->G5 verification against the LIVE API.

Runs the intended production flow on a currently-keyed concept
("definition of state under article 12 of constitution", Indian Polity), to prove the
mission lifecycle works end-to-end on current data — the thing user 2 could NOT do.

Flow:
  0. GET /me/learning            (sanity: should be a fresh/near-empty projection)
  1. seed: POST /me/attempt x2   (register the keyed concept so a mission can target it)
  2. G0: GET /me/mission/current (generate + read the mission; expect target = the concept)
  3. G2: GET /me/mission/{id}
  4. G3: GET /me/mission/{id}/questions   (EXPECT NON-EMPTY, no answer leak; this starts it)
  5. G4: POST /me/attempt for each returned question (answered correctly via the map below)
  6. G5: GET /me/mission/{id}/outcome      (triggers completion; before/after + next rec)
  7. GET /me/mission/current again         (confirm completed / next mission)

This WRITES data to the fresh test account (attempts, a mission, an experiment enrollment).
Run it only against a throwaway/test learner.

Setup (PowerShell):
    # In the browser devtools console on aimentora.in:  localStorage.getItem('ias_token')
    # copy that string, then:
    $env:AIMENTORA_TOKEN = "<paste the fresh account's ias_token>"
    python verify_journey.py

Paste the printed JSON back. It contains mission fields, question ids/options, and
outcome numbers — no token.
"""
import os, json, urllib.request, urllib.error

TOKEN = os.environ.get("AIMENTORA_TOKEN")
if not TOKEN:
    raise SystemExit("Set AIMENTORA_TOKEN to the fresh account's ias_token first "
                     "(browser devtools: localStorage.getItem('ias_token')).")
BASE = os.environ.get("AIMENTORA_BASE", "https://aimentora.in")

# concept-X question -> correct answer (from pick_keyed_concept.py)
ANSWERS = {2415:"C",2424:"B",2454:"C",2466:"B",2536:"B",2543:"B",
           2554:"C",2593:"D",2634:"C",2662:"B",2684:"B",2691:"C"}


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Authorization", "Bearer " + TOKEN)
    r.add_header("Accept", "application/json")
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            txt = resp.read().decode()
            return {"status": resp.status, "body": (json.loads(txt) if txt else None)}
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try: b = json.loads(txt)
        except Exception: b = txt
        return {"status": e.code, "body": b}
    except Exception as e:
        return {"status": 0, "body": {"__err": str(e)}}


def main():
    out = {}
    out["0_learning_before"] = req("GET", "/me/learning")

    out["1_seed"] = [req("POST", "/me/attempt", {"question_id": qid, "selected": ANSWERS[qid]})
                     for qid in (2415, 2424)]

    g0 = req("GET", "/me/mission/current")
    out["2_G0_current"] = g0
    mid = None
    if isinstance(g0.get("body"), dict):
        mid = g0["body"].get("mission_id")
    out["mission_id"] = mid

    if not mid:
        out["__halt"] = "no mission_id from G0 — cannot continue"
        print(json.dumps(out, indent=2, default=str)); return

    out["3_G2_detail"] = req("GET", "/me/mission/" + mid)

    g3 = req("GET", "/me/mission/" + mid + "/questions")
    qs = g3.get("body")
    out["4_G3_status"] = g3.get("status")
    out["4_G3_count"] = len(qs) if isinstance(qs, list) else ("not-list:" + str(type(qs).__name__))
    out["4_G3_item0_keys"] = list(qs[0].keys()) if isinstance(qs, list) and qs else []
    out["4_G3_answer_leak"] = (
        any(("correct_answer" in q) or ("correct_index" in q) or ("answer" in q) for q in qs)
        if isinstance(qs, list) else None)

    out["5_G4_attempts"] = []
    if isinstance(qs, list):
        for q in qs:
            qid = q.get("id")
            try: qid_int = int(qid)
            except Exception: qid_int = qid
            sel = ANSWERS.get(qid_int, "A")
            a = req("POST", "/me/attempt", {"question_id": qid_int, "selected": sel})
            b = a.get("body") or {}
            out["5_G4_attempts"].append({
                "qid": qid, "status": a.get("status"),
                "correct": b.get("correct"),
                "correct_index": b.get("correct_index"),
                "has_explanation": bool(b.get("answer_explanation")),
            })

    out["6_G5_outcome"] = req("GET", "/me/mission/" + mid + "/outcome")
    out["7_current_after"] = req("GET", "/me/mission/current")

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
