"""
policy_confidence.py — Confidence engine (M5 Phase A, EQ-08 + dependency of EQ-04..06).

Answers ONE question — "How certain are we?" — as a SIBLING of the scorecard
(which answers "What happened?"), never its child. The promotion engine
("Should the default change?") consumes this module's stable CONTRACT and never
sees the mathematics behind it.

FROZEN INTERFACE (what promotion depends on):

    evaluate_metric(default_sample, candidate_sample, metric_type) -> {
        "metric_type": "proportion" | "continuous",
        "method":      "wilson-newcombe" | "bootstrap-percentile" | ...,
        "default_stat", "candidate_stat",     # point estimates
        "effect":      candidate_stat - default_stat,
        "interval":    [low, high],           # CI of the DIFFERENCE (candidate-default)
        "sample_size": {"default", "candidate", "min"},
        "supported":   {"higher", "lower", "distinguishable"},  # direction-agnostic
        "alpha":       0.05,
    }

The math BELOW this interface is deliberately replaceable (per the M5 philosophy:
freeze the contract, keep the implementation swappable). First implementation,
chosen conservative rather than sophisticated:
  • proportions  → Wilson score interval per proportion, combined via Newcombe's
    method for the difference (robust for small n; no normal approximation).
  • continuous   → percentile bootstrap of the difference of means (no parametric
    assumption — mission counts are small, gains skewed, spans non-normal, and
    future planners will reshape these distributions again).
Six months from now Wilson→Agresti–Coull or bootstrap→BCa changes NOTHING above
this line, because promotion reads only `supported` / `sample_size` / `interval`.

DETERMINISM (required by EQ-07): the bootstrap RNG is seeded from the sample data
itself, so `evaluate_metric` is a pure function of its inputs — same samples →
byte-identical interval. No wall-clock, no unseeded RNG.

`supported` is direction-agnostic on purpose: it reports facts about the
difference (is the CI entirely above 0? entirely below 0?). WHICH direction is
"better" is a governance concern and lives in policy_promotion.py.
"""
from __future__ import annotations

import math
import zlib
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

CONFIDENCE_VERSION = "confidence-1.0"
BOOTSTRAP_ITERS = 2000
DEFAULT_ALPHA = 0.05

# metric_key → statistical family (proportion vs continuous). Matches the scorecard
# metric catalogue; retention joins as a continuous metric when its read-view lands.
METRIC_TYPES: Dict[str, str] = {
    "completion_rate": "proportion",
    "avg_mastery_gain": "continuous",
    "avg_attempts_on_target": "continuous",
    "avg_elapsed_seq": "continuous",
}

_Z = {0.05: 1.959964, 0.10: 1.644854, 0.01: 2.575829}


def _z_for(alpha: float) -> float:
    return _Z.get(round(alpha, 4), 1.959964)


def _r(x: Optional[float], nd: int = 6) -> Optional[float]:
    return None if x is None else round(float(x), nd)


# ── proportions: Wilson score interval + Newcombe difference ─────────────────
def wilson_interval(successes: int, n: int, z: float) -> Tuple[float, float]:
    """Wilson score interval for a single proportion. Robust at small n and near
    0/1 (unlike the normal approximation)."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (center - half, center + half)


def _prop(sample) -> Tuple[int, int]:
    """Accept a list of 0/1 or a (successes, n) tuple → (successes, n)."""
    if isinstance(sample, tuple) and len(sample) == 2:
        return int(sample[0]), int(sample[1])
    lst = list(sample)
    return int(sum(1 for x in lst if x)), len(lst)


def _newcombe_diff(sC: int, nC: int, sD: int, nD: int, z: float) -> Tuple[Optional[float], Optional[float]]:
    """Newcombe method 10 CI for the difference (candidate − default) of two
    independent proportions, built from each proportion's Wilson interval."""
    if nC <= 0 or nD <= 0:
        return (None, None)
    pC, pD = sC / nC, sD / nD
    lC, uC = wilson_interval(sC, nC, z)
    lD, uD = wilson_interval(sD, nD, z)
    effect = pC - pD
    lo = effect - math.sqrt((pC - lC) ** 2 + (uD - pD) ** 2)
    hi = effect + math.sqrt((uC - pC) ** 2 + (pD - lD) ** 2)
    return (lo, hi)


# ── continuous: deterministic percentile bootstrap of the mean difference ────
def _stable_seed(*samples: Sequence[float]) -> int:
    """A reproducible seed derived from the sample values, so the bootstrap is
    data-dependent yet identical on replay (EQ-07). Avoids Python's salted hash()."""
    payload = "|".join(",".join("%.6f" % float(x) for x in s) for s in samples)
    return zlib.crc32(payload.encode("utf-8")) & 0xFFFFFFFF


def _bootstrap_diff_ci(default: List[float], candidate: List[float],
                       iters: int, alpha: float, seed: int) -> Tuple[Optional[float], Optional[float]]:
    """Percentile CI for mean(candidate) − mean(default) via seeded bootstrap."""
    nD, nC = len(default), len(candidate)
    if nD == 0 or nC == 0:
        return (None, None)
    rng = random.Random(seed)
    diffs = []
    for _ in range(iters):
        mD = sum(default[rng.randrange(nD)] for _ in range(nD)) / nD
        mC = sum(candidate[rng.randrange(nC)] for _ in range(nC)) / nC
        diffs.append(mC - mD)
    diffs.sort()
    lo_idx = int((alpha / 2.0) * iters)
    hi_idx = max(0, int((1.0 - alpha / 2.0) * iters) - 1)
    return (diffs[lo_idx], diffs[hi_idx])


