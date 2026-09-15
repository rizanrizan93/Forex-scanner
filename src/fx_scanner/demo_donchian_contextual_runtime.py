from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any

import yaml

from .config import load_project_config
from .demo_donchian_adaptive_tournament import TournamentCosts
from .demo_donchian_contextual_v2 import (
    CONTEXTUAL_VERSION,
    CORE_VARIANT,
    DEVELOPMENT_FRACTION,
    PROFILES,
    STRUCTURE_WINDOW,
    evaluate_development,
    evaluate_untouched_holdout,
    select_on_development,
    simulate_context_profile,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_donchian_contextual_v2"
EXCLUDED_24_7_SYMBOLS = frozenset({"BTCUSD", "ETHUSD", "SOLUSD"})
DEFAULT_HISTORY_BARS = 2200
MIN_HISTORY_BARS = 800
MAX_HISTORY_BARS = 5000
MIN_SYMBOL_COVERAGE = 0.80
REQUEST_DELAY_SECONDS = 0.20


def _validation_cfg() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    value = yaml.safe_load((root / "config" / "validation.yaml").read_text())
    if not isinstance(value, dict):
        raise SystemExit("DONCHIAN_CONTEXT_VALIDATION_CONFIG_INVALID")
    return value


def _history_count() -> int:
    raw = os.getenv("CTRADER_DONCHIAN_CONTEXT_HISTORY_BARS", str(DEFAULT_HISTORY_BARS)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("CTRADER_DONCHIAN_CONTEXT_HISTORY_BARS_INVALID") from exc
    if not MIN_HISTORY_BARS <= value <= MAX_HISTORY_BARS:
        raise SystemExit("CTRADER_DONCHIAN_CONTEXT_HISTORY_BARS_OUT_OF_RANGE")
    return value


def _symbols(cfg) -> tuple[str, ...]:
    return tuple(pair.symbol for pair in cfg.pairs if pair.symbol not in EXCLUDED_24_7_SYMBOLS)


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


def _fetch(feed, *, symbols: tuple[str, ...], count: int, as_of: datetime):
    start = as_of - timedelta(seconds=count * 3600 * 2)
    output: dict[str, tuple] = {}
    failures: dict[str, str] = {}
    for symbol in symbols:
        try:
            fetched = tuple(
                feed.historical_bars(
                    symbol,
                    "H1",
                    from_time=start,
                    to_time=as_of,
                    count=count,
                )
            )
            closed = _closed_bars(fetched, as_of=as_of, timeframe_seconds=3600)
            if len(closed) < MIN_HISTORY_BARS:
                failures[symbol] = f"INSUFFICIENT_H1:{len(closed)}<{MIN_HISTORY_BARS}"
            else:
                output[symbol] = tuple(closed)
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}:{exc}"
        sleep(REQUEST_DELAY_SECONDS)
    return output, failures


def _write_artifact(details: dict[str, Any]) -> str | None:
    raw = os.getenv("DONCHIAN_CONTEXT_EVIDENCE_OUTPUT", "").strip()
    if not raw:
        return None
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "artifact_contract": "DONCHIAN_CONTEXTUAL_V2_EVIDENCE_1",
        "contains_secrets": False,
        "details": details,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return str(path)


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("DONCHIAN_CONTEXT_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("DONCHIAN_CONTEXT_REQUIRE_DEMO")

    validation_cfg = _validation_cfg()
    symbols = _symbols(cfg)
    pair_by_symbol = {pair.symbol: pair for pair in cfg.pairs}
    count = _history_count()
    as_of = datetime.now(tz=UTC)
    feed = build_ctrader_research_feed(policy, symbols)
    try:
        feed.ensure_connected()
        bars_by_symbol, failures = _fetch(feed, symbols=symbols, count=count, as_of=as_of)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    coverage = 0.0 if not symbols else len(bars_by_symbol) / len(symbols)
    base_costs = _costs(validation_cfg, stressed=False)
    stressed_costs = _costs(validation_cfg, stressed=True)
    development_base = {profile.profile_id: [] for profile in PROFILES}
    development_stressed = {profile.profile_id: [] for profile in PROFILES}
    split_times: dict[str, str] = {}
    split_indices: dict[str, int] = {}
    development_symbol_counts: dict[str, dict[str, int]] = {}

    warmup = max(CORE_VARIANT.lookback, CORE_VARIANT.atr_period, STRUCTURE_WINDOW)
    for symbol, bars in bars_by_symbol.items():
        split_index = int(len(bars) * DEVELOPMENT_FRACTION)
        split_index = max(warmup + 1, min(split_index, len(bars) - 2))
        split_indices[symbol] = split_index
        split_time = bars[split_index].timestamp
        split_times[symbol] = split_time.isoformat()
        dev_bars = bars[:split_index]
        pip_size = float(pair_by_symbol[symbol].pip_size)
        development_symbol_counts[symbol] = {}
        for profile in PROFILES:
            dev_base = simulate_context_profile(
                dev_bars,
                symbol=symbol,
                pip_size=pip_size,
                profile=profile,
                costs=base_costs,
            )
            dev_stress = simulate_context_profile(
                dev_bars,
                symbol=symbol,
                pip_size=pip_size,
                profile=profile,
                costs=stressed_costs,
            )
            development_base[profile.profile_id].extend(dev_base)
            development_stressed[profile.profile_id].extend(dev_stress)
            development_symbol_counts[symbol][profile.profile_id] = len(dev_base)

    evaluations = tuple(
        evaluate_development(
            profile=profile,
            base_trades=development_base[profile.profile_id],
            stressed_trades=development_stressed[profile.profile_id],
            validation_cfg=validation_cfg,
        )
        for profile in PROFILES
    )
    selected = select_on_development(evaluations)
    selected_id = None if selected is None else selected.profile.profile_id

    # Untouched holdout is evaluated only after the development-only selector is
    # frozen. No alternative profile receives a holdout score in this run.
    selected_holdout_base = []
    selected_holdout_stressed = []
    selected_symbol_trade_counts: dict[str, dict[str, int]] = {}
    if selected is not None:
        for symbol, bars in bars_by_symbol.items():
            split_index = split_indices[symbol]
            split_time = bars[split_index].timestamp
            hold_start = max(0, split_index - warmup)
            hold_bars = bars[hold_start:]
            pip_size = float(pair_by_symbol[symbol].pip_size)
            hold_base_all = simulate_context_profile(
                hold_bars,
                symbol=symbol,
                pip_size=pip_size,
                profile=selected.profile,
                costs=base_costs,
            )
            hold_stress_all = simulate_context_profile(
                hold_bars,
                symbol=symbol,
                pip_size=pip_size,
                profile=selected.profile,
                costs=stressed_costs,
            )
            hold_base = tuple(row for row in hold_base_all if row.signal_at >= split_time)
            hold_stress = tuple(row for row in hold_stress_all if row.signal_at >= split_time)
            selected_holdout_base.extend(hold_base)
            selected_holdout_stressed.extend(hold_stress)
            selected_symbol_trade_counts[symbol] = {
                "development": development_symbol_counts[symbol].get(selected_id, 0),
                "holdout": len(hold_base),
            }

    decision = evaluate_untouched_holdout(
        selected=selected,
        holdout_base=selected_holdout_base,
        holdout_stressed=selected_holdout_stressed,
        validation_cfg=validation_cfg,
    )
    if coverage < MIN_SYMBOL_COVERAGE:
        decision = {
            **decision,
            "stage": "DATA_INSUFFICIENT",
            "holdout_pass": False,
            "reason": "SYMBOL_COVERAGE_BELOW_GATE",
        }

    details = {
        "contextual_version": CONTEXTUAL_VERSION,
        "environment": "DEMO",
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "core_params_frozen": {
            "lookback": CORE_VARIANT.lookback,
            "atr_period": CORE_VARIANT.atr_period,
            "buffer_atr": CORE_VARIANT.buffer_atr,
            "stop_atr": 2.0,
            "reward_r": 2.0,
            "max_hold_h1": 72,
        },
        "anti_overfit_contract": {
            "profile_count": len(PROFILES),
            "development_fraction": DEVELOPMENT_FRACTION,
            "holdout_fraction": 1.0 - DEVELOPMENT_FRACTION,
            "profile_selection_uses_holdout": False,
            "minimum_development_trades": 130,
            "minimum_holdout_trades": 100,
            "holdout_opened_only_after_development_selection": True,
            "only_selected_profile_receives_holdout_score": True,
        },
        "symbols_requested": list(symbols),
        "symbols_available": sorted(bars_by_symbol),
        "symbol_coverage": coverage,
        "minimum_symbol_coverage": MIN_SYMBOL_COVERAGE,
        "fetch_failures": failures,
        "closed_h1_counts": {symbol: len(rows) for symbol, rows in sorted(bars_by_symbol.items())},
        "split_times": split_times,
        "development_evaluations": [row.payload() for row in evaluations],
        "decision": decision,
        "selected_symbol_trade_counts": selected_symbol_trade_counts,
    }
    healthy = bool(coverage >= MIN_SYMBOL_COVERAGE and bars_by_symbol)
    store = SupabaseOperationalStore.from_env()
    store.write_heartbeat(WORKER_NAME, healthy=healthy, lag_seconds=0.0, details=details)
    artifact_path = _write_artifact(details)
    print(
        "CTRADER_DEMO_DONCHIAN_CONTEXT_V2 "
        f"profiles={len(PROFILES)} symbols={len(bars_by_symbol)}/{len(symbols)} "
        f"coverage={coverage:.3f} selected={selected_id} stage={decision.get('stage')} "
        f"holdout_pass={int(bool(decision.get('holdout_pass')))} "
        f"artifact={artifact_path or 'NONE'} execution_influence=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
