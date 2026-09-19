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
from .research_xau_reacceleration_router_v42 import (
    annotate_outcome_m15,
    build_transition_outcome_context,
)

RESEARCH_VERSION = "XAU_COST_VIABILITY_ROUTER_V43"
ARTIFACT_CONTRACT = "XAU_COST_VIABILITY_ROUTER_V43_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

COST_R_LIMITS = (0.20, 0.15, 0.10)
ROUTES = (
    "ALL_D1_H1_ALIGNED_COST20",
    "ALL_D1_H1_ALIGNED_COST15",
    "ALL_D1_H1_ALIGNED_COST10",
    "REACCEL_1_20_NORMAL_UNGATED",
    "REACCEL_1_20_NORMAL_COST20",
    "REACCEL_1_20_NORMAL_COST15",
    "REACCEL_1_20_NORMAL_COST10",
)


def _friction_pips(costs: M15ResearchCosts) -> float:
    return (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
    )


def _risk_pips(trade: TournamentTrade, pip_size: float) -> float:
    return abs(float(trade.entry_price) - float(trade.stop_loss)) / float(pip_size)


def _annotate_cost(
    annotated: Sequence[Mapping[str, Any]],
    *,
    pip_size: float,
    costs: M15ResearchCosts,
) -> tuple[dict[str, Any], ...]:
    friction_pips = _friction_pips(costs)
    out: list[dict[str, Any]] = []
    for row in annotated:
        trade = row["trade"]
        risk_pips = _risk_pips(trade, pip_size)
        if risk_pips <= 0.0:
            continue
        enriched = dict(row)
        enriched["initial_risk_pips"] = risk_pips
        enriched["entry_friction_pips"] = friction_pips
        enriched["entry_friction_r"] = friction_pips / risk_pips
        out.append(enriched)
    return tuple(out)


def _limit_from_route(route: str) -> float | None:
    if route.endswith("COST20"):
        return 0.20
    if route.endswith("COST15"):
        return 0.15
    if route.endswith("COST10"):
        return 0.10
    return None


def _select(
    annotated: Sequence[Mapping[str, Any]],
    route: str,
) -> tuple[TournamentTrade, ...]:
    cap = _limit_from_route(route)
    selected: list[TournamentTrade] = []

    for row in annotated:
        family = str(row["family"])
        if family not in {"L12", "L20"}:
            continue

        match = bool(row["d1_match"])
        normal = bool(row["h1_normal"])
        outcome = str(row["transition_outcome"])
        age = int(row["post_transition_age_days"])
        friction_r = float(row["entry_friction_r"])

        cost_ok = cap is None or friction_r <= cap
        if route.startswith("ALL_D1_H1_ALIGNED_"):
            keep = match and normal and cost_ok
        elif route == "REACCEL_1_20_NORMAL_UNGATED":
            keep = (
                outcome == "REACCELERATION"
                and match
                and normal
                and 1 <= age <= 20
            )
        elif route.startswith("REACCEL_1_20_NORMAL_COST"):
            keep = (
                outcome == "REACCELERATION"
                and match
                and normal
                and 1 <= age <= 20
                and cost_ok
            )
        else:
            raise ValueError(f"V43_ROUTE_INVALID:{route}")

        if keep:
            selected.append(row["trade"])
    return tuple(selected)


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


def _bucket(value: float) -> str:
    if value <= 0.10:
        return "LE_010R"
    if value <= 0.15:
        return "GT010_LE015R"
    if value <= 0.20:
        return "GT015_LE020R"
    return "GT020R"


def _diagnostics(
    annotated: Sequence[Mapping[str, Any]],
    *,
    trading_days: int,
) -> dict[str, Any]:
    aligned = tuple(
        row for row in annotated
        if bool(row["d1_match"]) and bool(row["h1_normal"])
    )
    reaccel = tuple(
        row for row in aligned
        if str(row["transition_outcome"]) == "REACCELERATION"
        and 1 <= int(row["post_transition_age_days"]) <= 20
    )
    buckets = ("LE_010R", "GT010_LE015R", "GT015_LE020R", "GT020R")
    return {
        "all_aligned_by_friction_r": {
            bucket: _stats(
                tuple(
                    row["trade"] for row in aligned
                    if _bucket(float(row["entry_friction_r"])) == bucket
                ),
                trading_days,
            )
            for bucket in buckets
        },
        "reaccel_by_friction_r": {
            bucket: _stats(
                tuple(
                    row["trade"] for row in reaccel
                    if _bucket(float(row["entry_friction_r"])) == bucket
                ),
                trading_days,
            )
            for bucket in buckets
        },
        "reaccel_family_by_cost_cap": {
            f"{family}|LE_{int(cap*100):02d}R": _stats(
                tuple(
                    row["trade"] for row in reaccel
                    if str(row["family"]) == family
                    and float(row["entry_friction_r"]) <= cap
                ),
                trading_days,
            )
            for family in ("L12", "L20")
            for cap in COST_R_LIMITS
        },
    }


def evaluate_v43(
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
        raise ValueError("V43_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_transition_outcome_context(rows)
    h1_context = build_h1_context(rows)
    trading_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(trading_dates)

    selected_variants = tuple(
        x for x in M15_VARIANTS if x.variant_id in {L12_ID, L20_ID}
    )
    signal_map = {
        variant.variant_id: extract_m15_breakout(rows, variant=variant)
        for variant in selected_variants
    }

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )

        m15_all: list[TournamentTrade] = []
        for variant in selected_variants:
            m15_all.extend(
                simulate_m15(
                    rows,
                    signals=signal_map[variant.variant_id],
                    costs=costs,
                    pip_size=pip_size,
                )
            )
        m15 = _period(tuple(m15_all), start=start, end=end)
        base_annotated = annotate_outcome_m15(
            m15,
            d1_context=d1_context,
            h1_context=h1_context,
        )
        annotated = _annotate_cost(base_annotated, pip_size=pip_size, costs=costs)

        routes = {route: _select(annotated, route) for route in ROUTES}
        portfolios: dict[str, Any] = {
            "D1_CLASSIC_ONLY": _stats(classic, trading_days),
        }

        for route, selected in routes.items():
            combined = _limit_concurrency(_dedupe_with_classic((*classic, *selected)))
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
            portfolios[f"D1_CLASSIC_PLUS_{route}"] = payload

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "entry_friction_pips": _friction_pips(costs),
            "portfolios": portfolios,
            "routed_m15": {
                route: _stats(trades, trading_days)
                for route, trades in routes.items()
            },
            "diagnostics": _diagnostics(annotated, trading_days=trading_days),
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
            "entry_family": "FROZEN_V20_L12_L20",
            "d1_h1_architecture": "D1_DIRECTION_OR_REACCELERATION_PLUS_H1_NORMAL_PERMISSION",
            "cost_gate_is_ex_ante": True,
            "friction_formula": "(spread*multiplier + slippage*multiplier + commission_round_trip) / initial_risk",
            "swap_excluded_from_entry_gate": True,
            "cost_r_limits": list(COST_R_LIMITS),
            "dense_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "routes": list(ROUTES),
        "scenario_results": scenario_results,
        "note": (
            "V43 tests whether ex-ante transaction-cost burden explains the cross-era "
            "failure of M15 while preserving frozen entry logic."
        ),
    }
