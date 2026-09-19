from __future__ import annotations

from dataclasses import asdict
from math import floor
from typing import Any, Sequence

from .models import ensure_utc
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    MAX_ACTIVE_POSITIONS,
    MAX_LOT,
    MIN_LOT,
    STARTING_BALANCE_USD,
    _period,
    _portfolio_candidates,
    _trading_dates,
)

RESEARCH_VERSION = "XAU_100USD_LEVERAGE_V22"
ARTIFACT_CONTRACT = "XAU_100USD_LEVERAGE_V22_EVIDENCE_1"
SYMBOL = "XAUUSD"
EXECUTION_INFLUENCE = False
POLICY_EFFECT = "SHADOW_ONLY"
DIAGNOSTIC_ONLY = True

ACCOUNT_LEVERAGES = (30.0, 50.0, 100.0, 200.0, 500.0)
PORTFOLIOS = (
    "D1_ONLY",
    "D1_PLUS_L20",
    "D1_PLUS_L12_L20",
)
LOT_MODES = ("FIXED_001", "BALANCE_STEP_100")


def _symbol_leverage(tiers: Sequence[LeverageTier], notional_usd: float) -> float | None:
    if not tiers:
        return None
    ordered = sorted(tiers, key=lambda x: float(x.max_usd_volume))
    for tier in ordered:
        if notional_usd <= float(tier.max_usd_volume):
            return float(tier.leverage)
    return float(ordered[-1].leverage)


def _lot_feasible(spec: BrokerLotSpec, lot: float) -> bool:
    volume = int(round(float(lot) * spec.lot_size_cents))
    if volume < spec.min_volume_cents or volume > spec.max_volume_cents:
        return False
    if spec.step_volume_cents <= 0:
        return True
    if spec.min_volume_cents:
        return (volume - spec.min_volume_cents) % spec.step_volume_cents == 0
    return volume % spec.step_volume_cents == 0


def _lot_for_balance(balance: float, lot_mode: str) -> float:
    if lot_mode == "FIXED_001":
        return MIN_LOT
    if lot_mode == "BALANCE_STEP_100":
        steps = max(1, floor(max(0.0, balance) / 100.0))
        return min(MAX_LOT, steps * 0.01)
    raise ValueError(f"V22_UNKNOWN_LOT_MODE:{lot_mode}")


def _cash_path(
    trades,
    *,
    spec: BrokerLotSpec,
    tiers: Sequence[LeverageTier],
    account_leverage: float,
    lot_mode: str,
    trading_dates: Sequence[Any],
) -> dict[str, Any]:
    balance = STARTING_BALANCE_USD
    peak = balance
    max_dd = 0.0
    max_dd_pct = 0.0
    min_balance = balance
    max_losing_streak = 0
    losing_streak = 0
    ruin = False
    hit_1000_at = None
    max_margin_used = 0.0
    max_active = 0
    min_worst_stop_equity = balance
    worst_stop_below_zero_count = 0
    margin_skips = 0
    volume_skips = 0
    opened = 0
    accepted_entries: list[Any] = []
    active: dict[int, dict[str, Any]] = {}

    events = []
    for idx, trade in enumerate(sorted(trades, key=lambda x: (ensure_utc(x.entry_at), ensure_utc(x.exit_at)))):
        events.append((ensure_utc(trade.entry_at), 1, idx, "ENTRY", trade))
        events.append((ensure_utc(trade.exit_at), 0, idx, "EXIT", trade))
    events.sort(key=lambda x: (x[0], x[1], x[2]))

    for timestamp, _, idx, kind, trade in events:
        if kind == "EXIT":
            state = active.pop(idx, None)
            if state is None:
                continue
            pnl = float(state["pnl_usd"])
            balance += pnl
            min_balance = min(min_balance, balance)
            if balance > peak:
                peak = balance
            dd = peak - balance
            max_dd = max(max_dd, dd)
            if peak > 0:
                max_dd_pct = max(max_dd_pct, dd / peak * 100.0)
            if pnl < 0:
                losing_streak += 1
                max_losing_streak = max(max_losing_streak, losing_streak)
            else:
                losing_streak = 0
            if hit_1000_at is None and balance >= 1000.0:
                hit_1000_at = timestamp.isoformat()
            if balance <= 0:
                ruin = True
            continue

        if ruin:
            continue

        lot = _lot_for_balance(balance, lot_mode)
        if not _lot_feasible(spec, lot):
            volume_skips += 1
            continue

        units = spec.contract_units_per_lot * lot
        notional = abs(float(trade.entry_price)) * units
        symbol_lev = _symbol_leverage(tiers, notional)
        effective_lev = float(account_leverage) if symbol_lev is None else min(float(account_leverage), symbol_lev)
        if effective_lev <= 0:
            margin_skips += 1
            continue
        margin = notional / effective_lev

        margin_used = sum(float(x["margin_usd"]) for x in active.values())
        free_margin_proxy = balance - margin_used
        if len(active) >= MAX_ACTIVE_POSITIONS or free_margin_proxy < margin:
            margin_skips += 1
            continue

        risk_price = abs(float(trade.entry_price) - float(trade.stop_loss))
        stop_loss_usd = risk_price * units
        pnl_usd = float(trade.net_r) * risk_price * units

        active[idx] = {
            "margin_usd": margin,
            "stop_loss_usd": stop_loss_usd,
            "pnl_usd": pnl_usd,
            "lot": lot,
            "effective_leverage": effective_lev,
        }
        opened += 1
        accepted_entries.append(timestamp.date())
        max_active = max(max_active, len(active))
        current_margin = sum(float(x["margin_usd"]) for x in active.values())
        max_margin_used = max(max_margin_used, current_margin)
        worst_stop_equity = balance - sum(float(x["stop_loss_usd"]) for x in active.values())
        min_worst_stop_equity = min(min_worst_stop_equity, worst_stop_equity)
        if worst_stop_equity <= 0:
            worst_stop_below_zero_count += 1

    dates = sorted(set(trading_dates))
    counts = {d: 0 for d in dates}
    for d in accepted_entries:
        if d in counts:
            counts[d] += 1
    vals = list(counts.values())
    mean_per_day = sum(vals) / len(vals) if vals else 0.0
    days_ge5 = sum(v >= 5 for v in vals)
    days_ge5_fraction = days_ge5 / len(vals) if vals else 0.0

    return {
        "account_leverage": float(account_leverage),
        "lot_mode": lot_mode,
        "starting_balance_usd": STARTING_BALANCE_USD,
        "minimum_lot": MIN_LOT,
        "risk_pct_filter": None,
        "opened_trades": opened,
        "margin_skips": margin_skips,
        "volume_skips": volume_skips,
        "ending_balance_usd": float(balance),
        "net_profit_usd": float(balance - STARTING_BALANCE_USD),
        "return_pct": float((balance / STARTING_BALANCE_USD - 1.0) * 100.0),
        "minimum_realized_balance_usd": float(min_balance),
        "max_realized_drawdown_usd": float(max_dd),
        "max_realized_drawdown_pct": float(max_dd_pct),
        "max_losing_streak": int(max_losing_streak),
        "max_active_positions": int(max_active),
        "max_margin_used_usd": float(max_margin_used),
        "minimum_worst_case_equity_at_planned_stops_usd": float(min_worst_stop_equity),
        "planned_stop_equity_below_zero_events": int(worst_stop_below_zero_count),
        "ruin": bool(ruin),
        "hit_1000": bool(hit_1000_at is not None),
        "hit_1000_at": hit_1000_at,
        "mean_accepted_trades_per_day": float(mean_per_day),
        "days_ge_5_fraction": float(days_ge5_fraction),
        "accepted_days_ge_5": int(days_ge5),
        "trading_days": len(vals),
    }


