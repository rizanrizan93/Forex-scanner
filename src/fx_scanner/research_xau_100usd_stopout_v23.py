from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

from .models import ensure_utc
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    MAX_ACTIVE_POSITIONS,
    MIN_LOT,
    STARTING_BALANCE_USD,
    _period,
    _portfolio_candidates,
    _trading_dates,
)
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage

RESEARCH_VERSION = "XAU_100USD_STOPOUT_V23"
ARTIFACT_CONTRACT = "XAU_100USD_STOPOUT_V23_EVIDENCE_1"
SYMBOL = "XAUUSD"
EXECUTION_INFLUENCE = False
POLICY_EFFECT = "SHADOW_ONLY"
DIAGNOSTIC_ONLY = True

ACCOUNT_LEVERAGES = (30.0, 50.0, 100.0, 200.0, 500.0)
PORTFOLIOS = ("D1_ONLY", "D1_PLUS_L20", "D1_PLUS_L12_L20")
BROKER_FALLBACK_STOPOUT_PCT = 50.0


def _cash_path_stopout_safe(
    trades,
    *,
    spec: BrokerLotSpec,
    tiers: Sequence[LeverageTier],
    account_leverage: float,
    stopout_pct: float,
    trading_dates: Sequence[Any],
) -> dict[str, Any]:
    balance = STARTING_BALANCE_USD
    peak = balance
    min_balance = balance
    max_dd = 0.0
    max_dd_pct = 0.0
    losing_streak = 0
    max_losing_streak = 0
    active: dict[int, dict[str, Any]] = {}
    margin_skips = 0
    stopout_guard_skips = 0
    opened = 0
    accepted_dates = []
    max_active = 0
    max_margin_used = 0.0
    min_planned_margin_level = float("inf")
    hit_1000_at = None
    ruin = False

    events = []
    ordered = sorted(trades, key=lambda x: (ensure_utc(x.entry_at), ensure_utc(x.exit_at)))
    for idx, trade in enumerate(ordered):
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
            peak = max(peak, balance)
            dd = peak - balance
            max_dd = max(max_dd, dd)
            if peak > 0:
                max_dd_pct = max(max_dd_pct, 100.0 * dd / peak)
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
        lot = MIN_LOT
        if not _lot_feasible(spec, lot):
            margin_skips += 1
            continue
        units = spec.contract_units_per_lot * lot
        notional = abs(float(trade.entry_price)) * units
        symbol_lev = _symbol_leverage(tiers, notional)
        effective = account_leverage if symbol_lev is None else min(account_leverage, symbol_lev)
        margin = notional / effective

        current_margin = sum(float(x["margin_usd"]) for x in active.values())
        if len(active) >= MAX_ACTIVE_POSITIONS or balance - current_margin < margin:
            margin_skips += 1
            continue

        risk_price = abs(float(trade.entry_price) - float(trade.stop_loss))
        cost_multiplier = 1.0 + max(0.0, float(trade.cost_r))
        planned_loss = risk_price * units * cost_multiplier
        candidate_margin = current_margin + margin
        candidate_planned_loss = sum(float(x["planned_loss_usd"]) for x in active.values()) + planned_loss
        worst_equity = balance - candidate_planned_loss
        planned_margin_level = (
            float("inf") if candidate_margin <= 0 else 100.0 * worst_equity / candidate_margin
        )

        # This is a broker-survivability constraint, not a percentage-risk rule.
        # If all planned SLs would push margin level to/below stop-out, cTrader/FP
        # Markets may liquidate before the intended stop geometry can complete.
        if planned_margin_level <= stopout_pct:
            stopout_guard_skips += 1
            continue

        pnl_usd = float(trade.net_r) * risk_price * units
        active[idx] = {
            "margin_usd": margin,
            "planned_loss_usd": planned_loss,
            "pnl_usd": pnl_usd,
        }
        opened += 1
        accepted_dates.append(timestamp.date())
        max_active = max(max_active, len(active))
        max_margin_used = max(
            max_margin_used,
            sum(float(x["margin_usd"]) for x in active.values()),
        )
        min_planned_margin_level = min(min_planned_margin_level, planned_margin_level)

    dates = sorted(set(trading_dates))
    counts = {d: 0 for d in dates}
    for d in accepted_dates:
        if d in counts:
            counts[d] += 1
    vals = list(counts.values())
    mean_day = sum(vals) / len(vals) if vals else 0.0
    ge5 = sum(v >= 5 for v in vals)

    return {
        "account_leverage": account_leverage,
        "lot": MIN_LOT,
        "risk_pct_filter": None,
        "stopout_guard_pct": stopout_pct,
        "opened_trades": opened,
        "margin_skips": margin_skips,
        "stopout_guard_skips": stopout_guard_skips,
        "ending_balance_usd": float(balance),
        "net_profit_usd": float(balance - STARTING_BALANCE_USD),
        "return_pct": float((balance / STARTING_BALANCE_USD - 1.0) * 100.0),
        "minimum_realized_balance_usd": float(min_balance),
        "max_realized_drawdown_usd": float(max_dd),
        "max_realized_drawdown_pct": float(max_dd_pct),
        "max_losing_streak": int(max_losing_streak),
        "max_active_positions": int(max_active),
        "max_margin_used_usd": float(max_margin_used),
        "minimum_planned_stop_margin_level_pct": (
            None if min_planned_margin_level == float("inf") else float(min_planned_margin_level)
        ),
        "ruin": bool(ruin),
        "hit_1000": bool(hit_1000_at is not None),
        "hit_1000_at": hit_1000_at,
        "mean_accepted_trades_per_day": float(mean_day),
        "days_ge_5_fraction": float(ge5 / len(vals)) if vals else 0.0,
        "trading_days": len(vals),
    }


