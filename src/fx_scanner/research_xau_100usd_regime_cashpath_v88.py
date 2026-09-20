from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    gate_family_causally,
    _family_streams,
    _route_family_candidates,
)
from .research_xau_changepoint_reset_router_v87 import (
    ROUTE_ID,
    build_regime_feature_frame,
    detect_change_points,
    gate_family_with_changepoint_reset,
)
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import _period, build_h1_context
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    MAX_ACTIVE_POSITIONS,
    MIN_LOT,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_100USD_REGIME_CASHPATH_V88"
ARTIFACT_CONTRACT = "XAU_100USD_REGIME_CASHPATH_V88_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

STARTING_BALANCE_USD = 100.0
ACCOUNT_LEVERAGE = 100.0
PLANNED_STOP_MARGIN_FLOOR_PCT = 150.0
FIXED_LOT = 0.01
COST_SCENARIO_ID = "V24_STRESS_4675"

PORTFOLIOS = (
    "D1_CORE",
    "D1_PLUS_FROZEN_V47",
    "D1_PLUS_V87_RESET",
)


def _period_metrics(trades: Sequence[TournamentTrade], start, end) -> dict[str, Any]:
    values = _period(trades, start=start, end=end)
    return {
        "trades": len(values),
        "metrics": compute_metrics(values).payload(),
    }


def _assemble_portfolios(
    rows: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    pip_size: float,
    evaluation_end,
) -> tuple[
    dict[str, tuple[TournamentTrade, ...]],
    tuple[dict[str, Any], ...],
    dict[str, Any],
]:
    ordered = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    d1_context = build_secular_d1(ordered)
    h1_context = build_h1_context(ordered)
    feature_frame = build_regime_feature_frame(ordered)
    change_points = detect_change_points(feature_frame)
    full_dates = _trading_dates(
        ordered,
        start=ensure_utc(ordered[0].timestamp),
        end=ensure_utc(evaluation_end),
    )

    classic = _simulate_d1_classic(ordered, costs=costs, pip_size=pip_size)
    annotated = _family_streams(
        ordered,
        costs=costs,
        pip_size=pip_size,
        d1_context=d1_context,
        h1_context=h1_context,
    )

    v47_gated: dict[str, tuple[TournamentTrade, ...]] = {}
    reset_gated: dict[str, tuple[TournamentTrade, ...]] = {}
    gates: dict[str, Any] = {}
    for family in FAMILY_MAP:
        candidate = _route_family_candidates(annotated[family], route=ROUTE_ID)
        frozen, frozen_gate = gate_family_causally(candidate, trading_dates=full_dates)
        reset, reset_gate = gate_family_with_changepoint_reset(
            candidate,
            trading_dates=full_dates,
            change_points=change_points,
        )
        v47_gated[family] = frozen
        reset_gated[family] = reset
        gates[family] = {
            "candidate_trades": len(candidate),
            "frozen_v47_gate": frozen_gate,
            "v87_reset_gate": reset_gate,
        }

    frozen_satellite = tuple(
        trade for family in FAMILY_MAP for trade in v47_gated[family]
    )
    reset_satellite = tuple(
        trade for family in FAMILY_MAP for trade in reset_gated[family]
    )

    portfolios = {
        "D1_CORE": tuple(classic),
        "D1_PLUS_FROZEN_V47": _limit_concurrency(
            _dedupe_with_classic((*classic, *frozen_satellite))
        ),
        "D1_PLUS_V87_RESET": _limit_concurrency(
            _dedupe_with_classic((*classic, *reset_satellite))
        ),
    }
    return portfolios, change_points, gates


