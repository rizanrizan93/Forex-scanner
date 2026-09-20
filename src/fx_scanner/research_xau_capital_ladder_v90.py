from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade
from .models import ensure_utc
from .research_xau_100usd_bootstrap_v89 import (
    COST_SCENARIO_ID,
    MAX_RISK_PCT,
    _assemble,
)
from .research_xau_100usd_leverage_v22 import _symbol_leverage
from .research_xau_100usd_regime_cashpath_v88 import (
    ACCOUNT_LEVERAGE,
    PLANNED_STOP_MARGIN_FLOOR_PCT,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    MAX_ACTIVE_POSITIONS,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_CAPITAL_LADDER_V90"
ARTIFACT_CONTRACT = "XAU_CAPITAL_LADDER_V90_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

STARTING_BALANCES = (100.0, 110.0, 115.0, 120.0, 125.0, 150.0, 175.0, 200.0, 250.0, 300.0, 400.0, 500.0, 550.0, 600.0, 650.0, 700.0, 750.0, 800.0, 900.0)
MIN_LOT = 0.01
LOT_STEP = 0.01
MAX_LOT = 0.50
TARGET_BALANCE = 1000.0


def _lot_floor(value: float) -> float:
    if value < MIN_LOT:
        return 0.0
    steps = math.floor((value + 1e-12) / LOT_STEP)
    return round(min(MAX_LOT, steps * LOT_STEP), 2)


def _planned_loss_for_lot(
    trade: TournamentTrade,
    *,
    spec: BrokerLotSpec,
    lot: float,
) -> float:
    units = spec.contract_units_per_lot * lot
    risk_price = abs(float(trade.entry_price) - float(trade.stop_loss))
    return risk_price * units * (1.0 + max(0.0, float(trade.cost_r)))


def required_balance_distribution(
    trades: Sequence[TournamentTrade],
    *,
    spec: BrokerLotSpec,
) -> dict[str, Any]:
    req = sorted(
        _planned_loss_for_lot(t, spec=spec, lot=MIN_LOT) / (MAX_RISK_PCT / 100.0)
        for t in trades
    )
    if not req:
        return {"count": 0}
    def q(p: float) -> float:
        i = int(round((len(req) - 1) * p))
        return float(req[max(0, min(len(req) - 1, i))])
    return {
        "count": len(req),
        "minimum_usd": float(req[0]),
        "p10_usd": q(0.10),
        "p25_usd": q(0.25),
        "median_usd": q(0.50),
        "p75_usd": q(0.75),
        "p90_usd": q(0.90),
        "maximum_usd": float(req[-1]),
    }


def risk_capped_dynamic_cash_path(
    trades: Sequence[TournamentTrade],
    *,
    starting_balance: float,
    spec: BrokerLotSpec,
    tiers: Sequence[LeverageTier],
    checkpoint_times: Mapping[str, Any],
) -> dict[str, Any]:
    balance = float(starting_balance)
    peak = balance
    minimum_balance = balance
    max_dd_pct = 0.0
    active: dict[int, dict[str, Any]] = {}
    opened = 0
    risk_skips = 0
    margin_skips = 0
    guard_skips = 0
    max_active = 0
    max_lot_used = 0.0
    hit_target_at = None
    lot_hist: dict[str, int] = {}
    checkpoints: dict[str, Any] = {}

    events = []
    ordered = sorted(trades, key=lambda x: (ensure_utc(x.entry_at), ensure_utc(x.exit_at)))
    for idx, trade in enumerate(ordered):
        events.append((ensure_utc(trade.entry_at), 1, idx, "ENTRY", trade))
        events.append((ensure_utc(trade.exit_at), 0, idx, "EXIT", trade))
    events.sort(key=lambda x: (x[0], x[1], x[2]))

    cps = sorted((ensure_utc(v), k) for k, v in checkpoint_times.items())
    cp_i = 0

    def record(label: str, at) -> None:
        checkpoints[label] = {
            "at": ensure_utc(at).isoformat(),
            "realized_balance_usd": float(balance),
            "active_positions": len(active),
        }

    for ts, _, idx, kind, trade in events:
        while cp_i < len(cps) and cps[cp_i][0] <= ts:
            record(cps[cp_i][1], cps[cp_i][0])
            cp_i += 1

        if kind == "EXIT":
            state = active.pop(idx, None)
            if state is None:
                continue
            balance += float(state["pnl_usd"])
            minimum_balance = min(minimum_balance, balance)
            peak = max(peak, balance)
            if peak > 0:
                max_dd_pct = max(max_dd_pct, 100.0 * (peak - balance) / peak)
            if hit_target_at is None and balance >= TARGET_BALANCE:
                hit_target_at = ts.isoformat()
            continue

        if balance <= 0:
            continue

        per_001_loss = _planned_loss_for_lot(trade, spec=spec, lot=MIN_LOT)
        risk_budget = balance * (MAX_RISK_PCT / 100.0)
        lot = _lot_floor(MIN_LOT * (risk_budget / per_001_loss)) if per_001_loss > 0 else 0.0
        if lot < MIN_LOT:
            risk_skips += 1
            continue

        # Respect current free margin and account-wide concurrency.
        if len(active) >= MAX_ACTIVE_POSITIONS:
            margin_skips += 1
            continue

        units = spec.contract_units_per_lot * lot
        notional = abs(float(trade.entry_price)) * units
        symbol_lev = _symbol_leverage(tiers, notional)
        effective = ACCOUNT_LEVERAGE if symbol_lev is None else min(ACCOUNT_LEVERAGE, symbol_lev)
        margin = notional / effective
        current_margin = sum(float(x["margin_usd"]) for x in active.values())
        if balance - current_margin < margin:
            # Try progressively smaller valid lots rather than violating margin.
            feasible = 0.0
            test = round(lot - LOT_STEP, 2)
            while test >= MIN_LOT - 1e-12:
                units_t = spec.contract_units_per_lot * test
                notional_t = abs(float(trade.entry_price)) * units_t
                symbol_lev_t = _symbol_leverage(tiers, notional_t)
                effective_t = ACCOUNT_LEVERAGE if symbol_lev_t is None else min(ACCOUNT_LEVERAGE, symbol_lev_t)
                margin_t = notional_t / effective_t
                if balance - current_margin >= margin_t:
                    feasible = test
                    margin = margin_t
                    break
                test = round(test - LOT_STEP, 2)
            lot = feasible
            if lot < MIN_LOT:
                margin_skips += 1
                continue
            units = spec.contract_units_per_lot * lot

        planned_loss = _planned_loss_for_lot(trade, spec=spec, lot=lot)
        # Recheck exact 5% after lot rounding.
        if planned_loss > risk_budget + 1e-9:
            risk_skips += 1
            continue

        candidate_margin = current_margin + margin
        candidate_loss = sum(float(x["planned_loss_usd"]) for x in active.values()) + planned_loss
        worst_equity = balance - candidate_loss
        margin_level = float("inf") if candidate_margin <= 0 else 100.0 * worst_equity / candidate_margin
        if margin_level <= PLANNED_STOP_MARGIN_FLOOR_PCT:
            guard_skips += 1
            continue

        risk_price = abs(float(trade.entry_price) - float(trade.stop_loss))
        pnl_usd = float(trade.net_r) * risk_price * units
        active[idx] = {
            "margin_usd": margin,
            "planned_loss_usd": planned_loss,
            "pnl_usd": pnl_usd,
            "lot": lot,
        }
        opened += 1
        max_active = max(max_active, len(active))
        max_lot_used = max(max_lot_used, lot)
        lot_hist[f"{lot:.2f}"] = lot_hist.get(f"{lot:.2f}", 0) + 1

    while cp_i < len(cps):
        record(cps[cp_i][1], cps[cp_i][0])
        cp_i += 1

    return {
        "starting_balance_usd": float(starting_balance),
        "ending_balance_usd": float(balance),
        "return_pct": float((balance / starting_balance - 1.0) * 100.0),
        "minimum_realized_balance_usd": float(minimum_balance),
        "max_realized_drawdown_pct": float(max_dd_pct),
        "opened_trades": opened,
        "risk_skips": risk_skips,
        "margin_skips": margin_skips,
        "planned_stop_guard_skips": guard_skips,
        "max_active_positions": max_active,
        "max_lot_used": max_lot_used,
        "lot_histogram": lot_hist,
        "hit_1000": hit_target_at is not None,
        "hit_1000_at": hit_target_at,
        "checkpoints": checkpoints,
    }


def evaluate_v90(
    bars,
    *,
    evaluation_start,
    evaluation_end,
    pip_size: float,
    costs: M15ResearchCosts,
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
    era_windows: Mapping[str, tuple[Any, Any]],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    start = ensure_utc(evaluation_start)
    end = ensure_utc(evaluation_end)
    _, satellite, _, change_points, gates = _assemble(
        rows, costs=costs, pip_size=pip_size, end=end
    )
    satellite = tuple(t for t in satellite if start <= ensure_utc(t.entry_at) < end)
    checkpoints = {
        "START_2012": start,
        "START_2019": ensure_utc(era_windows["2019_2024"][0]),
        "START_2025": ensure_utc(era_windows["2025_2026YTD"][0]),
        "END_2026YTD": end,
    }
    ladder = {
        f"{int(b)}": risk_capped_dynamic_cash_path(
            satellite,
            starting_balance=b,
            spec=broker_spec,
            tiers=leverage_tiers,
            checkpoint_times=checkpoints,
        )
        for b in STARTING_BALANCES
    }
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "account_leverage": ACCOUNT_LEVERAGE,
            "max_risk_pct_per_trade": MAX_RISK_PCT,
            "minimum_lot": MIN_LOT,
            "lot_step": LOT_STEP,
            "maximum_lot": MAX_LOT,
            "planned_stop_margin_floor_pct": PLANNED_STOP_MARGIN_FLOOR_PCT,
            "cost_scenario": COST_SCENARIO_ID,
            "target_balance_usd": TARGET_BALANCE,
            "calendar_era_routing": False,
        },
        "satellite_trade_count": len(satellite),
        "required_balance_for_minimum_lot": required_balance_distribution(
            satellite, spec=broker_spec
        ),
        "starting_balance_ladder": ladder,
        "change_points": list(change_points),
        "gates": gates,
    }
