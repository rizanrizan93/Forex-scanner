from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    extract_signals as extract_m15_breakout,
    simulate as simulate_m15,
)
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_adaptive_alpha_activation_v40 import (
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
    gate_family_causally,
)
from .research_xau_cost_viability_router_v43 import _annotate_cost
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    L12_ID,
    L20_ID,
    MARGIN_FLOOR_PCT,
    _direction_metrics,
    _max_losing_streak,
    _period,
    build_h1_context,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    M15_VARIANTS,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import (
    COST_R_CAP,
    annotate_secular,
    build_secular_d1,
)

RESEARCH_VERSION = "XAU_CAUSAL_REGIME_EDGE_GATE_V47"
ARTIFACT_CONTRACT = "XAU_CAUSAL_REGIME_EDGE_GATE_V47_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FAMILY_MAP = {
    "L12": L12_ID,
    "L20": L20_ID,
}

ROUTES = (
    "LONG_REACCEL_COST10",
    "SECULAR_BULL_REACCEL_LONG_COST10",
    "SECULAR_BULL_LONG_COST10",
)


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


def _candidate_match(row: Mapping[str, Any], route: str) -> bool:
    trade = row["trade"]
    if str(trade.direction).upper() != "LONG":
        return False
    if not bool(row["d1_match"]) or not bool(row["h1_normal"]):
        return False
    if float(row["entry_friction_r"]) > COST_R_CAP:
        return False

    outcome = str(row["transition_outcome"])
    age = int(row["post_transition_age_days"])
    secular = str(row["secular_regime"])

    if route == "LONG_REACCEL_COST10":
        return outcome == "REACCELERATION" and 1 <= age <= 20
    if route == "SECULAR_BULL_REACCEL_LONG_COST10":
        return (
            secular == "SECULAR_BULL"
            and outcome == "REACCELERATION"
            and 1 <= age <= 20
        )
    if route == "SECULAR_BULL_LONG_COST10":
        return secular == "SECULAR_BULL"
    raise ValueError(f"V47_ROUTE_INVALID:{route}")


def _family_streams(
    rows: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    pip_size: float,
    d1_context,
    h1_context,
) -> dict[str, tuple[dict[str, Any], ...]]:
    by_id = {variant.variant_id: variant for variant in M15_VARIANTS}
    out: dict[str, tuple[dict[str, Any], ...]] = {}
    for family, variant_id in FAMILY_MAP.items():
        variant = by_id[variant_id]
        trades = simulate_m15(
            rows,
            signals=extract_m15_breakout(rows, variant=variant),
            costs=costs,
            pip_size=pip_size,
        )
        annotated = annotate_secular(
            trades,
            d1_context=d1_context,
            h1_context=h1_context,
        )
        out[family] = _annotate_cost(
            annotated,
            pip_size=pip_size,
            costs=costs,
        )
    return out


def _route_family_candidates(
    annotated: Sequence[Mapping[str, Any]],
    *,
    route: str,
) -> tuple[TournamentTrade, ...]:
    return tuple(
        row["trade"]
        for row in annotated
        if _candidate_match(row, route)
    )


def evaluate_v47(
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
        raise ValueError("V47_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=end,
    )
    era_dates = _trading_dates(rows, start=start, end=end)
    era_days = len(era_dates)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )
        annotated_by_family = _family_streams(
            rows,
            costs=costs,
            pip_size=pip_size,
            d1_context=d1_context,
            h1_context=h1_context,
        )

        route_payload: dict[str, Any] = {}
        portfolio_payload: dict[str, Any] = {}

        for route in ROUTES:
            ungated_all: dict[str, tuple[TournamentTrade, ...]] = {}
            gated_all: dict[str, tuple[TournamentTrade, ...]] = {}
            gates: dict[str, Any] = {}

            for family in FAMILY_MAP:
                candidate = _route_family_candidates(
                    annotated_by_family[family],
                    route=route,
                )
                gated, gate = gate_family_causally(
                    candidate,
                    trading_dates=full_dates,
                )
                ungated_all[family] = candidate
                gated_all[family] = gated
                gates[family] = {
                    **gate,
                    "all_candidate_metrics": _metrics(candidate),
                    "era_ungated_metrics": _metrics(
                        _period(candidate, start=start, end=end)
                    ),
                    "era_gated_metrics": _metrics(
                        _period(gated, start=start, end=end)
                    ),
                }

            ungated_era = tuple(
                trade
                for family in FAMILY_MAP
                for trade in _period(ungated_all[family], start=start, end=end)
            )
            gated_era = tuple(
                trade
                for family in FAMILY_MAP
                for trade in _period(gated_all[family], start=start, end=end)
            )

            ungated_portfolio = _limit_concurrency(
                _dedupe_with_classic((*classic, *ungated_era))
            )
            gated_portfolio = _limit_concurrency(
                _dedupe_with_classic((*classic, *gated_era))
            )

            route_payload[route] = {
                "ungated": _stats(ungated_era, era_days),
                "gated": _stats(gated_era, era_days),
                "gates": gates,
            }
            portfolio_payload[route] = {
                "ungated_d1_plus_route": _stats(ungated_portfolio, era_days),
                "gated_d1_plus_route": _stats(gated_portfolio, era_days),
            }
            if cost_id == "V24_STRESS_4675":
                portfolio_payload[route]["gated_cash_fixed_001"] = _cash_path_stopout_safe(
                    gated_portfolio,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=ACCOUNT_LEVERAGE,
                    stopout_pct=MARGIN_FLOOR_PCT,
                    trading_dates=era_dates,
                )

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "core_d1_classic": _stats(classic, era_days),
            "routes": route_payload,
            "portfolios": portfolio_payload,
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
        "era_trading_days": era_days,
        "preregistered_contract": {
            "routes": list(ROUTES),
            "families": FAMILY_MAP,
            "cost_r_cap": COST_R_CAP,
            "gate_lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "gate_min_completed_trades": MIN_COMPLETED_TRADES,
            "gate_min_trailing_pf": MIN_TRAILING_PF,
            "gate_min_trailing_expectancy_r": MIN_TRAILING_EXPECTANCY_R,
            "gate_thresholds_identical_to_v40": True,
            "gate_uses_only_completed_prior_route_family_trades": True,
            "cold_start_is_off_until_min_sample": True,
            "year_or_era_feature_used": False,
            "signal_logic_retuned": False,
            "dense_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V47 composes the frozen V40 online health gate with V42/V43/V46 route context. "
            "Suppressed signals remain observable in shadow so future gate state remains causal."
        ),
    }