def cash_path_with_checkpoints(
    trades: Sequence[TournamentTrade],
    *,
    spec: BrokerLotSpec,
    tiers: Sequence[LeverageTier],
    trading_dates: Sequence[Any],
    checkpoint_times: Mapping[str, Any],
) -> dict[str, Any]:
    balance = STARTING_BALANCE_USD
    peak = balance
    minimum_balance = balance
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    active: dict[int, dict[str, Any]] = {}
    opened = 0
    margin_skips = 0
    stopout_guard_skips = 0
    max_active = 0
    max_margin_used = 0.0
    min_planned_margin_level = float("inf")
    losing_streak = 0
    max_losing_streak = 0
    ruin = False
    first_1000_at = None

    events = []
    ordered = sorted(
        trades,
        key=lambda x: (ensure_utc(x.entry_at), ensure_utc(x.exit_at)),
    )
    for idx, trade in enumerate(ordered):
        events.append((ensure_utc(trade.entry_at), 1, idx, "ENTRY", trade))
        events.append((ensure_utc(trade.exit_at), 0, idx, "EXIT", trade))
    events.sort(key=lambda x: (x[0], x[1], x[2]))

    cps = sorted(
        (
            ensure_utc(ts),
            str(label),
        )
        for label, ts in checkpoint_times.items()
    )
    cp_i = 0
    checkpoints: dict[str, Any] = {}

    def record_checkpoint(label: str, at) -> None:
        checkpoints[label] = {
            "at": ensure_utc(at).isoformat(),
            "realized_balance_usd": float(balance),
            "active_positions": len(active),
            "margin_used_usd": float(
                sum(float(x["margin_usd"]) for x in active.values())
            ),
        }

    for timestamp, _, idx, kind, trade in events:
        while cp_i < len(cps) and cps[cp_i][0] <= timestamp:
            record_checkpoint(cps[cp_i][1], cps[cp_i][0])
            cp_i += 1

        if kind == "EXIT":
            state = active.pop(idx, None)
            if state is None:
                continue
            pnl = float(state["pnl_usd"])
            balance += pnl
            minimum_balance = min(minimum_balance, balance)
            peak = max(peak, balance)
            dd = peak - balance
            max_dd_usd = max(max_dd_usd, dd)
            if peak > 0.0:
                max_dd_pct = max(max_dd_pct, 100.0 * dd / peak)
            if pnl < 0.0:
                losing_streak += 1
                max_losing_streak = max(max_losing_streak, losing_streak)
            else:
                losing_streak = 0
            if first_1000_at is None and balance >= 1000.0:
                first_1000_at = timestamp.isoformat()
            if balance <= 0.0:
                ruin = True
            continue

        if ruin:
            continue
        if not _lot_feasible(spec, FIXED_LOT):
            margin_skips += 1
            continue

        units = spec.contract_units_per_lot * FIXED_LOT
        notional = abs(float(trade.entry_price)) * units
        symbol_leverage = _symbol_leverage(tiers, notional)
        effective_leverage = (
            ACCOUNT_LEVERAGE
            if symbol_leverage is None
            else min(ACCOUNT_LEVERAGE, symbol_leverage)
        )
        margin = notional / effective_leverage

        current_margin = sum(float(x["margin_usd"]) for x in active.values())
        if (
            len(active) >= MAX_ACTIVE_POSITIONS
            or balance - current_margin < margin
        ):
            margin_skips += 1
            continue

        risk_price = abs(float(trade.entry_price) - float(trade.stop_loss))
        cost_multiplier = 1.0 + max(0.0, float(trade.cost_r))
        planned_loss = risk_price * units * cost_multiplier
        candidate_margin = current_margin + margin
        candidate_planned_loss = (
            sum(float(x["planned_loss_usd"]) for x in active.values())
            + planned_loss
        )
        worst_equity = balance - candidate_planned_loss
        planned_margin_level = (
            float("inf")
            if candidate_margin <= 0.0
            else 100.0 * worst_equity / candidate_margin
        )
        if planned_margin_level <= PLANNED_STOP_MARGIN_FLOOR_PCT:
            stopout_guard_skips += 1
            continue

        pnl_usd = float(trade.net_r) * risk_price * units
        active[idx] = {
            "margin_usd": margin,
            "planned_loss_usd": planned_loss,
            "pnl_usd": pnl_usd,
        }
        opened += 1
        max_active = max(max_active, len(active))
        max_margin_used = max(
            max_margin_used,
            sum(float(x["margin_usd"]) for x in active.values()),
        )
        min_planned_margin_level = min(
            min_planned_margin_level,
            planned_margin_level,
        )

    while cp_i < len(cps):
        record_checkpoint(cps[cp_i][1], cps[cp_i][0])
        cp_i += 1

    dates = sorted(set(trading_dates))
    return {
        "starting_balance_usd": STARTING_BALANCE_USD,
        "ending_balance_usd": float(balance),
        "net_profit_usd": float(balance - STARTING_BALANCE_USD),
        "return_pct": float((balance / STARTING_BALANCE_USD - 1.0) * 100.0),
        "account_leverage": ACCOUNT_LEVERAGE,
        "fixed_lot": FIXED_LOT,
        "risk_pct_filter": None,
        "planned_stop_margin_floor_pct": PLANNED_STOP_MARGIN_FLOOR_PCT,
        "opened_trades": opened,
        "margin_skips": margin_skips,
        "planned_stop_guard_skips": stopout_guard_skips,
        "minimum_realized_balance_usd": float(minimum_balance),
        "max_realized_drawdown_usd": float(max_dd_usd),
        "max_realized_drawdown_pct": float(max_dd_pct),
        "max_losing_streak": int(max_losing_streak),
        "max_active_positions": int(max_active),
        "max_margin_used_usd": float(max_margin_used),
        "minimum_planned_margin_level_pct": (
            None
            if min_planned_margin_level == float("inf")
            else float(min_planned_margin_level)
        ),
        "ruin": bool(ruin),
        "hit_1000": bool(first_1000_at is not None),
        "hit_1000_at": first_1000_at,
        "trading_days": len(dates),
        "checkpoints": checkpoints,
    }


