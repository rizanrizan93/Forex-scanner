from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_regime_cashpath_v88 import (
    ACCOUNT_LEVERAGE,
    FIXED_LOT,
    PLANNED_STOP_MARGIN_FLOOR_PCT,
    STARTING_BALANCE_USD,
    cash_path_with_checkpoints,
)
from .research_xau_100usd_leverage_v22 import _lot_feasible, _symbol_leverage
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
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
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_100USD_BOOTSTRAP_V89"
ARTIFACT_CONTRACT = "XAU_100USD_BOOTSTRAP_V89_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True
MAX_RISK_PCT = 5.0
COST_SCENARIO_ID = "V24_STRESS_4675"


def _assemble(rows: Sequence[Bar], *, costs: M15ResearchCosts, pip_size: float, end):
    ordered = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    d1_context = build_secular_d1(ordered)
    h1_context = build_h1_context(ordered)
    change_points = detect_change_points(build_regime_feature_frame(ordered))
    dates = _trading_dates(ordered, start=ensure_utc(ordered[0].timestamp), end=end)
    classic = _simulate_d1_classic(ordered, costs=costs, pip_size=pip_size)
    annotated = _family_streams(
        ordered, costs=costs, pip_size=pip_size,
        d1_context=d1_context, h1_context=h1_context,
    )
    reset_streams = {}
    gates = {}
    for family in FAMILY_MAP:
        candidate = _route_family_candidates(annotated[family], route=ROUTE_ID)
        reset, gate = gate_family_with_changepoint_reset(
            candidate, trading_dates=dates, change_points=change_points
        )
        reset_streams[family] = reset
        gates[family] = gate
    satellite = _limit_concurrency(
        _dedupe_with_classic(
            tuple(t for family in FAMILY_MAP for t in reset_streams[family])
        )
    )
    combined = _limit_concurrency(_dedupe_with_classic((*classic, *satellite)))
    return tuple(classic), tuple(satellite), tuple(combined), change_points, gates


def cash_path_risk5(
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
    max_dd = 0.0
    max_dd_pct = 0.0
    active: dict[int, dict[str, Any]] = {}
    opened = 0
    margin_skips = 0
    guard_skips = 0
    risk_skips = 0
    ruin = False
    checkpoints = {}
    events = []
    for idx, trade in enumerate(sorted(trades, key=lambda x: ensure_utc(x.entry_at))):
        events.append((ensure_utc(trade.entry_at), 1, idx, "ENTRY", trade))
        events.append((ensure_utc(trade.exit_at), 0, idx, "EXIT", trade))
    events.sort(key=lambda x: (x[0], x[1], x[2]))
    cps = sorted((ensure_utc(v), k) for k, v in checkpoint_times.items())
    cp_i = 0

    def record(label, at):
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
            dd = peak - balance
            max_dd = max(max_dd, dd)
            if peak > 0:
                max_dd_pct = max(max_dd_pct, 100.0 * dd / peak)
            if balance <= 0:
                ruin = True
            continue

        if ruin or not _lot_feasible(spec, FIXED_LOT):
            continue
        units = spec.contract_units_per_lot * FIXED_LOT
        notional = abs(float(trade.entry_price)) * units
        symbol_lev = _symbol_leverage(tiers, notional)
        effective = ACCOUNT_LEVERAGE if symbol_lev is None else min(ACCOUNT_LEVERAGE, symbol_lev)
        margin = notional / effective
        current_margin = sum(float(x["margin_usd"]) for x in active.values())
        if len(active) >= MAX_ACTIVE_POSITIONS or balance - current_margin < margin:
            margin_skips += 1
            continue

        risk_price = abs(float(trade.entry_price) - float(trade.stop_loss))
        planned_loss = risk_price * units * (1.0 + max(0.0, float(trade.cost_r)))
        if planned_loss > balance * (MAX_RISK_PCT / 100.0):
            risk_skips += 1
            continue

        candidate_margin = current_margin + margin
        candidate_loss = sum(float(x["planned_loss_usd"]) for x in active.values()) + planned_loss
        worst_equity = balance - candidate_loss
        margin_level = float("inf") if candidate_margin <= 0 else 100.0 * worst_equity / candidate_margin
        if margin_level <= PLANNED_STOP_MARGIN_FLOOR_PCT:
            guard_skips += 1
            continue

        active[idx] = {
            "margin_usd": margin,
            "planned_loss_usd": planned_loss,
            "pnl_usd": float(trade.net_r) * risk_price * units,
        }
        opened += 1

    while cp_i < len(cps):
        record(cps[cp_i][1], cps[cp_i][0])
        cp_i += 1

    return {
        "starting_balance_usd": STARTING_BALANCE_USD,
        "ending_balance_usd": float(balance),
        "return_pct": float((balance / STARTING_BALANCE_USD - 1.0) * 100.0),
        "minimum_realized_balance_usd": float(minimum_balance),
        "max_realized_drawdown_usd": float(max_dd),
        "max_realized_drawdown_pct": float(max_dd_pct),
        "opened_trades": opened,
        "margin_skips": margin_skips,
        "planned_stop_guard_skips": guard_skips,
        "risk_5pct_skips": risk_skips,
        "ruin": ruin,
        "checkpoints": checkpoints,
    }


def evaluate_v89(
    bars: Sequence[Bar], *,
    evaluation_start, evaluation_end, pip_size: float,
    costs: M15ResearchCosts,
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
    era_windows: Mapping[str, tuple[Any, Any]],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    start = ensure_utc(evaluation_start); end = ensure_utc(evaluation_end)
    core, satellite, combined, change_points, gates = _assemble(
        rows, costs=costs, pip_size=pip_size, end=end
    )
    dates = _trading_dates(rows, start=start, end=end)
    checkpoints = {
        "START_2012": start,
        "START_2019": ensure_utc(era_windows["2019_2024"][0]),
        "START_2025": ensure_utc(era_windows["2025_2026YTD"][0]),
        "END_2026YTD": end,
    }
    portfolios = {
        "V87_SATELLITE_ONLY": _period(satellite, start=start, end=end),
        "D1_PLUS_V87_RESET": _period(combined, start=start, end=end),
        "D1_CORE": _period(core, start=start, end=end),
    }
    out = {}
    for pid, trades in portfolios.items():
        out[pid] = {
            "signal_metrics": compute_metrics(trades).payload(),
            "cash_no_risk_cap": cash_path_with_checkpoints(
                trades, spec=broker_spec, tiers=leverage_tiers,
                trading_dates=dates, checkpoint_times=checkpoints,
            ),
            "cash_risk_5pct": cash_path_risk5(
                trades, spec=broker_spec, tiers=leverage_tiers,
                trading_dates=dates, checkpoint_times=checkpoints,
            ),
            "era_metrics": {
                era: compute_metrics(_period(trades, start=ensure_utc(a), end=ensure_utc(b))).payload()
                for era, (a, b) in era_windows.items()
            },
        }
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "contract": {
            "starting_balance_usd": STARTING_BALANCE_USD,
            "account_leverage": ACCOUNT_LEVERAGE,
            "fixed_lot": FIXED_LOT,
            "planned_stop_margin_floor_pct": PLANNED_STOP_MARGIN_FLOOR_PCT,
            "max_risk_pct": MAX_RISK_PCT,
            "cost_scenario": COST_SCENARIO_ID,
            "dynamic_sizing": False,
            "calendar_era_routing": False,
        },
        "change_points": list(change_points),
        "gates": gates,
        "portfolio_results": out,
    }
