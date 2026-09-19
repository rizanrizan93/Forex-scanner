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
    annotate_m15,
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
from .research_xau_us_short_continuation_v2 import (
    VARIANTS as V2_VARIANTS,
    _directional_signals,
)
from .research_xau_m15_continuation_tournament import simulate_trades as simulate_continuation

RESEARCH_VERSION = "XAU_ASYMMETRIC_REGIME_FAMILY_V44"
ARTIFACT_CONTRACT = "XAU_ASYMMETRIC_REGIME_FAMILY_V44_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

LONG_COST_R_CAP = 0.10
SHORT_COST_R_CAP = 0.10
FROZEN_SHORT_VARIANT_ID = "XAU_V2_US_SHORT_L10_ADX15_R15"

ROUTES = (
    "LONG_REACCEL_COST10_ONLY",
    "SHORT_CONT_D1_H1_ONLY",
    "SHORT_CONT_D1_H1_COST10_ONLY",
    "SHORT_CONT_STRONG_D1_H1_COST10_ONLY",
    "ASYM_LONG_PLUS_SHORT_COST10",
    "ASYM_LONG_PLUS_STRONG_SHORT_COST10",
)


def _short_variant():
    for variant in V2_VARIANTS:
        if variant.variant_id == FROZEN_SHORT_VARIANT_ID:
            return variant
    raise ValueError("V44_FROZEN_SHORT_VARIANT_MISSING")


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


def _select_long(
    annotated: Sequence[Mapping[str, Any]],
) -> tuple[TournamentTrade, ...]:
    return tuple(
        row["trade"]
        for row in annotated
        if str(row["family"]) in {"L12", "L20"}
        and str(row["trade"].direction).upper() == "LONG"
        and str(row["transition_outcome"]) == "REACCELERATION"
        and 1 <= int(row["post_transition_age_days"]) <= 20
        and bool(row["d1_match"])
        and bool(row["h1_normal"])
        and float(row["entry_friction_r"]) <= LONG_COST_R_CAP
    )


def _select_short(
    annotated: Sequence[Mapping[str, Any]],
    *,
    require_cost_cap: bool,
    strong_d1_only: bool,
) -> tuple[TournamentTrade, ...]:
    out: list[TournamentTrade] = []
    for row in annotated:
        trade = row["trade"]
        if str(trade.direction).upper() != "SHORT":
            continue
        if not bool(row["d1_match"]) or not bool(row["h1_normal"]):
            continue
        if strong_d1_only and str(row["regime"]) != "STRONG_BEAR":
            continue
        if require_cost_cap and float(row["entry_friction_r"]) > SHORT_COST_R_CAP:
            continue
        out.append(trade)
    return tuple(out)


def evaluate_v44(
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
        raise ValueError("V44_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_transition_outcome_context(rows)
    h1_context = build_h1_context(rows)
    trading_dates = _trading_dates(rows, start=start, end=end)
    trading_days = len(trading_dates)

    long_variants = tuple(
        x for x in M15_VARIANTS if x.variant_id in {L12_ID, L20_ID}
    )
    long_signal_map = {
        variant.variant_id: extract_m15_breakout(rows, variant=variant)
        for variant in long_variants
    }

    short_variant = _short_variant()
    short_signals = _directional_signals(rows, variant=short_variant)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )

        long_all: list[TournamentTrade] = []
        for variant in long_variants:
            long_all.extend(
                simulate_m15(
                    rows,
                    signals=long_signal_map[variant.variant_id],
                    costs=costs,
                    pip_size=pip_size,
                )
            )
        long_trades = _period(tuple(long_all), start=start, end=end)
        long_annotated = annotate_outcome_m15(
            long_trades,
            d1_context=d1_context,
            h1_context=h1_context,
        )
        long_annotated = _annotate_cost(long_annotated, pip_size=pip_size, costs=costs)
        long_selected = _select_long(long_annotated)

        short_trades = _period(
            simulate_continuation(rows, signals=short_signals, costs=costs),
            start=start,
            end=end,
        )
        short_annotated = annotate_m15(
            short_trades,
            d1_context=d1_context,
            h1_context=h1_context,
        )
        short_annotated = _annotate_cost(short_annotated, pip_size=pip_size, costs=costs)
        short_plain = _select_short(
            short_annotated,
            require_cost_cap=False,
            strong_d1_only=False,
        )
        short_cost10 = _select_short(
            short_annotated,
            require_cost_cap=True,
            strong_d1_only=False,
        )
        short_strong_cost10 = _select_short(
            short_annotated,
            require_cost_cap=True,
            strong_d1_only=True,
        )

        route_map = {
            "LONG_REACCEL_COST10_ONLY": long_selected,
            "SHORT_CONT_D1_H1_ONLY": short_plain,
            "SHORT_CONT_D1_H1_COST10_ONLY": short_cost10,
            "SHORT_CONT_STRONG_D1_H1_COST10_ONLY": short_strong_cost10,
            "ASYM_LONG_PLUS_SHORT_COST10": (*long_selected, *short_cost10),
            "ASYM_LONG_PLUS_STRONG_SHORT_COST10": (*long_selected, *short_strong_cost10),
        }

        portfolios: dict[str, Any] = {
            "D1_CLASSIC_ONLY": _stats(classic, trading_days),
        }
        for route, selected in route_map.items():
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
            portfolios[f"D1_CLASSIC_PLUS_{route}"] = payload

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "portfolios": portfolios,
            "routes": {
                route: _stats(tuple(selected), trading_days)
                for route, selected in route_map.items()
            },
            "component_counts": {
                "raw_long_l12_l20": len(long_trades),
                "selected_long_reaccel_cost10": len(long_selected),
                "raw_short_continuation": len(short_trades),
                "short_d1_h1": len(short_plain),
                "short_d1_h1_cost10": len(short_cost10),
                "short_strong_d1_h1_cost10": len(short_strong_cost10),
            },
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
            "architecture": "D1_DIRECTION -> H1_PERMISSION -> REGIME_SPECIFIC_M15_FAMILY",
            "long_family": "V20_L12_L20_REACCELERATION",
            "long_cost_r_cap": LONG_COST_R_CAP,
            "short_family": FROZEN_SHORT_VARIANT_ID,
            "short_cost_r_cap": SHORT_COST_R_CAP,
            "short_session": "US",
            "short_family_retuned": False,
            "entry_families_modified": False,
            "dense_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "routes": list(ROUTES),
        "scenario_results": scenario_results,
        "note": (
            "V44 tests asymmetric regime-specific entry families instead of forcing "
            "L12/L20 to serve both bull and bear regimes."
        ),
    }
