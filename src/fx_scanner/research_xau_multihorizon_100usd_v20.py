from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    BreakoutVariant,
    _frequency,
    extract_signals as extract_m15_breakout,
    simulate as simulate_m15,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_MULTIHORIZON_100USD_V20"
ARTIFACT_CONTRACT = "XAU_MULTIHORIZON_100USD_V20_EVIDENCE_1"
SYMBOL = "XAUUSD"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
DIAGNOSTIC_ONLY = True

STARTING_BALANCE_USD = 100.0
MIN_LOT = 0.01
MAX_LOT = 0.50
MAX_ACTIVE_POSITIONS = 10

D1_STOP_ATR = 2.0
D1_TARGET_R = 2.0
D1_MAX_HOLD_DAYS = 30
D1_MAX_ACTIVE = 10
D1_CADENCE_DAYS = 1

DEVELOPMENT_FRACTION = 0.75

M15_VARIANTS = (
    BreakoutVariant(
        "V20_M15_L12_ADX12_D1_R150",
        12, 12.0, True, 1.50, 0.50, 3,
    ),
    BreakoutVariant(
        "V20_M15_L20_ADX15_D1_R200",
        20, 15.0, True, 2.00, 0.55, 4,
    ),
)


@dataclass(frozen=True, slots=True)
class BrokerLotSpec:
    lot_size_cents: int
    min_volume_cents: int
    max_volume_cents: int
    step_volume_cents: int
    expected_margin_001_usd: float
    margin_money_digits: int
    reference_price: float

    @property
    def contract_units_per_lot(self) -> float:
        # cTrader Open API volume and lotSize are expressed in cents of units.
        return float(self.lot_size_cents) / 100.0

    @property
    def min_lot(self) -> float:
        return float(self.min_volume_cents) / float(self.lot_size_cents)

    @property
    def step_lot(self) -> float:
        return float(self.step_volume_cents) / float(self.lot_size_cents)


def _bars_frame(rows: Sequence[Bar]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [ensure_utc(x.timestamp) for x in rows],
            "open": [float(x.open) for x in rows],
            "high": [float(x.high) for x in rows],
            "low": [float(x.low) for x in rows],
            "close": [float(x.close) for x in rows],
        }
    ).sort_values("time").reset_index(drop=True)


