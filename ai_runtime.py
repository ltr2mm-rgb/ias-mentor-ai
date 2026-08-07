"""AI Execution Runtime — the single chokepoint every LLM call in AIVORA passes
through (architecture §9). Providers *register* their adapters here; callers ask for
a **task**, and the runtime chooses provider + params, enforces a per-call timeout,
validates the output, runs the fallback chain, and logs a decision.

Rules from the architecture baseline (v6):
- The runtime EXECUTES; it never makes educational decisions.
- Every decision is logged with source / provider / reason / confidence / fallback.
- Nothing above this layer imports a vendor SDK — providers register into it.

This module is intentionally dependency-free (stdlib only) so it can be unit-tested
in isolation and never drags model SDKs into layers that shouldn't know about them.
"""
from __future__ import annotations

import json as _json
import logging
import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout

log = logging.getLogger("ai_runtime")

# ── Provider registry ────────────────────────────────────────────────────────
# name -> {"generate": fn(prompt, json_mode, system, model_tier) -> str,
#          "available": fn() -> bool}
_PROVIDERS: dict = {}


def register_provider(name: str, generate, available) -> None:
    """Register a provider adapter. `generate(prompt, json_mode, system, model_tier)`
    returns raw text; `available()` returns whether the provider can serve now."""
    _PROVIDERS[name] = {"generate": generate, "available": available}


def providers_available() -> dict:
    return {n: bool(p["available"]()) for n, p in _PROVIDERS.items()}


def test_provider(name: str, prompt: str = "Reply with the single word: OK") -> dict:
    """Directly probe one provider with a trivial prompt and return the raw result
    or the raw error message — the definitive way to diagnose a failing engine
    (billing vs model-access vs key vs transient) without waiting for a real call."""
    p = _PROVIDERS.get(name)
    if not p:
        return {"provider": name, "registered": False, "error": "not registered"}
    try:
        out = p["generate"](prompt=prompt, json_mode=False, system=None, model_tier="flash")
        return {"provider": name, "registered": True, "available": bool(p["available"]()),
                "ok": bool(out and str(out).strip()), "sample": (str(out) or "")[:200]}
    except Exception as e:
        return {"provider": name, "registered": True, "available": bool(p["available"]()),
                "ok": False, "error": str(e)[:600]}


# Default global priority (overridden per task). Gemini → OpenAI → DeepSeek.
DEFAULT_PRIORITY = ["gemini", "openai", "deepseek"]

# ── Task registry ────────────────────────────────────────────────────────────
# The seed of the learned routing policy (architecture §9, `routing_stats`). Today
# it is a STATIC evidence table; V2 makes it adaptive from real outcomes. Each task:
#   providers : ordered override (None = DEFAULT_PRIORITY)
#   json      : default json_mode
#   model     : tier hint — 'flash' (fast/cheap) | 'pro' (high-stakes reasoning)
#   timeout   : per-call seconds (None = global default)
_DEFAULT_TIMEOUT = float(os.getenv("AI_RUNTIME_TIMEOUT", "45"))

TASKS: dict = {
    "text.generic":       {"providers": None, "json": False, "model": "flash"},
    "mcq.generate":       {"providers": None, "json": True,  "model": "flash"},
    # cross-model verification prefers a *different* engine than the generator:
    "mcq.verify":         {"providers": ["openai", "gemini", "deepseek"], "json": True, "model": "flash"},
    "lesson.explain":     {"providers": None, "json": False, "model": "flash"},
    "pedagogy.asset":     {"providers": None, "json": False, "model": "flash"},
    "mentor.report":      {"providers": None, "json": False, "model": "pro"},
    "mistake.diagnose":   {"providers": None, "json": True,  "model": "pro"},
    "mains.evaluate":     {"providers": None, "json": True,  "model": "pro"},
    "interview.generate": {"providers": None, "json": False, "model": "pro"},
}


def _task_policy(task) -> dict:
    return TASKS.get(task or "", {})


# ── Decision log (in-memory ring buffer; a V2 step persists to routing_decisions) ─
_DECISIONS = deque(maxlen=500)


def recent_decisions(n: int = 50) -> list:
    """Most recent routing decisions, newest last — for admin/debug observability."""
    items = list(_DECISIONS)
    return items[-n:] if n else items


