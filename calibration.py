"""
calibration.py — confidence calibration (arch v1.4; review "build confidence
calibration: predicted confidence → observed accuracy").

The Policy Evaluator asks whether *expected gain* matches *actual gain*. This asks
the complementary question: is *confidence itself* trustworthy? When the system
(or the learner) says "90% sure", are they right ~90% of the time?

    predicted confidence   →   observed accuracy
        95%                        94%      ✅ well-calibrated
        60%                        42%      ⚠️ over-confident

v1 sources this from answer-level confidence tags (`ConceptAttempt.confidence` ∈
sure|somewhat|guess vs. `correct`) — the cleanest labelled signal available. The
same `reliability()` primitive later calibrates the Prediction Engine's numeric
confidence once readiness predictions have ground-truth labels.

Pure `reliability()` (testable, no DB) + a DB sourcing helper. Computes per-bucket
observed accuracy, counts, and Expected Calibration Error (ECE = Σ (n_b/N)·|conf_b −
acc_b|) — one number for "how far off is confidence overall".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# nominal confidence assigned to each categorical tag (tunable)
TAG_CONFIDENCE = {"sure": 0.90, "somewhat": 0.65, "guess": 0.35}


def reliability(pairs: List[Tuple[float, bool]],
                edges: Optional[List[float]] = None) -> Dict[str, Any]:
    """pairs: [(predicted_confidence 0-1, was_correct bool)]. Returns a reliability
    table (one row per confidence bucket) + overall ECE."""
    edges = edges or [0.0, 0.5, 0.7, 0.85, 0.95, 1.01]
    buckets = []
    n_total = len(pairs)
    ece = 0.0
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        inb = [(c, ok) for c, ok in pairs if lo <= c < hi]
        if not inb:
            continue
        n = len(inb)
        mean_conf = sum(c for c, _ in inb) / n
        obs_acc = sum(1 for _, ok in inb if ok) / n
        ece += (n / n_total) * abs(mean_conf - obs_acc)
        buckets.append({
            "range": f"{int(lo*100)}–{int(min(hi,1.0)*100)}%",
            "predicted_confidence": round(mean_conf, 2),
            "observed_accuracy": round(obs_acc, 2),
            "gap": round(obs_acc - mean_conf, 2),        # negative → over-confident
            "n": n,
        })
    return {
        "buckets": buckets,
        "ece": round(ece, 3) if n_total else None,        # 0 = perfectly calibrated
        "n": n_total,
        "verdict": _verdict(ece) if n_total else "no data",
    }


def _verdict(ece: float) -> str:
    return ("well-calibrated" if ece < 0.05 else
            "slightly off" if ece < 0.12 else "poorly calibrated — confidence is not trustworthy")


def answer_confidence_calibration(db, user_id: Optional[int] = None,
                                  limit: int = 20000) -> Dict[str, Any]:
    """Reliability of learners' answer-confidence tags vs. actual correctness."""
    import models
    q = db.query(models.ConceptAttempt.confidence, models.ConceptAttempt.correct)
    if user_id is not None:
        q = q.filter(models.ConceptAttempt.user_id == user_id)
    q = q.filter(models.ConceptAttempt.confidence.isnot(None))
    pairs: List[Tuple[float, bool]] = []
    for conf, correct in q.limit(limit).all():
        c = TAG_CONFIDENCE.get((conf or "").strip().lower())
        if c is not None:
            pairs.append((c, bool(correct)))
    out = reliability(pairs)
    out["source"] = "answer_confidence"
    out["mapping"] = TAG_CONFIDENCE
    return out


if __name__ == "__main__":
    # over-confident 'sure' answers, well-calibrated 'somewhat', poor 'guess'
    pairs = ([(0.90, True)] * 80 + [(0.90, False)] * 20 +       # sure: 80% actual vs 90% stated
             [(0.65, True)] * 65 + [(0.65, False)] * 35 +       # somewhat: 65% — spot on
             [(0.35, True)] * 30 + [(0.35, False)] * 70)        # guess: 30% — ~calibrated
    r = reliability(pairs)
    for b in r["buckets"]:
        print(f"  conf {b['predicted_confidence']:.0%}  →  observed {b['observed_accuracy']:.0%}  "
              f"(gap {b['gap']:+.0%}, n={b['n']})")
    print("ECE:", r["ece"], "→", r["verdict"])
    assert any(b["gap"] < 0 for b in r["buckets"]), "should detect over-confidence"
    assert r["ece"] is not None
    print("OK — reliability table + ECE detects over-confidence (stated 90%, observed 80%).")
