from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_cost_viability_router_v43 import _annotate_cost
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    _direction_metrics,
    _max_losing_streak,
    _period,
    annotate_m15,
    build_d1_context,
    build_h1_context,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import (
    EMA_STRATEGY_ID,
    MAX_HOLD_BARS,
    SWEEP_STRATEGY_ID,
    M15ResearchCosts,
    extract_signal_events,
    simulate_hold_variant,
)

RESEARCH_VERSION = "XAU_BEAR_FAMILY_TOURNAMENT_V45"
ARTIFACT_CONTRACT = "XAU_BEAR_FAMILY_TOURNAMENT_V45_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True
COST_R_CAP = 0.10
FAMILIES = (EMA_STRATEGY_ID, SWEEP_STRATEGY_ID)
HOLD_BARS = tuple(MAX_HOLD_BARS)
COST_MODES = ("RAW", "COST10")


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _stats(trades: Sequence[TournamentTrade], trading_days: int) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "trades_per_day": 0.0 if trading_days <= 0 else len(values) / float(trading_days),
        "max_losing_streak": _max_losing_streak(values),
        "metrics": _metrics(values),
        "direction_metrics": _direction_metrics(values),
    }


def _route_id(family: str, hold: int, cost_mode: str) -> str:
    short = "EMA_REV" if family == EMA_STRATEGY_ID else "SWEEP_FADE"
    return f"{short}_H{hold}_{cost_mode}"


def _select_bear(
    annotated: Sequence[Mapping[str, Any]],
    *,
    cost_mode: str,
) -> tuple[TournamentTrade, ...]:
    out: list[TournamentTrade] = []
    for row in annotated:
        trade = row["trade"]
        if str(trade.direction).upper() != "SHORT":
            continue
        if not bool(row["d1_match"]):
            continue
        if not bool(row["h1_normal"]):
            continue
        if str(row["regime"]) not in {"BEAR", "STRONG_BEAR"}:
            continue
        if cost_mode == "COST10" and float(row["entry_friction_r"]) > COST_R_CAP:
            continue
        if cost_mode not in COST_MODES:
            raise ValueError(f"V45_COST_MODE_INVALID:{cost_mode}")
        out.append(trade)
    return tuple(out)


def _family_trade_sets(
    rows: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    pip_size: float,
    start,
    end,
    d1_context,
    h1_context,
) -> dict[str, tuple[TournamentTrade, ...]]:
    events = extract_signal_events(rows)
    out: dict[str, tuple[TournamentTrade, ...]] = {}
    for family in FAMILIES:
        for hold in HOLD_BARS:
            trades = _period(
                simulate_hold_variant(
                    rows,
                    events=events[family],
                    max_hold_bars=hold,
                    costs=costs,
                    pip_size=pip_size,
                ),
                start=start,
                end=end,
            )
            annotated = annotate_m15(
                trades,
                d1_context=d1_context,
                h1_context=h1_context,
            )
            annotated = _annotate_cost(
                annotated,
                pip_size=pip_size,
                costs=costs,
            )
            for cost_mode in COST_MODES:
                out[_route_id(family, hold, cost_mode)] = _select_bear(
                    annotated,
                    cost_mode=cost_mode,
                )
    return out


def evaluate_v45(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V45_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_d1_context(rows)
    h1_context = build_h1_context(rows)
    trading_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(trading_dates)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )
        routes = _family_trade_sets(
            rows,
            costs=costs,
            pip_size=pip_size,
            start=start,
            end=end,
            d1_context=d1_context,
            h1_context=h1_context,
        )

        portfolios: dict[str, Any] = {
            "D1_CLASSIC_ONLY": _stats(classic, trading_days),
        }
        for route_id, selected in routes.items():
            combined = _limit_concurrency(
                _dedupe_with_classic((*classic, *selected))
            )
            payload = _stats(combined, trading_days)
            if cost_id == "V24_STRESS_4675":
                payload["cash_fixed_001"] = _cash_path_stopout_safe(
                    combined,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=ACCOUNT_LEVERAGE,
                    stopout_pct=MARGIN_FLOOR_PCT,
                    trading_dates=trading_dates,
                )
            portfolios[f"D1_CLASSIC_PLUS_{route_id}"] = payload

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "routes": {
                route_id: _stats(trades, trading_days)
                for route_id, trades in routes.items()
            },
            "portfolios": portfolios,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "era_id": era_id,
        "era_start": start.isoformat(),
        "era_end_exclusive": end.isoformat(),
        "trading_days": trading_days,
        "preregistered_contract": {
            "architecture": "D1_BEAR -> H1_NORMAL_PERMISSION -> FROZEN_M15_BEAR_FAMILY",
            "families": list(FAMILIES),
            "holds_bars": list(HOLD_BARS),
            "holds_hours": [x / 4.0 for x in HOLD_BARS],
            "cost_modes": list(COST_MODES),
            "cost10_cap_r": COST_R_CAP,
            "signal_logic_retuned": False,
            "stop_target_retuned": False,
            "hold_horizons_newly_invented": False,
            "dense_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V45 is a bounded bear-family tournament over two frozen pre-existing M15 "
            "families and their previously preregistered hold horizons."
        ),
    }