class RouteResult:
    __slots__ = ("output", "decision", "json")

    def __init__(self, output, decision, parsed=None):
        self.output = output        # raw provider text (callers may parse themselves)
        self.decision = decision    # {source, provider, reason, confidence, ...}
        self.json = parsed          # parsed object when json_mode succeeded, else None


def _order_for(task, prefer) -> list:
    """Build the ordered, available provider list for a task."""
    pol = _task_policy(task)
    base = list(pol.get("providers") or DEFAULT_PRIORITY)
    # any registered provider not explicitly listed can still be a tail fallback
    for p in _PROVIDERS:
        if p not in base:
            base.append(p)
    if prefer:
        base = [prefer] + [p for p in base if p != prefer]
    order = [p for p in base if p in _PROVIDERS and _PROVIDERS[p]["available"]()]
    if not order and _PROVIDERS:
        order = [next(iter(_PROVIDERS))]  # last resort: try something
    return order


def _validate(output, json_mode):
    """Non-empty check, plus JSON parse (with light salvage) when json_mode."""
    if not output or not str(output).strip():
        return False, None
    if not json_mode:
        return True, output
    s = str(output).strip()
    try:
        return True, _json.loads(s)
    except Exception:
        pass
    # salvage fenced / prefixed JSON: take the outermost {...} or [...]
    for lo, hi in ((s.find("{"), s.rfind("}")), (s.find("["), s.rfind("]"))):
        if lo != -1 and hi > lo:
            try:
                return True, _json.loads(s[lo:hi + 1])
            except Exception:
                continue
    return False, None


def _call_with_timeout(fn, timeout):
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(fn).result(timeout=timeout)


def _confidence(idx, task):
    """Static prior until `routing_stats` exists (architecture §9): the task's
    primary engine = high confidence; each fallback step lowers it."""
    return round(max(0.3, min(0.95, 0.9 - 0.2 * idx)), 2)


def route(task=None, prompt="", *, system=None, json_mode=None, model=None,
          prefer=None, spec=None, archetype=None) -> RouteResult:
    """Single AI entry point. Chooses a provider for `task`, executes with timeout +
    fallback, validates, logs the decision, and returns RouteResult(output, decision).

    `spec` / `archetype` are accepted now (the Teaching Engine passes them) and become
    routing inputs in V2; today they are recorded but do not change the static policy.
    Raises RuntimeError only if EVERY provider fails."""
    pol = _task_policy(task)
    if json_mode is None:
        json_mode = bool(pol.get("json", False))
    model_tier = model or pol.get("model", "flash")
    timeout = float(pol.get("timeout") or _DEFAULT_TIMEOUT)
    order = _order_for(task, prefer)

    t0 = time.time()
    attempts = []
    errors = {}
    for i, name in enumerate(order):
        gen = _PROVIDERS[name]["generate"]
        try:
            raw = _call_with_timeout(
                lambda g=gen: g(prompt=prompt, json_mode=json_mode,
                                system=system, model_tier=model_tier),
                timeout)
            ok, parsed = _validate(raw, json_mode)
            if ok:
                decision = {
                    "task": task, "source": "model", "provider": name,
                    "reason": "primary" if i == 0 else "fallback",
                    "fallback_used": i > 0, "attempts": attempts + [name],
                    "confidence": _confidence(i, task), "archetype": archetype,
                    "latency_ms": int((time.time() - t0) * 1000),
                }
                if errors:
                    decision["errors"] = errors
                _DECISIONS.append(decision)
                # .output stays the raw string (legacy callers parse themselves);
                # .json carries the parsed object when json_mode succeeded.
                return RouteResult(raw, decision, parsed if json_mode else None)
            attempts.append(f"{name}:invalid")
        except _FutureTimeout:
            attempts.append(f"{name}:timeout")
            errors[name] = f"timeout>{timeout}s"
            log.warning("ai_runtime task=%s provider=%s timeout(%ss)", task, name, timeout)
        except Exception as e:  # provider error → try the next one
            attempts.append(f"{name}:error")
            errors[name] = str(e)[:300]
            log.warning("ai_runtime task=%s provider=%s error: %s", task, name, e)

    decision = {"task": task, "source": "none", "provider": None,
                "reason": "all providers failed", "fallback_used": True,
                "attempts": attempts, "errors": errors, "confidence": 0.0,
                "archetype": archetype, "latency_ms": int((time.time() - t0) * 1000)}
    _DECISIONS.append(decision)
    raise RuntimeError(f"ai_runtime: no provider produced valid output for task={task} ({attempts})")