def evaluate_v88(
    bars: Sequence[Bar],
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
    if not rows:
        raise ValueError("V88_EMPTY_HISTORY")
    start = ensure_utc(evaluation_start)
    end = ensure_utc(evaluation_end)
    if ensure_utc(rows[0].timestamp) >= start:
        raise ValueError("V88_WARMUP_REQUIRED")

    portfolios, change_points, gates = _assemble_portfolios(
        rows,
        costs=costs,
        pip_size=pip_size,
        evaluation_end=end,
    )
    trading_dates = _trading_dates(rows, start=start, end=end)

    checkpoints = {
        "START_2012": start,
        "START_2019": ensure_utc(era_windows["2019_2024"][0]),
        "START_2025": ensure_utc(era_windows["2025_2026YTD"][0]),
        "END_2026YTD": end,
    }

    portfolio_results: dict[str, Any] = {}
    for portfolio_id, trades in portfolios.items():
        in_window = _period(trades, start=start, end=end)
        era_metrics = {
            era_id: _period_metrics(
                in_window,
                ensure_utc(era_start),
                ensure_utc(era_end),
            )
            for era_id, (era_start, era_end) in era_windows.items()
        }
        portfolio_results[portfolio_id] = {
            "signal_level_full": {
                "trades": len(in_window),
                "metrics": compute_metrics(in_window).payload(),
            },
            "signal_level_by_era": era_metrics,
            "continuous_cash_path": cash_path_with_checkpoints(
                in_window,
                spec=broker_spec,
                tiers=leverage_tiers,
                trading_dates=trading_dates,
                checkpoint_times=checkpoints,
            ),
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "evaluation_start": start.isoformat(),
        "evaluation_end_exclusive": end.isoformat(),
        "cash_contract": {
            "starting_balance_usd": STARTING_BALANCE_USD,
            "account_leverage": ACCOUNT_LEVERAGE,
            "fixed_lot": FIXED_LOT,
            "max_active_positions": MAX_ACTIVE_POSITIONS,
            "planned_stop_margin_floor_pct": PLANNED_STOP_MARGIN_FLOOR_PCT,
            "risk_pct_filter": None,
            "cost_scenario": COST_SCENARIO_ID,
            "balance_resets_between_eras": False,
            "dynamic_sizing": False,
            "compounding_lot": False,
        },
        "change_points": list(change_points),
        "gates": gates,
        "portfolio_results": portfolio_results,
        "note": (
            "V88 is a cash-survivability diagnostic only. It keeps one continuous $100 "
            "account from 2012 through Sep-2026, uses fixed 0.01 lot at 1:100 leverage, "
            "and never resets balance at evaluation-era boundaries. Checkpoints are "
            "realized-balance snapshots, not equity marks. No dynamic sizing is enabled."
        ),
    }
