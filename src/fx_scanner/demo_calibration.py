from __future__ import annotations

import os
from dataclasses import replace
from math import isfinite

from .storage.supabase_operational import SupabaseOperationalStore


def apply_demo_calibration_threshold(cfg):
    """Apply a DEMO-only execution threshold without changing canonical limits."""
    production_min = float(cfg.scoring["states"]["execution_candidate_min"])
    raw = os.getenv("CTRADER_DEMO_EXECUTION_CANDIDATE_MIN", "").strip()
    demo_min = production_min if not raw else float(raw)
    if not isfinite(demo_min) or not 60.0 <= demo_min <= production_min:
        raise SystemExit("CTRADER_DEMO_CALIBRATION_THRESHOLD_OUT_OF_RANGE")
    states = dict(cfg.scoring["states"])
    states["execution_candidate_min"] = demo_min
    scoring = dict(cfg.scoring)
    scoring["states"] = states
    return replace(cfg, scoring=scoring), production_min


def apply_demo_calibration_risk(cfg, *, max_risk_pct: float):
    """Apply a process-local DEMO risk target while keeping canonical risk unchanged."""
    ceiling = float(max_risk_pct)
    if not isfinite(ceiling) or not 0.0 < ceiling <= 1.0:
        raise SystemExit("CTRADER_DEMO_RISK_CEILING_OUT_OF_RANGE")
    raw = os.getenv("CTRADER_DEMO_RISK_PER_TRADE_PCT", "").strip()
    requested = float(cfg.risk["risk_per_trade_pct"]) if not raw else float(raw)
    if not isfinite(requested) or not 0.0 < requested <= ceiling:
        raise SystemExit("CTRADER_DEMO_RISK_PER_TRADE_OUT_OF_RANGE")
    risk = dict(cfg.risk)
    risk["risk_per_trade_pct"] = requested
    risk["max_risk_per_trade_pct"] = ceiling
    return replace(cfg, risk=risk), requested


def build_demo_calibration_store(*, execution_ready_score_floor: float):
    """Build the backend store with an isolated DEMO persistence floor >=60.

    SupabaseOperationalStore deliberately keeps its canonical constructor floor
    at 65. The DEMO calibration adapter bootstraps through that invariant, then
    narrows only this process-local persistence floor after explicit validation.
    """
    floor = float(execution_ready_score_floor)
    if not isfinite(floor) or not 60.0 <= floor <= 100.0:
        raise SystemExit("CTRADER_DEMO_CALIBRATION_STORE_FLOOR_OUT_OF_RANGE")
    store = SupabaseOperationalStore.from_env(
        execution_ready_score_floor=max(65.0, floor),
    )
    store.execution_ready_score_floor = floor
    return store
