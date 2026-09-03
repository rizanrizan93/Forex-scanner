from __future__ import annotations

import os
from dataclasses import replace
from math import isfinite

from .storage.supabase_operational import SupabaseOperationalStore


DEMO_SCORE_FLOOR_MIN = 50.01


def apply_demo_calibration_threshold(cfg):
    """Apply a DEMO-only execution threshold without changing canonical limits."""
    production_min = float(cfg.scoring["states"]["execution_candidate_min"])
    raw = os.getenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", "").strip()
    demo_min = production_min if not raw else float(raw)
    if not isfinite(demo_min) or not DEMO_SCORE_FLOOR_MIN <= demo_min <= production_min:
        raise SystemExit("CTRADER_DEMO_CALIBRATION_THRESHOLD_OUT_OF_RANGE")
    states = dict(cfg.scoring["states"])
    states["execution_candidate_min"] = demo_min
    scoring = dict(cfg.scoring)
    scoring["states"] = states
    return replace(cfg, scoring=scoring), production_min


def apply_demo_calibration_risk(cfg, *, max_risk_pct: float = 1.0):
    """Apply an explicit process-local DEMO risk target.

    Canonical configuration remains unchanged. An explicit
    CTRADER_DEMO_RISK_PER_TRADE_PCT may raise the calibration ceiling up to 1%
    only in the DEMO wrappers that call this helper after environment checks.
    """
    canonical_ceiling = float(max_risk_pct)
    if not isfinite(canonical_ceiling) or canonical_ceiling <= 0.0:
        raise SystemExit("CTRADER_DEMO_RISK_CEILING_OUT_OF_RANGE")
    raw = os.getenv("CTRADER_DEMO_RISK_PER_TRADE_PCT", "").strip()
    requested = float(cfg.risk["risk_per_trade_pct"]) if not raw else float(raw)
    ceiling = min(1.0, max(canonical_ceiling, requested if raw else canonical_ceiling))
    if not isfinite(requested) or not 0.0 < requested <= ceiling:
        raise SystemExit("CTRADER_DEMO_RISK_PER_TRADE_OUT_OF_RANGE")
    risk = dict(cfg.risk)
    risk["risk_per_trade_pct"] = requested
    risk["max_risk_per_trade_pct"] = ceiling
    return replace(cfg, risk=risk), requested


def apply_demo_deep_analysis_top(cfg):
    """Expand only the DEMO technical deep shortlist, bounded by the universe."""
    raw = os.getenv("CTRADER_DEMO_DEEP_ANALYSIS_TOP", "").strip()
    if not raw:
        return cfg
    try:
        requested = int(raw)
    except ValueError as exc:
        raise SystemExit("CTRADER_DEMO_DEEP_ANALYSIS_TOP_INVALID") from exc
    canonical = int(cfg.strategy["selection"]["deep_analysis_top"])
    universe = len(cfg.pairs)
    if not canonical <= requested <= min(10, universe):
        raise SystemExit("CTRADER_DEMO_DEEP_ANALYSIS_TOP_OUT_OF_RANGE")
    selection = dict(cfg.strategy["selection"])
    selection["deep_analysis_top"] = requested
    strategy = dict(cfg.strategy)
    strategy["selection"] = selection
    return replace(cfg, strategy=strategy)


def apply_demo_calibration_policy_risk(policy, *, max_risk_pct: float = 1.0):
    """Raise only the already-validated DEMO process risk ceiling."""
    ceiling = float(max_risk_pct)
    if not isfinite(ceiling) or not 0.0 < ceiling <= 1.0:
        raise SystemExit("CTRADER_DEMO_POLICY_RISK_CEILING_OUT_OF_RANGE")
    demo_safety = dict(policy.demo_safety)
    demo_safety["max_risk_pct"] = ceiling
    return replace(policy, demo_safety=demo_safety)


def build_demo_calibration_store(*, execution_ready_score_floor: float):
    """Build the backend store with an isolated DEMO persistence floor >50.

    SupabaseOperationalStore deliberately keeps its canonical constructor floor
    at 65. The DEMO calibration adapter bootstraps through that invariant, then
    narrows only this process-local persistence floor after explicit validation.
    """
    floor = float(execution_ready_score_floor)
    if not isfinite(floor) or not DEMO_SCORE_FLOOR_MIN <= floor <= 100.0:
        raise SystemExit("CTRADER_DEMO_CALIBRATION_STORE_FLOOR_OUT_OF_RANGE")
    store = SupabaseOperationalStore.from_env(
        execution_ready_score_floor=max(65.0, floor),
    )
    store.execution_ready_score_floor = floor
    return store