def evaluate_v22(
    rows,
    *,
    pip_size: float,
    base_costs,
    stressed_costs,
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if len(bars) < 100_000:
        raise ValueError("V22_M15_HISTORY_TOO_SHORT")
    split_i = max(20_000, min(len(bars) - 1, int(len(bars) * 0.75)))
    split_time = ensure_utc(bars[split_i].timestamp)
    hold_dates = _trading_dates(bars, start=split_time)

    candidates = _portfolio_candidates(
        bars,
        base_costs=base_costs,
        stressed_costs=stressed_costs,
        pip_size=pip_size,
    )

    matrix = {}
    for portfolio_id in PORTFOLIOS:
        holdout = _period(candidates[portfolio_id]["stress"], start=split_time)
        rows_out = []
        for leverage in ACCOUNT_LEVERAGES:
            for lot_mode in LOT_MODES:
                rows_out.append(
                    _cash_path(
                        holdout,
                        spec=broker_spec,
                        tiers=leverage_tiers,
                        account_leverage=leverage,
                        lot_mode=lot_mode,
                        trading_dates=hold_dates,
                    )
                )
        matrix[portfolio_id] = {
            "holdout_trades_available": len(holdout),
            "scenarios": rows_out,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "promotion_eligible": False,
        "symbol": SYMBOL,
        "history": {
            "m15_rows": len(bars),
            "split_time": split_time.isoformat(),
        },
        "broker_volume": {
            **asdict(broker_spec),
            "contract_units_per_lot": broker_spec.contract_units_per_lot,
            "minimum_lot_feasible": _lot_feasible(broker_spec, MIN_LOT),
        },
        "dynamic_leverage_tiers": [asdict(x) for x in leverage_tiers],
        "account_leverage_scenarios": list(ACCOUNT_LEVERAGES),
        "portfolio_scenarios": matrix,
        "primary_research_portfolio": "D1_ONLY",
        "higher_frequency_challengers": ["D1_PLUS_L20", "D1_PLUS_L12_L20"],
        "contract": {
            "starting_balance_usd": STARTING_BALANCE_USD,
            "minimum_lot": MIN_LOT,
            "max_lot": MAX_LOT,
            "max_active_positions": MAX_ACTIVE_POSITIONS,
            "risk_pct_filter": None,
            "server_side_sl_tp_required_for_future_demo_execution": True,
            "holdout_already_exposed": True,
        },
        "note": (
            "V22 is post-hoc diagnostic. It answers capital feasibility under broker-like "
            "margin constraints; it cannot promote a strategy. FIXED_001 is the primary "
            "$100 test. BALANCE_STEP_100 is an aggressive non-risk-percent compounding diagnostic."
        ),
    }
