from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_causal_regime_edge_gate_v47 import (
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
    gate_family_causally,
)
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_external_liquidity_cascade_v51 import (
    VARIANTS as V51_VARIANTS,
    extract_signals,
    simulate,
)
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    _direction_metrics,
    _max_losing_streak,
    _period,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_CAUSAL_CASCADE_GATE_V52"
ARTIFACT_CONTRACT = "XAU_CAUSAL_CASCADE_GATE_V52_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

DISCOVERY_VARIANTS = (
    "PD_CASCADE_D1_H1_2R",
    "PD_CASCADE_D1_H1_RANGE_CREDIBLE_2R",
)
assert all(x in V51_VARIANTS for x in DISCOVERY_VARIANTS)
DIRECTIONS = ("LONG", "SHORT")


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


def evaluate_v52(
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
        raise ValueError("V52_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=end,
    )
    era_dates = _trading_dates(rows, start=start, end=end)
    era_days = len(era_dates)
    signals = extract_signals(rows)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )

        variants: dict[str, Any] = {}
        for variant in DISCOVERY_VARIANTS:
            candidate_all = simulate(
                rows,
                signals=signals,
                variant=variant,
                costs=costs,
                pip_size=pip_size,
            )
            gated_by_direction: dict[str, tuple[TournamentTrade, ...]] = {}
            gates: dict[str, Any] = {}
            for direction in DIRECTIONS:
                candidate_dir = tuple(
                    x for x in candidate_all
                    if str(x.direction).upper() == direction
                )
                gated, gate = gate_family_causally(
                    candidate_dir,
                    trading_dates=full_dates,
                )
                gated_by_direction[direction] = gated
                gates[direction] = {
                    **gate,
                    "candidate_full_metrics": _metrics(candidate_dir),
                    "era_ungated_metrics": _metrics(
                        _period(candidate_dir, start=start, end=end)
                    ),
                    "era_gated_metrics": _metrics(
                        _period(gated, start=start, end=end)
                    ),
                }

            ungated_era = _period(candidate_all, start=start, end=end)
            gated_era = tuple(
                trade
                for direction in DIRECTIONS
                for trade in _period(
                    gated_by_direction[direction],
                    start=start,
                    end=end,
                )
            )
            gated_era = tuple(
                sorted(
                    gated_era,
                    key=lambda x: (
                        ensure_utc(x.entry_at),
                        str(x.direction),
                        str(x.strategy_id),
                    ),
                )
            )

            ungated_portfolio = _limit_concurrency(
                _dedupe_with_classic((*classic, *ungated_era))
            )
            gated_portfolio = _limit_concurrency(
                _dedupe_with_classic((*classic, *gated_era))
            )

            payload = {
                "ungated": _stats(ungated_era, era_days),
                "gated": _stats(gated_era, era_days),
                "gates": gates,
                "ungated_d1_plus_cascade": _stats(ungated_portfolio, era_days),
                "gated_d1_plus_cascade": _stats(gated_portfolio, era_days),
            }
            if cost_id == "V24_STRESS_4675":
                payload["gated_cash_fixed_001"] = _cash_path_stopout_safe(
                    gated_portfolio,
                    spec=broker_spec,
                    tiers=leverage_tiers,
                    account_leverage=ACCOUNT_LEVERAGE,
                    stopout_pct=MARGIN_FLOOR_PCT,
                    trading_dates=era_dates,
                )
            variants[variant] = payload

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "core_d1_classic": _stats(classic, era_days),
            "variants": variants,
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
            "discovery_variants": list(DISCOVERY_VARIANTS),
            "directions_gated_independently": list(DIRECTIONS),
            "gate_lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "gate_min_completed_trades": MIN_COMPLETED_TRADES,
            "gate_min_trailing_pf": MIN_TRAILING_PF,
            "gate_min_trailing_expectancy_r": MIN_TRAILING_EXPECTANCY_R,
            "gate_thresholds_identical_to_v40_v47": True,
            "suppressed_signals_continue_shadow_tracking": True,
            "year_or_era_feature_used": False,
            "v51_entry_geometry_retuned": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V52 tests whether the V51 external-liquidity cascade can self-qualify causally. "
            "LONG and SHORT are gated independently using the frozen V40/V47 thresholds; "
            "all suppressed cascade trades remain in the shadow history."
        ),
    }
