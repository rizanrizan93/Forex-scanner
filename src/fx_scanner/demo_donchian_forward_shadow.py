from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from time import sleep
from typing import Any, Mapping

import yaml

from .config import load_project_config
from .demo_donchian_adaptive_tournament import (
    MAX_HOLD_H1,
    TIMEFRAME_SECONDS,
    TournamentCosts,
    simulate_variant,
)
from .demo_donchian_lifecycle import (
    DEMOTION_EVENT,
    PROMOTION_STATE_EVENT,
    active_frozen_candidate,
    demotion_required,
    freeze_latest_eligible_candidate,
    promotion_state,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_donchian_forward_shadow"
FORWARD_EVENT = "DEMO_DONCHIAN_FORWARD_CLOSED"
EXCLUDED_24_7_SYMBOLS = frozenset({"BTCUSD", "ETHUSD", "SOLUSD"})
DEFAULT_HISTORY_BARS = 1200
MIN_HISTORY_BARS = 200
MAX_HISTORY_BARS = 3000
MAX_EVENT_ROWS = 5000
MIN_SYMBOL_COVERAGE = 0.80
REQUEST_DELAY_SECONDS = 0.15


def _validation_cfg() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    value = yaml.safe_load((root / "config" / "validation.yaml").read_text())
    if not isinstance(value, dict):
        raise SystemExit("DONCHIAN_FORWARD_VALIDATION_CONFIG_INVALID")
    return value


def _history_count() -> int:
    raw = os.getenv("CTRADER_DONCHIAN_FORWARD_HISTORY_BARS", str(DEFAULT_HISTORY_BARS)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit("CTRADER_DONCHIAN_FORWARD_HISTORY_BARS_INVALID") from exc
    if not MIN_HISTORY_BARS <= value <= MAX_HISTORY_BARS:
        raise SystemExit("CTRADER_DONCHIAN_FORWARD_HISTORY_BARS_OUT_OF_RANGE")
    return value


def _symbols(cfg) -> tuple[str, ...]:
    return tuple(pair.symbol for pair in cfg.pairs if pair.symbol not in EXCLUDED_24_7_SYMBOLS)


def _costs(validation_cfg: Mapping[str, Any]) -> TournamentCosts:
    base = validation_cfg["costs"]["base"]
    return TournamentCosts(
        spread_pips=float(base["spread_pips"]),
        slippage_pips=float(base["slippage_pips"]),
        commission_pips_round_trip=float(base["commission_pips_round_trip"]),
        swap_pips_per_day=float(base["swap_pips_per_day"]),
    )


def _fetch(feed, *, symbols: tuple[str, ...], count: int, as_of: datetime):
    start = as_of - timedelta(seconds=count * TIMEFRAME_SECONDS * 2)
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
            closed = _closed_bars(
                fetched,
                as_of=as_of,
                timeframe_seconds=TIMEFRAME_SECONDS,
            )
            if len(closed) < MIN_HISTORY_BARS:
                failures[symbol] = f"INSUFFICIENT_H1:{len(closed)}<{MIN_HISTORY_BARS}"
            else:
                output[symbol] = tuple(closed)
        except Exception as exc:
            failures[symbol] = f"{type(exc).__name__}:{exc}"
        sleep(REQUEST_DELAY_SECONDS)
    return output, failures


def _existing_forward_keys(store: SupabaseOperationalStore) -> set[str]:
    response = (
        store.client.table("broker_order_events")
        .select("signal_key")
        .eq("backend", "CTRADER")
        .eq("event_type", FORWARD_EVENT)
        .order("observed_at", desc=True)
        .limit(MAX_EVENT_ROWS)
        .execute()
    )
    return {
        str(row.get("signal_key") or "")
        for row in (response.data or [])
        if row.get("signal_key")
    }


def _forward_rows(store: SupabaseOperationalStore, strategy_id: str) -> tuple[dict[str, Any], ...]:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,signal_key,payload")
        .eq("backend", "CTRADER")
        .eq("event_type", FORWARD_EVENT)
        .order("observed_at", desc=False)
        .limit(MAX_EVENT_ROWS)
        .execute()
    )
    rows = []
    for row in response.data or []:
        payload = row.get("payload")
        if isinstance(payload, Mapping) and str(payload.get("strategy_id") or "") == strategy_id:
            rows.append(dict(row))
    return tuple(rows)


def _metrics(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    returns: list[float] = []
    costs: list[float] = []
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, Mapping):
            continue
        try:
            net_r = float(payload.get("net_r"))
            cost_r = float(payload.get("cost_r") or 0.0)
        except (TypeError, ValueError):
            continue
        if not isfinite(net_r) or not isfinite(cost_r):
            continue
        returns.append(net_r)
        costs.append(cost_r)
    if not returns:
        return {
            "completed_trades": 0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "win_rate": None,
            "profit_factor": None,
            "expectancy_r": None,
            "gross_profit_r": 0.0,
            "gross_loss_r": 0.0,
            "max_drawdown_r": 0.0,
            "max_losing_streak": 0,
            "average_cost_r": None,
        }
    wins = sum(value > 0 for value in returns)
    losses = sum(value < 0 for value in returns)
    breakeven = len(returns) - wins - losses
    gross_profit = sum(value for value in returns if value > 0)
    gross_loss = abs(sum(value for value in returns if value < 0))
    profit_factor = None if gross_loss <= 1e-12 else gross_profit / gross_loss
    equity = peak = max_drawdown = 0.0
    loss_streak = max_loss_streak = 0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if value < 0:
            loss_streak += 1
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            loss_streak = 0
    return {
        "completed_trades": len(returns),
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": wins / len(returns),
        "profit_factor": profit_factor,
        "expectancy_r": sum(returns) / len(returns),
        "gross_profit_r": gross_profit,
        "gross_loss_r": gross_loss,
        "max_drawdown_r": max_drawdown,
        "max_losing_streak": max_loss_streak,
        "average_cost_r": sum(costs) / len(costs),
    }


def _latest_promotion_state(store: SupabaseOperationalStore, strategy_id: str) -> dict[str, Any] | None:
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,payload")
        .eq("backend", "CTRADER")
        .eq("event_type", PROMOTION_STATE_EVENT)
        .order("observed_at", desc=True)
        .limit(20)
        .execute()
    )
    for row in response.data or []:
        payload = row.get("payload")
        if isinstance(payload, Mapping) and str(payload.get("strategy_id") or "") == strategy_id:
            return dict(payload)
    return None