# ── the frozen interface ─────────────────────────────────────────────────────
def evaluate_metric(default_sample, candidate_sample, metric_type: str,
                    alpha: float = DEFAULT_ALPHA) -> Dict[str, Any]:
    """Compare candidate vs default on one metric. Direction-agnostic: returns
    facts about the difference; the caller decides which direction is 'better'."""
    z = _z_for(alpha)

    if metric_type == "proportion":
        sD, nD = _prop(default_sample)
        sC, nC = _prop(candidate_sample)
        dstat = (sD / nD) if nD else None
        cstat = (sC / nC) if nC else None
        lo, hi = _newcombe_diff(sC, nC, sD, nD, z)
        method = "wilson-newcombe"
        nrec = {"default": nD, "candidate": nC, "min": min(nD, nC)}
    else:  # continuous
        a = [float(x) for x in default_sample]
        b = [float(x) for x in candidate_sample]
        dstat = (sum(a) / len(a)) if a else None
        cstat = (sum(b) / len(b)) if b else None
        if a and b:
            lo, hi = _bootstrap_diff_ci(a, b, BOOTSTRAP_ITERS, alpha, _stable_seed(a, b))
        else:
            lo, hi = (None, None)
        method = "bootstrap-percentile"
        nrec = {"default": len(a), "candidate": len(b), "min": min(len(a), len(b))}

    effect = (cstat - dstat) if (dstat is not None and cstat is not None) else None
    supported = {
        "higher": (lo is not None and lo > 0),   # candidate significantly greater
        "lower": (hi is not None and hi < 0),    # candidate significantly less
    }
    supported["distinguishable"] = supported["higher"] or supported["lower"]

    return {
        "metric_type": metric_type,
        "method": method,
        "default_stat": _r(dstat),
        "candidate_stat": _r(cstat),
        "effect": _r(effect),
        "interval": [_r(lo), _r(hi)],
        "sample_size": nrec,
        "supported": supported,
        "alpha": alpha,
    }


# ── sample extraction from outcomes (sibling of aggregate_by_policy) ─────────
def samples_by_policy(outcomes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-policy RAW samples for each metric (what the confidence engine needs;
    the aggregate's averages are not enough for a bootstrap). Also reports the
    evaluation window (seq span + mission count) so the confidence layer can state
    over what data it judged — the third thing EQ-08 requires alongside n and CI."""
    by: Dict[str, Any] = {}
    for o in outcomes:
        pol = o.get("policy_version") or "unknown"
        g = by.setdefault(pol, {
            "completion_rate": [], "avg_mastery_gain": [],
            "avg_attempts_on_target": [], "avg_elapsed_seq": [],
            "_seqs": [], "_missions": 0,
        })
        g["_missions"] += 1
        g["completion_rate"].append(1 if o.get("state") == "COMPLETED" else 0)
        if o.get("mastery_gain") is not None:
            g["avg_mastery_gain"].append(float(o["mastery_gain"]))
        g["avg_attempts_on_target"].append(int(o.get("attempts_on_target") or 0))
        if o.get("elapsed_seq") is not None:
            g["avg_elapsed_seq"].append(int(o["elapsed_seq"]))
        for k in ("created_seq", "terminal_seq"):
            if o.get(k) is not None:
                g["_seqs"].append(int(o[k]))
    for pol, g in by.items():
        seqs = g.pop("_seqs")
        g["window"] = {
            "seq_low": min(seqs) if seqs else None,
            "seq_high": max(seqs) if seqs else None,
            "missions": g["_missions"],
        }
    return by


# ── EQ-08: confidence-enriched scorecard (base scorecard + how-certain) ──────
def enrich_scorecard(scorecard: Dict[str, Any],
                     default_samples: Dict[str, Any],
                     candidate_samples: Dict[str, Any],
                     default_window: Optional[Dict[str, Any]] = None,
                     candidate_window: Optional[Dict[str, Any]] = None,
                     alpha: float = DEFAULT_ALPHA) -> Dict[str, Any]:
    """Join a base (pure) scorecard with confidence, WITHOUT mutating it. Every
    row gains {effect, interval, sample_size, method}; the artifact gains the
    evaluation window. This is the human-facing 'what happened + how certain'
    view — still NOT a promotion decision (that stays in policy_promotion.py)."""
    rows = []
    for r in scorecard.get("rows", []):
        k = r["metric"]
        mtype = METRIC_TYPES.get(k, "continuous")
        ev = evaluate_metric(default_samples.get(k, []), candidate_samples.get(k, []),
                             mtype, alpha=alpha)
        nr = dict(r)
        nr["effect"] = ev["effect"]
        nr["interval"] = ev["interval"]
        nr["sample_size"] = ev["sample_size"]
        nr["method"] = ev["method"]
        rows.append(nr)
    out = dict(scorecard)
    out["rows"] = rows
    out["confidence_version"] = CONFIDENCE_VERSION
    out["alpha"] = alpha
    out["evaluation_window"] = {"default": default_window, "candidate": candidate_window}
    return out
