from __future__ import annotations

import os
import time
from dataclasses import replace
from math import isfinite

from .storage.supabase_operational import (
    OperationalStoreUnavailable,
    SupabaseOperationalStore,
)
from .transient import TRANSIENT_RETRY_DELAYS, is_transient_backend_error


DEMO_SCORE_FLOOR_MIN = 50.01
DEMO_RISK_CEILING_PCT = 5.0


class DemoSupabaseOperationalStore(SupabaseOperationalStore):
    """DEMO store with bounded retry for idempotent reference bootstrap only."""

    def ensure_reference_symbols(self, pairs) -> None:
        last_exc: OperationalStoreUnavailable | None = None
        for attempt, delay in enumerate(TRANSIENT_RETRY_DELAYS, start=1):
            if delay:
                time.sleep(delay)
            try:
                super().ensure_reference_symbols(pairs)
                return
            except OperationalStoreUnavailable as exc:
                if not is_transient_backend_error(exc):
                    raise
                last_exc = exc
                if attempt == len(TRANSIENT_RETRY_DELAYS):
                    break
        raise OperationalStoreUnavailable(
            "fx_symbols reference bootstrap failed after transient retries"
        ) from last_exc


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


def apply_demo_calibration_risk(cfg, *, max_risk_pct: float = DEMO_RISK_CEILING_PCT):
    """Apply an explicit process-local DEMO risk target.

    Canonical LIVE safety remains unchanged. An explicit
    CTRADER_DEMO_RISK_PER_TRADE_PCT may raise only this DEMO wrapper up to 5%.
    """
    canonical_ceiling = float(max_risk_pct)
    if not isfinite(canonical_ceiling) or not 0.0 < canonical_ceiling <= DEMO_RISK_CEILING_PCT:
        raise SystemExit("CTRADER_DEMO_RISK_CEILING_OUT_OF_RANGE")
    raw = os.getenv("CTRADER_DEMO_RISK_PER_TRADE_PCT", "").strip()
    requested = float(cfg.risk["risk_per_trade_pct"]) if not raw else float(raw)
    ceiling = min(
        DEMO_RISK_CEILING_PCT,
        max(canonical_ceiling, requested if raw else canonical_ceiling),
    )
    if not isfinite(requested) or not 0.0 < requested <= ceiling:
        raise SystemExit("CTRADER_DEMO_RISK_PER_TRADE_OUT_OF_RANGE")
    risk = dict(cfg.risk)
    risk["risk_per_trade_pct"] = requested
    risk["max_risk_per_trade_pct"] = ceiling
    return replace(cfg, risk=risk), requested


def apply_demo_deep_analysis_top(cfg):
    """Apply DEMO deep-shortlist width, capped by the active market universe."""
    raw = os.getenv("CTRADER_DEMO_DEEP_ANALYSIS_TOP", "").strip()
    if not raw:
        return cfg
    try:
        requested = int(raw)
    except ValueError as exc:
        raise SystemExit("CTRADER_DEMO_DEEP_ANALYSIS_TOP_INVALID") from exc
    canonical = int(cfg.strategy["selection"]["deep_analysis_top"])
    universe = len(cfg.pairs)
    if not canonical <= requested <= 10:
        raise SystemExit("CTRADER_DEMO_DEEP_ANALYSIS_TOP_OUT_OF_RANGE")
    effective = min(requested, universe)
    if effective <= 0:
        raise SystemExit("CTRADER_DEMO_DEEP_ANALYSIS_TOP_OUT_OF_RANGE")
    selection = dict(cfg.strategy["selection"])
    selection["deep_analysis_top"] = effective
    strategy = dict(cfg.strategy)
    strategy["selection"] = selection
    return replace(cfg, strategy=strategy)


def apply_demo_calibration_policy_risk(
    policy, *, max_risk_pct: float = DEMO_RISK_CEILING_PCT
):
    """Raise only the already-validated DEMO process risk ceiling."""
    ceiling = float(max_risk_pct)
    if not isfinite(ceiling) or not 0.0 < ceiling <= DEMO_RISK_CEILING_PCT:
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
    store = DemoSupabaseOperationalStore.from_env(
        execution_ready_score_floor=max(65.0, floor),
    )
    store.execution_ready_score_floor = floor
    return store