def _emit_state_if_changed(store, *, candidate, state: dict[str, Any], previous: Mapping[str, Any] | None):
    if previous is not None and str(previous.get("state")) == str(state.get("state")):
        return False
    store.record_order_event(
        backend="CTRADER",
        account_id=str(os.getenv("CTRADER_ACCOUNT_ID") or os.getenv("CTRADER_TRADER_LOGIN") or "UNKNOWN"),
        signal_key=f"DONCHIAN_STATE:{candidate.strategy_id}:{state['state']}",
        event_type=PROMOTION_STATE_EVENT,
        broker_order_id=f"DONCHIAN_STATE:{candidate.strategy_id}",
        accepted=True,
        code=str(state["state"]),
        message="Donchian prospective forward lifecycle state changed",
        payload=state,
    )
    return True


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("DONCHIAN_FORWARD_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("DONCHIAN_FORWARD_REQUIRE_DEMO")

    validation_cfg = _validation_cfg()
    store = SupabaseOperationalStore.from_env()
    candidate = active_frozen_candidate(store) or freeze_latest_eligible_candidate(store)
    if candidate is None:
        store.write_heartbeat(
            WORKER_NAME,
            healthy=True,
            lag_seconds=0.0,
            details={
                "mode": "DONCHIAN_FORWARD_SHADOW_V1",
                "state": "WAITING_FOR_HISTORICAL_CANDIDATE",
                "execution_influence": False,
                "policy_effect": "SHADOW_ONLY",
            },
        )
        print("CTRADER_DEMO_DONCHIAN_FORWARD state=WAITING_FOR_HISTORICAL_CANDIDATE")
        return 0

    symbols = _symbols(cfg)
    pair_by_symbol = {pair.symbol: pair for pair in cfg.pairs}
    history_count = _history_count()
    feed = build_ctrader_research_feed(policy, symbols)
    as_of = datetime.now(tz=UTC)
    bars_by_symbol: dict[str, tuple] = {}
    failures: dict[str, str] = {}
    try:
        feed.ensure_connected()
        bars_by_symbol, failures = _fetch(feed, symbols=symbols, count=history_count, as_of=as_of)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    coverage = 0.0 if not symbols else len(bars_by_symbol) / len(symbols)
    existing = _existing_forward_keys(store)
    emitted = 0
    costs = _costs(validation_cfg)
    warmup = max(candidate.variant.lookback, candidate.variant.atr_period)

    for symbol, bars in bars_by_symbol.items():
        # Start exactly at the prospective freeze boundary while retaining only
        # pre-freeze bars needed to build point-in-time Donchian/ATR features.
        first_forward = next(
            (
                index
                for index, bar in enumerate(bars)
                if bar.timestamp + timedelta(seconds=TIMEFRAME_SECONDS) >= candidate.frozen_at
            ),
            len(bars),
        )
        if first_forward >= len(bars):
            continue
        start = max(0, first_forward - warmup)
        window = bars[start:]
        trades = simulate_variant(
            window,
            symbol=symbol,
            pip_size=float(pair_by_symbol[symbol].pip_size),
            variant=candidate.variant,
            costs=costs,
        )
        for trade in trades:
            # `entry_at` is the next H1 open, which is also the breakout bar's
            # completion boundary. It therefore cannot precede candidate freeze.
            if trade.entry_at < candidate.frozen_at:
                continue
            key = f"DONCHIAN_FORWARD:{candidate.strategy_id}:{symbol}:{trade.entry_at.isoformat()}"
            if key in existing:
                continue
            payload = {
                "strategy_id": candidate.strategy_id,
                "params": {
                    "lookback": candidate.variant.lookback,
                    "atr_period": candidate.variant.atr_period,
                    "buffer_atr": candidate.variant.buffer_atr,
                },
                "symbol": trade.symbol,
                "direction": trade.direction,
                "signal_bar_open_at": trade.signal_at.isoformat(),
                "entry_at": trade.entry_at.isoformat(),
                "exit_at": trade.exit_at.isoformat(),
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "atr_at_signal": trade.atr_at_signal,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
                "gross_r": trade.gross_r,
                "cost_r": trade.cost_r,
                "net_r": trade.net_r,
                "bars_held": trade.bars_held,
                "exit_reason": trade.exit_reason,
                "frozen_at": candidate.frozen_at.isoformat(),
                "policy_effect": "SHADOW_ONLY",
                "execution_influence": False,
            }
            store.record_order_event(
                backend="CTRADER",
                account_id=str(os.getenv("CTRADER_ACCOUNT_ID") or os.getenv("CTRADER_TRADER_LOGIN") or "UNKNOWN"),
                signal_key=key,
                event_type=FORWARD_EVENT,
                broker_order_id=f"DONCHIAN_SHADOW:{symbol}:{trade.entry_at.isoformat()}",
                accepted=True,
                code=trade.exit_reason,
                message="prospective Donchian H1 forward-shadow trade closed",
                payload=payload,
            )
            existing.add(key)
            emitted += 1

    all_rows = _forward_rows(store, candidate.strategy_id)
    metrics = _metrics(all_rows)
    recent_metrics = _metrics(all_rows[-30:])
    state = promotion_state(
        candidate=candidate,
        forward_metrics=metrics,
        stress_acceptance=validation_cfg["stress_acceptance"],
        drawdown_limit_r=float(validation_cfg["monte_carlo"]["max_drawdown_r_p95_limit"]),
    )
    previous = _latest_promotion_state(store, candidate.strategy_id)
    demote = demotion_required(state=previous or {}, recent_metrics=recent_metrics)
    if demote:
        store.record_order_event(
            backend="CTRADER",
            account_id=str(os.getenv("CTRADER_ACCOUNT_ID") or os.getenv("CTRADER_TRADER_LOGIN") or "UNKNOWN"),
            signal_key=f"DONCHIAN_DEMOTE:{candidate.strategy_id}:{as_of.isoformat()}",
            event_type=DEMOTION_EVENT,
            broker_order_id=f"DONCHIAN_DEMOTE:{candidate.strategy_id}",
            accepted=True,
            code="FORWARD_EDGE_DECAY",
            message="Donchian candidate demoted after prospective edge decay",
            payload={
                "strategy_id": candidate.strategy_id,
                "reason": "RECENT_EXPECTANCY_OR_PROFIT_FACTOR_FAILED",
                "recent_metrics": recent_metrics,
                "previous_state": previous,
                "execution_influence": False,
            },
        )
        state = {**state, "state": "DEMOTED", "demotion_reason": "FORWARD_EDGE_DECAY"}
    changed = _emit_state_if_changed(store, candidate=candidate, state=state, previous=previous)

    healthy = coverage >= MIN_SYMBOL_COVERAGE
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "mode": "DONCHIAN_FORWARD_SHADOW_V1",
            "candidate": candidate.payload(),
            "symbol_coverage": coverage,
            "minimum_symbol_coverage": MIN_SYMBOL_COVERAGE,
            "fetch_failures": failures,
            "forward_rows_emitted": emitted,
            "forward_metrics": metrics,
            "recent_30_metrics": recent_metrics,
            "promotion_state": state,
            "promotion_state_changed": changed,
            "execution_influence": False,
            "risk_mutation": False,
            "sltp_mutation": False,
        },
    )
    print(
        "CTRADER_DEMO_DONCHIAN_FORWARD "
        f"strategy={candidate.strategy_id} emitted={emitted} "
        f"decisive={metrics['completed_trades']} state={state['state']} "
        f"coverage={coverage:.3f} execution_influence=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
