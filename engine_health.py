"""
engine_health.py — operational telemetry for the adaptive engine (arch v1.4;
review "add engine health metrics").

Learner metrics (Policy Evaluator) answer *was the recommendation good?*
Engine health answers *is the engine itself healthy in production?* — latency per
stage, pipeline success rate, outcome-settlement success, failure counts. These
are the numbers an on-call dashboard watches, entirely separate from learning.

`record()` writes one EngineHealthLog row per pipeline run (best-effort — logging
must never break the learner path). `metrics()` aggregates recent runs into
p50/p95/avg latency per stage + success rates. No decisions, no learner data.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

STAGES = ["kernel", "prediction", "delta", "explanation", "decision", "mission"]


def record(db, user_id: Optional[int], timings_ms: Dict[str, float],
           ok: bool = True, failed_stage: Optional[str] = None,
           source_event: Optional[str] = None, settle_ok: Optional[bool] = None) -> None:
    """Persist one pipeline run's health. Swallows all errors by design."""
    import models
    try:
        db.add(models.EngineHealthLog(
            user_id=user_id, source_event=source_event, ok=ok, failed_stage=failed_stage,
            kernel_ms=timings_ms.get("kernel"), prediction_ms=timings_ms.get("prediction"),
            delta_ms=timings_ms.get("delta"), explanation_ms=timings_ms.get("explanation"),
            decision_ms=timings_ms.get("decision"), mission_ms=timings_ms.get("mission"),
            total_ms=timings_ms.get("total"), settle_ok=settle_ok,
            created_at=datetime.datetime.utcnow()))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def _pct(values: List[float], p: float) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = max(0, min(len(vals) - 1, int(round((p / 100.0) * (len(vals) - 1)))))
    return round(vals[k], 1)


def _stage_stats(rows, attr: str) -> Dict[str, Any]:
    vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "avg_ms": round(sum(vals) / len(vals), 1),
            "p50_ms": _pct(vals, 50), "p95_ms": _pct(vals, 95), "max_ms": round(max(vals), 1)}


def metrics(db, since: Optional[datetime.datetime] = None, limit: int = 5000) -> Dict[str, Any]:
    """Aggregate recent pipeline runs into an ops snapshot. Empty-safe."""
    import models
    q = db.query(models.EngineHealthLog)
    if since is not None:
        q = q.filter(models.EngineHealthLog.created_at >= since)
    rows = q.order_by(models.EngineHealthLog.id.desc()).limit(limit).all()
    n = len(rows)
    if n == 0:
        return {"runs": 0, "note": "no pipeline runs recorded yet"}

    ok = sum(1 for r in rows if r.ok)
    settle_known = [r for r in rows if r.settle_ok is not None]
    settle_ok = sum(1 for r in settle_known if r.settle_ok)
    failed = [r for r in rows if not r.ok]
    fail_by_stage: Dict[str, int] = {}
    for r in failed:
        fail_by_stage[r.failed_stage or "unknown"] = fail_by_stage.get(r.failed_stage or "unknown", 0) + 1

    return {
        "runs": n,
        "success_rate": round(ok / n, 3),
        "failed_count": n - ok,
        "failed_by_stage": fail_by_stage,
        "settlement_success_rate": (round(settle_ok / len(settle_known), 3) if settle_known else None),
        "latency_ms": {stage: _stage_stats(rows, f"{stage}_ms") for stage in STAGES},
        "total_latency_ms": _stage_stats(rows, "total_ms"),
        "note": "read-only ops telemetry; measures the engine, not the learner",
    }
