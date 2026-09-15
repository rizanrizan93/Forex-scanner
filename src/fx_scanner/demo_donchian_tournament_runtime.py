from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any

import yaml

from .config import load_project_config
from .demo_donchian_adaptive_tournament import (
    TOURNAMENT_VERSION,
    TournamentCosts,
    choose_candidate,
    evaluate_variant,
    parameter_grid,
    simulate_variant,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_donchian_adaptive_tournament"
EXCLUDED_24_7_SYMBOLS = frozenset({"BTCUSD", "ETHUSD", "SOLUSD"})
DEFAULT_HISTORY_BARS = 2200
MIN_HISTORY_BARS = 800
MAX_HISTORY_BARS = 5000
REQUEST_DELAY_SECONDS = 0.20
MIN_SYMBOL_COVERAGE = 0.80


def _validation_cfg() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    value = yaml.safe_load((root / "config" / "validation.yaml").read_text())
    if not isinstance(value, dict):
        raise SystemExit("DONCHIAN_VALIDATION_CONFIG_INVALID")
    return value


def _history_count() -> int:
    raw = os.getenv("CTRADER_DONCHIAN_HISTORY_BARS", str(DEFAULT_HISTORY_BARS)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("CTRADER_DONCHIAN_HISTORY_BARS_INVALID") from exc
    if not MIN_HISTORY_BARS <= value <= MAX_HISTORY_BARS:
        raise SystemExit("CTRADER_DONCHIAN_HISTORY_BARS_OUT_OF_RANGE")
    return value


def _research_symbols(cfg) -> tuple[str, ...]:
    configured = tuple(pair.symbol for pair in cfg.pairs if pair.symbol not in EXCLUDED_24_7_SYMBOLS)
    override = os.getenv("CTRADER_DONCHIAN_SYMBOLS", "").strip()
    if not override:
        return configured
    requested = tuple(dict.fromkeys(token.strip().upper() for token in override.split(",") if token.strip()))
    invalid = sorted(set(requested) - set(configured))
    if invalid:
        raise SystemExit(f"CTRADER_DONCHIAN_SYMBOLS_INVALID:{','.join(invalid)}")
    if not requested:
        raise SystemExit("CTRADER_DONCHIAN_SYMBOLS_EMPTY")
    return requested


def _costs(validation_cfg: dict[str, Any], *, stressed: bool) -> TournamentCosts:
    base = validation_cfg["costs"]["base"]
    costs = TournamentCosts(
        spread_pips=float(base["spread_pips"]),
        slippage_pips=float(base["slippage_pips"]),
        commission_pips_round_trip=float(base["commission_pips_round_trip"]),
        swap_pips_per_day=float(base["swap_pips_per_day"]),
    )
    if not stressed:
        return costs
    return costs.stressed(
        spread_multiplier=float(validation_cfg["costs"]["stress_spread_multiplier"]),
        slippage_multiplier=float(validation_cfg["costs"]["stress_slippage_multiplier"]),
    )


def _fetch_h1_history(feed, *, symbols: tuple[str, ...], history_count: int, as_of: datetime):
    # Calendar window is deliberately wider than requested trading bars so
    # weekends/closures do not silently reduce the H1 sample.
    start = as_of - timedelta(seconds=history_count * 3600 * 2)
    bars_by_symbol: dict[str, tuple] = {}
    failures: dict[str, str] = {}
    for symbol in symbols:
        try:
            fetched = tuple(
                feed.historical_bars(
                    symbol,
                    "H1",
                    from_time=start,
                    to_time=as_of,
                    count=history_count,
                )
            )
            closed = _closed_bars(fetched, as_of=as_of, timeframe_seconds=3600)
            if len(closed) < MIN_HISTORY_BARS:
                failures[symbol] = f"INSUFFICIENT_H1:{len(closed)}<{MIN_HISTORY_BARS}"
            else:
                bars_by_symbol[symbol] = tuple(closed)
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}:{exc}"
        sleep(REQUEST_DELAY_SECONDS)
    return bars_by_symbol, failures


def _finite_top(evaluations, limit: int = 10) -> list[dict[str, Any]]:
    values = sorted(
        evaluations,
        key=lambda row: (
            row.preliminary_eligible,
            row.walk_forward_pass_fraction,
            row.stressed_metrics.expectancy_r if row.stressed_metrics.expectancy_r is not None else -999.0,
            row.stressed_metrics.profit_factor if row.stressed_metrics.profit_factor is not None else -999.0,
            row.base_metrics.expectancy_r if row.base_metrics.expectancy_r is not None else -999.0,
            -row.base_metrics.max_drawdown_r,
        ),
        reverse=True,
    )
    return [row.payload() for row in values[:limit]]


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("DONCHIAN_TOURNAMENT_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("DONCHIAN_TOURNAMENT_REQUIRE_DEMO")

    validation_cfg = _validation_cfg()
    symbols = _research_symbols(cfg)
    history_count = _history_count()
    pair_by_symbol = {pair.symbol: pair for pair in cfg.pairs}
    feed = build_ctrader_research_feed(policy, symbols)
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    bars_by_symbol: dict[str, tuple] = {}
    failures: dict[str, str] = {}
    try:
        feed.ensure_connected()
        bars_by_symbol, failures = _fetch_h1_history(
            feed,
            symbols=symbols,
            history_count=history_count,
            as_of=as_of,
        )
    finally:
        try:
            feed.close()
        except Exception:
            pass

    coverage = 0.0 if not symbols else len(bars_by_symbol) / len(symbols)
    base_costs = _costs(validation_cfg, stressed=False)
    stressed_costs = _costs(validation_cfg, stressed=True)
    evaluations = []
    symbol_trade_counts: dict[str, dict[str, int]] = {}

    for variant in parameter_grid():
        base_trades = []
        stressed_trades = []
        for symbol, bars in bars_by_symbol.items():
            pip_size = float(pair_by_symbol[symbol].pip_size)
            base_rows = simulate_variant(
                bars,
                symbol=symbol,
                pip_size=pip_size,
                variant=variant,
                costs=base_costs,
            )
            stress_rows = simulate_variant(
                bars,
                symbol=symbol,
                pip_size=pip_size,
                variant=variant,
                costs=stressed_costs,
            )
            base_trades.extend(base_rows)
            stressed_trades.extend(stress_rows)
            symbol_trade_counts.setdefault(symbol, {})[variant.strategy_id] = len(base_rows)
        evaluations.append(
            evaluate_variant(
                variant=variant,
                base_trades=base_trades,
                stressed_trades=stressed_trades,
                validation_cfg=validation_cfg,
            )
        )

    decision = choose_candidate(evaluations, validation_cfg)
    if coverage < MIN_SYMBOL_COVERAGE:
        decision = {
            **decision,
            "stage": "DATA_INSUFFICIENT",
            "historical_pass": False,
            "parameter_stability_pass": False,
            "reason": "SYMBOL_COVERAGE_BELOW_GATE",
        }

    details = {
        "tournament_version": TOURNAMENT_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "risk_mutation": False,
        "sltp_mutation": False,
        "live_unlock": False,
        "history_bars_requested": history_count,
        "symbols_requested": list(symbols),
        "symbols_available": sorted(bars_by_symbol),
        "symbol_coverage": coverage,
        "minimum_symbol_coverage": MIN_SYMBOL_COVERAGE,
        "fetch_failures": failures,
        "parameter_grid_size": len(parameter_grid()),
        "parameter_contract": {
            "lookbacks": [10, 20, 30, 55],
            "atr_periods": [10, 14, 20],
            "breakout_buffers_atr": [0.0, 0.10, 0.20, 0.30],
            "stop_atr": 2.0,
            "reward_r": 2.0,
            "max_hold_h1": 72,
            "entry": "NEXT_H1_OPEN_WITH_ADVERSE_SPREAD_AND_SLIPPAGE",
            "overlap": "ONE_POSITION_PER_SYMBOL_PER_VARIANT",
        },
        "validation_contract": {
            "walk_forward": validation_cfg["walk_forward"],
            "stress_acceptance": validation_cfg["stress_acceptance"],
            "parameter_perturbation": validation_cfg["parameter_perturbation"],
            "costs": validation_cfg["costs"],
        },
        "decision": decision,
        "top_variants": _finite_top(evaluations),
        "closed_h1_counts": {symbol: len(rows) for symbol, rows in sorted(bars_by_symbol.items())},
        "symbol_trade_counts_for_selected": (
            {
                symbol: counts.get(str(decision.get("selected_strategy_id") or ""), 0)
                for symbol, counts in sorted(symbol_trade_counts.items())
            }
            if decision.get("selected_strategy_id")
            else {}
        ),
    }
    healthy = bool(coverage >= MIN_SYMBOL_COVERAGE and evaluations)
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details=details,
    )
    print(
        "CTRADER_DEMO_DONCHIAN_TOURNAMENT "
        f"version={TOURNAMENT_VERSION} variants={len(evaluations)} "
        f"symbols={len(bars_by_symbol)}/{len(symbols)} coverage={coverage:.3f} "
        f"stage={decision.get('stage')} selected={decision.get('selected_strategy_id')} "
        "policy=SHADOW_ONLY execution_influence=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
