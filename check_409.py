"""
check_409.py — post-deploy validation of the mission-lifecycle invariant.

Hits GET /me/mission/m-2-1/questions for USER 2 (whose target concept "Indian History"
has zero resolvable questions) and confirms the DEPLOYED app now returns 409 with the
structured MissionHasNoQuestions body — not the old 200 [].

Note: m-2-1 was already STARTED during the investigation, so the "stays CREATED"
half of the invariant is proven by the unit test (MA-6); this live check confirms the
HTTP 409 translation on real data.

Run with USER 2's token (your main account, ltr2mm), against the Cloud Run origin:
    # browser devtools on aimentora.in (logged into the main account): localStorage.getItem('ias_token')
    $env:AIMENTORA_TOKEN = "<user-2 ias_token>"
    $env:AIMENTORA_BASE  = "https://aivora-54122344163.asia-south1.run.app"
    python check_409.py
Paste the JSON back.
"""
import os, json, urllib.request, urllib.error

TOKEN = os.environ.get("AIMENTORA_TOKEN")
if not TOKEN:
    raise SystemExit("Set AIMENTORA_TOKEN to user 2's ias_token first.")
BASE = os.environ.get("AIMENTORA_BASE", "https://aimentora.in")


def req(method, path):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Authorization", "Bearer " + TOKEN)
    r.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, str(e)


out = {}
s, b = req("GET", "/me/mission/current")
out["current_before"] = {"status": s, "body": (b[:300])}
# THE check — G3 on the dead-concept mission. Expect 409, not 200 [].
s, b = req("GET", "/me/mission/m-2-1/questions")
out["G3_m-2-1"] = {"status": s, "body": b[:500]}
out["verdict"] = "PASS (409 invariant)" if s == 409 else ("FAIL — got %s" % s)
s, b = req("GET", "/me/mission/current")
out["current_after"] = {"status": s, "body": (b[:300])}
print(json.dumps(out, indent=2))
