from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any

from .cli import _apply_demo_technical_only_profile, _demo_spread_limit_overrides
from .config import ProjectConfig, load_project_config
from .demo_calibration import (
    apply_demo_calibration_risk,
    apply_demo_calibration_threshold,
    apply_demo_deep_analysis_top,
    build_demo_calibration_store,
)
from .demo_correlation_evidence import EvidenceProductionGuardResolver
from .demo_market_schedule import apply_demo_market_schedule
from .demo_signal_producer import ExplicitDemoTechnicalSignalProducer
from .demo_technical_producer import _apply_demo_chase_block, _persist_geometry_events
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy

UTC = timezone.utc
_ALLOWED_STATES = {"EXECUTION_READY", "ARMED", "SETUP_FORMING", "WATCH"}
_STATE_PRIORITY = {"EXECUTION_READY": 4, "ARMED": 3, "SETUP_FORMING": 2, "WATCH": 1}


def _safe_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name}_INVALID") from exc
    if not minimum <= value <= maximum:
        raise SystemExit(f"{name}_OUT_OF_RANGE")
    return value


def _safe_float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name}_INVALID") from exc
    if not isfinite(value) or not minimum <= value <= maximum:
        raise SystemExit(f"{name}_OUT_OF_RANGE")
    return value


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def recent_candidate_symbols(
    store,
    cfg: ProjectConfig,
    *,
    now: datetime,
    lookback_minutes: int,
    max_symbols: int,
) -> tuple[str, ...]:
    """Choose symbols only; every candidate is fully revalidated on fresh data."""
    response = (
        store.client.table("signals")
        .select("observed_at,symbol,state,final_score")
        .order("observed_at", desc=True)
        .limit(250)
        .execute()
    )
    cutoff = now.astimezone(UTC) - timedelta(minutes=int(lookback_minutes))
    allowed_symbols = set(cfg.pair_map)
    best: dict[str, tuple[int, float, datetime]] = {}
    for raw in response.data or []:
        row = dict(raw)
        symbol = str(row.get("symbol", "") or "").upper().strip()
        state = str(row.get("state", "") or "").upper().strip()
        observed = _dt(row.get("observed_at"))
        if symbol not in allowed_symbols or state not in _ALLOWED_STATES or observed is None:
            continue
        if observed < cutoff or observed > now.astimezone(UTC) + timedelta(seconds=1):
            continue
        try:
            score = float(row.get("final_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        key = (_STATE_PRIORITY[state], score, observed)
        if symbol not in best or key > best[symbol]:
            best[symbol] = key
    ordered = sorted(best, key=lambda symbol: best[symbol], reverse=True)
    return tuple(ordered[: int(max_symbols)])


def _subset_cfg(cfg: ProjectConfig, symbols: tuple[str, ...]) -> ProjectConfig:
    selected = tuple(cfg.pair_map[symbol] for symbol in symbols if symbol in cfg.pair_map)
    return replace(cfg, pairs=selected)


def run() -> int:
    cfg = load_project_config(None)
    cfg, market_schedule_mode = apply_demo_market_schedule(cfg)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("CTRADER_FAST_CANDIDATE_PRODUCER_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_FAST_CANDIDATE_PRODUCER_REQUIRE_DEMO")

    cfg, production_execution_min = apply_demo_calibration_threshold(cfg)
    cfg = _apply_demo_technical_only_profile(cfg)
    cfg, production_chase_block = _apply_demo_chase_block(cfg)
    cfg = apply_demo_deep_analysis_top(cfg)
    cfg, demo_risk_pct = apply_demo_calibration_risk(
        cfg,
        max_risk_pct=float(policy.demo_safety["max_risk_pct"]),
    )
    demo_execution_min = float(cfg.scoring["states"]["execution_candidate_min"])
    max_symbols = _safe_int_env(
        "CTRADER_DEMO_FAST_MAX_SYMBOLS", 8, minimum=1, maximum=10
    )
    lookback_minutes = _safe_int_env(
        "CTRADER_DEMO_FAST_CANDIDATE_LOOKBACK_MINUTES", 45, minimum=5, maximum=180
    )
    request_delay = _safe_float_env(
        "CTRADER_DEMO_HISTORICAL_REQUEST_DELAY_SECONDS", 0.60, minimum=0.20, maximum=2.0
    )

    store = build_demo_calibration_store(execution_ready_score_floor=demo_execution_min)
    now = datetime.now(tz=UTC)
    symbols = recent_candidate_symbols(
        store,
        cfg,
        now=now,
        lookback_minutes=lookback_minutes,
        max_symbols=max_symbols,
    )
    if not symbols:
        store.write_heartbeat(
            "ctrader_demo_fast_candidate_producer",
            healthy=True,
            lag_seconds=0.0,
            details={
                "mode": "FAST_REVALIDATION",
                "candidate_symbols": [],
                "candidate_count": 0,
                "lookback_minutes": lookback_minutes,
                "market_schedule_mode": market_schedule_mode,
                "result": "NO_RECENT_CANDIDATES",
            },
        )
        print(
            "CTRADER_DEMO_FAST_CANDIDATE_PRODUCER_OK "
            f"candidates=0 lookback_min={lookback_minutes} result=NO_RECENT_CANDIDATES"
        )
        return 0

    cfg = _subset_cfg(cfg, symbols)
    store.ensure_reference_symbols(cfg.pairs)
    feed = build_ctrader_research_feed(policy, symbols)
    spread_overrides = _demo_spread_limit_overrides(cfg)
    guard_resolver = EvidenceProductionGuardResolver(
        cfg,
        feed,
        calendar_provider=None,
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        max_spread_pips=float(policy.reconciliation["max_execution_spread_pips"]),
        demo_max_risk_pct=float(policy.demo_safety["max_risk_pct"]),
        max_spread_pips_by_symbol=spread_overrides,
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        clock=lambda: datetime.now(tz=UTC),
        disabled_guards=("NEWS_BLOCK",),
    )
    producer = ExplicitDemoTechnicalSignalProducer(
        cfg,
        feed,
        store,
        code_version=os.getenv("GITHUB_SHA", "LOCAL"),
        historical_request_delay_seconds=request_delay,
        signal_ttl_seconds=min(300.0, float(policy.order.get("max_signal_age_seconds", 300))),
        max_quote_age_seconds=float(policy.ctrader["max_quote_age_seconds"]),
        quote_wait_timeout_seconds=float(policy.ctrader["quote_wait_timeout_seconds"]),
        quote_poll_seconds=float(policy.ctrader["quote_poll_seconds"]),
        guard_resolver=guard_resolver,
        technical_only_scalping=True,
    )

    started = datetime.now(tz=UTC)
    try:
        report = producer.run_once()
        persisted = store.list_signals_for_run(report.run_id)
        analyses = {
            item.symbol: item
            for item in (
                producer.last_deep_report.analyses if producer.last_deep_report else ()
            )
        }
        geometry_written, geometry_missing = _persist_geometry_events(
            store=store,
            policy=policy,
            persisted=persisted,
            analyses=analyses,
        )
        elapsed = (datetime.now(tz=UTC) - started).total_seconds()
        store.write_heartbeat(
            "ctrader_demo_fast_candidate_producer",
            healthy=True,
            lag_seconds=0.0,
            details={
                "mode": "FAST_REVALIDATION",
                "candidate_symbols": list(symbols),
                "candidate_count": len(symbols),
                "lookback_minutes": lookback_minutes,
                "request_delay_seconds": request_delay,
                "market_schedule_mode": market_schedule_mode,
                "signals_written": report.signals_written,
                "execution_ready": report.execution_ready,
                "geometry_written": geometry_written,
                "geometry_missing_nonready": geometry_missing,
                "elapsed_seconds": elapsed,
                "production_execution_min": production_execution_min,
                "demo_execution_min": demo_execution_min,
                "production_chase_block_atr": production_chase_block,
                "risk_per_trade_pct": demo_risk_pct,
            },
        )
        print(
            "CTRADER_DEMO_FAST_CANDIDATE_PRODUCER_OK "
            f"candidates={len(symbols)} symbols={','.join(symbols)} "
            f"market={report.market_symbols}/{len(symbols)} ranked={report.ranked_pairs} "
            f"deep={report.deep_candidates} signals={report.signals_written} "
            f"execution_ready={report.execution_ready} geometry={geometry_written} "
            f"elapsed_s={elapsed:.1f} request_delay_s={request_delay:g}"
        )
        return 0
    finally:
        close = getattr(feed, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(run())