def evaluate_v23(
    rows,
    *,
    pip_size: float,
    base_costs,
    stressed_costs,
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
    broker_margin_call_thresholds: Sequence[float],
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if len(bars) < 100_000:
        raise ValueError("V23_M15_HISTORY_TOO_SHORT")

    split_i = max(20_000, min(len(bars) - 1, int(len(bars) * 0.75)))
    split_time = ensure_utc(bars[split_i].timestamp)
    hold_dates = _trading_dates(bars, start=split_time)

    positive_thresholds = sorted(float(x) for x in broker_margin_call_thresholds if float(x) > 0)
    # FP Markets publishes stop-out at 50%. When the account returns three
    # margin-call thresholds, the lowest is the liquidation threshold.
    stopout_pct = (
        min(positive_thresholds)
        if positive_thresholds
        else BROKER_FALLBACK_STOPOUT_PCT
    )

    candidates = _portfolio_candidates(
        bars,
        base_costs=base_costs,
        stressed_costs=stressed_costs,
        pip_size=pip_size,
    )
    matrix = {}
    for portfolio_id in PORTFOLIOS:
        holdout = _period(candidates[portfolio_id]["stress"], start=split_time)
        matrix[portfolio_id] = {
            "available_holdout_trades": len(holdout),
            "scenarios": [
                _cash_path_stopout_safe(
                    holdout,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=lev,
                    stopout_pct=stopout_pct,
                    trading_dates=hold_dates,
                )
                for lev in ACCOUNT_LEVERAGES
            ],
        }

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "promotion_eligible": False,
        "symbol": SYMBOL,
        "history": {"m15_rows": len(bars), "split_time": split_time.isoformat()},
        "broker_volume": {
            **asdict(broker_spec),
            "contract_units_per_lot": broker_spec.contract_units_per_lot,
        },
        "dynamic_leverage_tiers": [asdict(x) for x in leverage_tiers],
        "broker_margin_call_thresholds_pct": positive_thresholds,
        "stopout_pct_used": stopout_pct,
        "account_leverage_scenarios": list(ACCOUNT_LEVERAGES),
        "portfolio_scenarios": matrix,
        "contract": {
            "starting_balance_usd": STARTING_BALANCE_USD,
            "minimum_lot": MIN_LOT,
            "risk_pct_filter": None,
            "broker_stopout_survivability_required": True,
            "server_side_sl_tp_required_for_future_demo_execution": True,
            "holdout_already_exposed": True,
        },
        "note": (
            "V23 hard-gates only broker stop-out survivability. It does not restore "
            "a risk-percentage limit. Historical holdout is already exposed, so results "
            "are diagnostic and require prospective DEMO validation."
        ),
    }