def _add_daily_indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy().reset_index(drop=True)
    prev_close = x["close"].shift(1)
    tr = pd.concat(
        [
            (x["high"] - x["low"]).abs(),
            (x["high"] - prev_close).abs(),
            (x["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    x["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    x["ema200"] = x["close"].ewm(span=200, adjust=False, min_periods=200).mean()
    x["ret60"] = x["close"] / x["close"].shift(60) - 1.0
    long_sig = (x["close"] > x["ema200"]) & (x["ret60"] > 0)
    short_sig = (x["close"] < x["ema200"]) & (x["ret60"] < 0)
    x["direction"] = np.where(long_sig, 1, np.where(short_sig, -1, 0)).astype(int)
    return x


def _daily_frame(rows: Sequence[Bar]) -> pd.DataFrame:
    x = _bars_frame(rows).set_index("time")
    d1 = x.resample("1D", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).dropna().reset_index()
    return _add_daily_indicators(d1)


def _d1_cost_r(
    *,
    risk_price: float,
    entry_time,
    exit_time,
    pip_size: float,
    costs: M15ResearchCosts,
) -> float:
    if risk_price <= 0 or pip_size <= 0:
        raise ValueError("V20_INVALID_D1_RISK")
    elapsed_days = max(
        0.0,
        (ensure_utc(exit_time) - ensure_utc(entry_time)).total_seconds() / 86400.0,
    )
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / (risk_price / pip_size)


def simulate_d1_staggered(
    rows: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    pip_size: float,
) -> tuple[TournamentTrade, ...]:
    d1 = _daily_frame(rows)
    output: list[TournamentTrade] = []
    active_exit_indices: list[int] = []
    last_signal_i: int | None = None

    for signal_i in range(len(d1) - 1):
        direction = int(d1.loc[signal_i, "direction"])
        if direction == 0:
            continue
        entry_i = signal_i + 1
        active_exit_indices = [idx for idx in active_exit_indices if idx >= entry_i]
        if len(active_exit_indices) >= D1_MAX_ACTIVE:
            continue
        if (
            last_signal_i is not None
            and signal_i - last_signal_i < D1_CADENCE_DAYS
        ):
            continue

        atr = float(d1.loc[signal_i, "atr14"])
        if not isfinite(atr) or atr <= 0:
            continue
        entry = float(d1.loc[entry_i, "open"])
        risk = D1_STOP_ATR * atr
        stop = entry - direction * risk
        target = entry + direction * D1_TARGET_R * risk
        last_i = min(len(d1) - 1, entry_i + D1_MAX_HOLD_DAYS - 1)

        gross_r = None
        exit_i = last_i
        reason = "TIME_EXIT"
        exit_price = float(d1.loc[last_i, "close"])
        for j in range(entry_i, last_i + 1):
            hi = float(d1.loc[j, "high"])
            lo = float(d1.loc[j, "low"])
            if direction > 0:
                stop_hit = lo <= stop
                target_hit = hi >= target
            else:
                stop_hit = hi >= stop
                target_hit = lo <= target
            if stop_hit:
                gross_r = -1.0
                exit_i = j
                exit_price = stop
                reason = "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP_HIT"
                break
            if target_hit:
                gross_r = D1_TARGET_R
                exit_i = j
                exit_price = target
                reason = "TARGET_HIT"
                break

        if gross_r is None:
            exit_price = float(d1.loc[exit_i, "close"])
            gross_r = direction * (exit_price - entry) / risk

        entry_time = d1.loc[entry_i, "time"]
        exit_time = d1.loc[exit_i, "time"]
        cost_r = _d1_cost_r(
            risk_price=risk,
            entry_time=entry_time,
            exit_time=exit_time,
            pip_size=pip_size,
            costs=costs,
        )
        output.append(
            TournamentTrade(
                "V20_D1_TSMOM_C1_R200",
                SYMBOL,
                "LONG" if direction > 0 else "SHORT",
                d1.loc[signal_i, "time"],
                entry_time,
                exit_time,
                signal_i,
                exit_i,
                entry,
                exit_price,
                atr,
                stop,
                target,
                float(gross_r),
                float(cost_r),
                float(gross_r - cost_r),
                int(exit_i - entry_i),
                reason,
            )
        )
        active_exit_indices.append(exit_i)
        last_signal_i = signal_i
    return tuple(output)


def _dedupe(trades: Sequence[TournamentTrade]) -> tuple[TournamentTrade, ...]:
    # Keep one order per exact timestamp/direction. Prefer the stricter L20 setup,
    # then D1 core, then L12.
    priority = {
        "V20_M15_L20_ADX15_D1_R200": 3,
        "V20_D1_TSMOM_C1_R200": 2,
        "V20_M15_L12_ADX12_D1_R150": 1,
    }
    chosen: dict[tuple[Any, str], TournamentTrade] = {}
    for trade in trades:
        key = (ensure_utc(trade.entry_at), str(trade.direction))
        current = chosen.get(key)
        if current is None or priority.get(trade.strategy_id, 0) > priority.get(
            current.strategy_id, 0
        ):
            chosen[key] = trade
    return tuple(
        sorted(chosen.values(), key=lambda x: (ensure_utc(x.entry_at), x.strategy_id))
    )


def _limit_concurrency(
    trades: Sequence[TournamentTrade],
    *,
    max_active: int = MAX_ACTIVE_POSITIONS,
) -> tuple[TournamentTrade, ...]:
    accepted: list[TournamentTrade] = []
    active: list[TournamentTrade] = []
    for trade in sorted(trades, key=lambda x: (ensure_utc(x.entry_at), x.strategy_id)):
        entry = ensure_utc(trade.entry_at)
        active = [x for x in active if ensure_utc(x.exit_at) >= entry]
        if len(active) >= max_active:
            continue
        accepted.append(trade)
        active.append(trade)
    return tuple(accepted)


def _concurrency(trades: Sequence[TournamentTrade]) -> dict[str, float | int]:
    values = sorted(trades, key=lambda x: ensure_utc(x.entry_at))
    if not values:
        return {"max_active": 0, "mean_active_on_entry": 0.0, "p95_active_on_entry": 0.0}
    counts = []
    for trade in values:
        entry = ensure_utc(trade.entry_at)
        active = [
            x for x in values
            if ensure_utc(x.entry_at) <= entry <= ensure_utc(x.exit_at)
        ]
        counts.append(len(active))
    return {
        "max_active": int(max(counts)),
        "mean_active_on_entry": float(np.mean(counts)),
        "p95_active_on_entry": float(np.quantile(counts, 0.95)),
    }


def _period(
    trades: Sequence[TournamentTrade],
    *,
    start=None,
    end=None,
) -> tuple[TournamentTrade, ...]:
    out = []
    for trade in trades:
        entry = ensure_utc(trade.entry_at)
        if start is not None and entry < ensure_utc(start):
            continue
        if end is not None and entry >= ensure_utc(end):
            continue
        out.append(trade)
    return tuple(out)


def _portfolio_candidates(
    rows: Sequence[Bar],
    *,
    base_costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    pip_size: float,
) -> dict[str, dict[str, tuple[TournamentTrade, ...]]]:
    d1_base = simulate_d1_staggered(rows, costs=base_costs, pip_size=pip_size)
    d1_stress = simulate_d1_staggered(rows, costs=stressed_costs, pip_size=pip_size)

    m15_base = {}
    m15_stress = {}
    for variant in M15_VARIANTS:
        signals = extract_m15_breakout(rows, variant=variant)
        m15_base[variant.variant_id] = simulate_m15(
            rows, signals=signals, costs=base_costs, pip_size=pip_size
        )
        m15_stress[variant.variant_id] = simulate_m15(
            rows, signals=signals, costs=stressed_costs, pip_size=pip_size
        )

    l12 = M15_VARIANTS[0].variant_id
    l20 = M15_VARIANTS[1].variant_id
    raw = {
        "D1_ONLY": {
            "base": d1_base,
            "stress": d1_stress,
        },
        "M15_L12_ONLY": {
            "base": m15_base[l12],
            "stress": m15_stress[l12],
        },
        "M15_L20_ONLY": {
            "base": m15_base[l20],
            "stress": m15_stress[l20],
        },
        "D1_PLUS_L12": {
            "base": _dedupe((*d1_base, *m15_base[l12])),
            "stress": _dedupe((*d1_stress, *m15_stress[l12])),
        },
        "D1_PLUS_L20": {
            "base": _dedupe((*d1_base, *m15_base[l20])),
            "stress": _dedupe((*d1_stress, *m15_stress[l20])),
        },
        "D1_PLUS_L12_L20": {
            "base": _dedupe((*d1_base, *m15_base[l12], *m15_base[l20])),
            "stress": _dedupe((*d1_stress, *m15_stress[l12], *m15_stress[l20])),
        },
    }
    return {
        name: {
            "base": _limit_concurrency(pair["base"]),
            "stress": _limit_concurrency(pair["stress"]),
        }
        for name, pair in raw.items()
    }


def _trading_dates(rows: Sequence[Bar], *, start, end=None) -> list[Any]:
    return sorted(
        {
            ensure_utc(row.timestamp).date()
            for row in rows
            if ensure_utc(row.timestamp) >= ensure_utc(start)
            and (end is None or ensure_utc(row.timestamp) < ensure_utc(end))
        }
    )


def _select_dev(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [
        x
        for x in rows
        if x["development_stressed"]["completed_trades"] >= 120
        and x["development_stressed"]["profit_factor"] is not None
        and x["development_stressed"]["profit_factor"] >= 1.10
        and x["development_stressed"]["expectancy_r"] is not None
        and x["development_stressed"]["expectancy_r"] >= 0.05
    ]
    eligible.sort(
        key=lambda x: (
            float(x["development_stressed"]["expectancy_r"]),
            float(x["development_stressed"]["profit_factor"]),
            float(x["development_frequency"]["mean_trades_per_day"]),
            -float(x["development_stressed"]["max_drawdown_r"]),
        ),
        reverse=True,
    )
    return eligible[0] if eligible else None


def _lot_feasible(spec: BrokerLotSpec, lot: float) -> bool:
    volume = int(round(float(lot) * spec.lot_size_cents))
    if volume < spec.min_volume_cents or volume > spec.max_volume_cents:
        return False
    if spec.step_volume_cents > 0:
        if spec.min_volume_cents > 0:
            return (volume - spec.min_volume_cents) % spec.step_volume_cents == 0
        return volume % spec.step_volume_cents == 0
    return True


def _historical_margin(
    *,
    spec: BrokerLotSpec,
    lot: float,
    entry_price: float,
) -> float:
    if spec.reference_price <= 0:
        return float("inf")
    return (
        spec.expected_margin_001_usd
        * (float(lot) / MIN_LOT)
        * (float(entry_price) / spec.reference_price)
    )


def _simulate_cash_path(
    trades: Sequence[TournamentTrade],
    *,
    spec: BrokerLotSpec,
    lot_mode: str,
) -> dict[str, Any]:
    if lot_mode not in {"FIXED_001", "BALANCE_STEP_100"}:
        raise ValueError("V20_UNKNOWN_LOT_MODE")

    units_per_lot = spec.contract_units_per_lot
    balance = STARTING_BALANCE_USD
    peak = balance
    max_dd = 0.0
    losing_streak = 0
    max_losing_streak = 0
    ruin = False
    hit_1000 = False
    skipped_margin = 0
    opened = 0
    events = []
    active: dict[int, dict[str, Any]] = {}

    # Exit events are processed before entries at the same timestamp.
    for idx, trade in enumerate(
        sorted(trades, key=lambda x: (ensure_utc(x.entry_at), ensure_utc(x.exit_at)))
    ):
        events.append((ensure_utc(trade.entry_at), 1, idx, "ENTRY", trade))
        events.append((ensure_utc(trade.exit_at), 0, idx, "EXIT", trade))
    events.sort(key=lambda x: (x[0], x[1], x[2]))

    accepted_ids: set[int] = set()
    min_balance = balance
    min_worst_case_equity = balance
    max_margin_used = 0.0
    max_active = 0

    for _, _, idx, kind, trade in events:
        if kind == "EXIT":
            state = active.pop(idx, None)
            if state is None:
                continue
            balance += float(state["pnl_usd"])
            min_balance = min(min_balance, balance)
            peak = max(peak, balance)
            max_dd = max(max_dd, peak - balance)
            if float(state["pnl_usd"]) < 0:
                losing_streak += 1
                max_losing_streak = max(max_losing_streak, losing_streak)
            else:
                losing_streak = 0
            if balance >= 1000.0:
                hit_1000 = True
            if balance <= 0:
                ruin = True
            continue

        if ruin:
            continue

        if lot_mode == "FIXED_001":
            lot = MIN_LOT
        else:
            lot = min(
                MAX_LOT,
                max(MIN_LOT, floor(balance / 100.0) * 0.01),
            )
        if not _lot_feasible(spec, lot):
            skipped_margin += 1
            continue

        margin = _historical_margin(
            spec=spec,
            lot=lot,
            entry_price=float(trade.entry_price),
        )
        margin_used = sum(float(x["margin"]) for x in active.values())
        free_for_margin = balance - margin_used
        if not isfinite(margin) or margin <= 0 or free_for_margin < margin:
            skipped_margin += 1
            continue

        risk_price = abs(float(trade.entry_price) - float(trade.stop_loss))
        units = units_per_lot * lot
        pnl_usd = float(trade.net_r) * risk_price * units
        stop_loss_usd = risk_price * units

        active[idx] = {
            "margin": margin,
            "pnl_usd": pnl_usd,
            "stop_loss_usd": stop_loss_usd,
            "lot": lot,
        }
        accepted_ids.add(idx)
        opened += 1
        max_active = max(max_active, len(active))
        max_margin_used = max(
            max_margin_used,
            sum(float(x["margin"]) for x in active.values()),
        )
        worst_case_equity = balance - sum(
            float(x["stop_loss_usd"]) for x in active.values()
        )
        min_worst_case_equity = min(min_worst_case_equity, worst_case_equity)

    return {
        "lot_mode": lot_mode,
        "starting_balance_usd": STARTING_BALANCE_USD,
        "minimum_lot": MIN_LOT,
        "risk_pct_filter": None,
        "opened_trades": opened,
        "skipped_margin": skipped_margin,
        "ending_balance_usd": float(balance),
        "net_profit_usd": float(balance - STARTING_BALANCE_USD),
        "return_pct": float((balance / STARTING_BALANCE_USD - 1.0) * 100.0),
        "minimum_realized_balance_usd": float(min_balance),
        "max_realized_drawdown_usd": float(max_dd),
        "max_losing_streak": int(max_losing_streak),
        "max_active_positions": int(max_active),
        "max_margin_used_usd": float(max_margin_used),
        "minimum_worst_case_equity_at_planned_stops_usd": float(
            min_worst_case_equity
        ),
        "ruin": bool(ruin),
        "hit_1000": bool(hit_1000),
        "lot_feasible_001": bool(_lot_feasible(spec, MIN_LOT)),
    }


def evaluate_v20(
    rows: Sequence[Bar],
    *,
    pip_size: float,
    base_costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    broker_spec: BrokerLotSpec,
) -> dict[str, Any]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if len(bars) < 50_000:
        raise ValueError("V20_M15_HISTORY_TOO_SHORT")

    split_i = max(20_000, min(len(bars) - 1, int(len(bars) * DEVELOPMENT_FRACTION)))
    split_time = ensure_utc(bars[split_i].timestamp)
    start_time = ensure_utc(bars[0].timestamp)
    end_time = ensure_utc(bars[-1].timestamp)

    candidates = _portfolio_candidates(
        bars,
        base_costs=base_costs,
        stressed_costs=stressed_costs,
        pip_size=pip_size,
    )

    dev_dates = _trading_dates(bars, start=start_time, end=split_time)
    hold_dates = _trading_dates(bars, start=split_time)

    rows_out = []
    for name, pair in candidates.items():
        dev_base = _period(pair["base"], end=split_time)
        dev_stress = _period(pair["stress"], end=split_time)
        hold_base = _period(pair["base"], start=split_time)
        hold_stress = _period(pair["stress"], start=split_time)
        rows_out.append(
            {
                "portfolio_id": name,
                "development_base": compute_metrics(dev_base).payload(),
                "development_stressed": compute_metrics(dev_stress).payload(),
                "development_frequency": _frequency(dev_base, dev_dates),
                "development_concurrency": _concurrency(dev_base),
                "holdout_base": compute_metrics(hold_base).payload(),
                "holdout_stressed": compute_metrics(hold_stress).payload(),
                "holdout_frequency": _frequency(hold_base, hold_dates),
                "holdout_concurrency": _concurrency(hold_base),
            }
        )

    selected = _select_dev(rows_out)
    selected_id = None if selected is None else selected["portfolio_id"]
    cash = None
    if selected_id is not None:
        holdout_stress = _period(
            candidates[selected_id]["stress"],
            start=split_time,
        )
        cash = {
            "fixed_001": _simulate_cash_path(
                holdout_stress,
                spec=broker_spec,
                lot_mode="FIXED_001",
            ),
            "balance_step_100": _simulate_cash_path(
                holdout_stress,
                spec=broker_spec,
                lot_mode="BALANCE_STEP_100",
            ),
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
            "start": str(start_time),
            "end": str(end_time),
            "split_time": str(split_time),
            "development_fraction": DEVELOPMENT_FRACTION,
        },
        "broker_001_lot": {
            "lot_size_cents": broker_spec.lot_size_cents,
            "contract_units_per_lot": broker_spec.contract_units_per_lot,
            "min_volume_cents": broker_spec.min_volume_cents,
            "max_volume_cents": broker_spec.max_volume_cents,
            "step_volume_cents": broker_spec.step_volume_cents,
            "min_lot": broker_spec.min_lot,
            "step_lot": broker_spec.step_lot,
            "expected_margin_001_usd": broker_spec.expected_margin_001_usd,
            "margin_money_digits": broker_spec.margin_money_digits,
            "reference_price": broker_spec.reference_price,
            "lot_feasible_001": _lot_feasible(broker_spec, MIN_LOT),
        },
        "portfolio_candidates": rows_out,
        "selected_portfolio": selected_id,
        "cash_simulation_holdout": cash,
        "research_contract": {
            "starting_balance_usd": STARTING_BALANCE_USD,
            "minimum_lot": MIN_LOT,
            "risk_pct_filter": None,
            "server_side_sl_tp_required_in_any_future_execution": True,
            "max_positions_for_simulation": MAX_ACTIVE_POSITIONS,
            "selection_uses_holdout": False,
        },
        "note": (
            "V20 is diagnostic because prior XAU evidence has already been exposed. "
            "The $100 experiment intentionally removes percentage-risk eligibility; "
            "0.01-lot broker volume and margin feasibility become the hard capital constraints. "
            "SL/TP remain mandatory."
        ),
    }
