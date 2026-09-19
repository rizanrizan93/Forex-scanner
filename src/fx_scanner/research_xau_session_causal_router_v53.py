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
from .research_xau_m15_continuation_tournament import simulate_trades
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_session_liquidity_adaptive_v3 import (
    SESSION_EUROPE,
    SESSION_US,
    VARIANTS as SESSION_VARIANTS,
    _session_name,
    extract_session_signals,
)

RESEARCH_VERSION = "XAU_SESSION_CAUSAL_ROUTER_V53"
ARTIFACT_CONTRACT = "XAU_SESSION_CAUSAL_ROUTER_V53_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

SELECTED_VARIANT_IDS = (
    "XAU_V3_EUUS_REVERSAL_R15",
    "XAU_V3_EUUS_BREAKOUT_R15",
    "XAU_V3_EUUS_ADAPT_R20",
)
TARGET_SESSIONS = (SESSION_EUROPE, SESSION_US)
DIRECTIONS = ("LONG", "SHORT")

_VARIANT_BY_ID = {
    variant.variant_id: variant
    for variant in SESSION_VARIANTS
}
assert all(x in _VARIANT_BY_ID for x in SELECTED_VARIANT_IDS)


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


def _stream(
    trades: Sequence[TournamentTrade],
    *,
    rows: Sequence[Bar],
    target_session: str,
    direction: str,
) -> tuple[TournamentTrade, ...]:
    output: list[TournamentTrade] = []
    for trade in trades:
        i = int(trade.signal_index)
        if i < 0 or i >= len(rows):
            continue
        if _session_name(rows[i]) != target_session:
            continue
        if str(trade.direction).upper() != direction:
            continue
        output.append(trade)
    return tuple(output)


def _merge_unique(trades: Sequence[TournamentTrade]) -> tuple[TournamentTrade, ...]:
    chosen: dict[tuple[Any, ...], TournamentTrade] = {}
    for trade in sorted(
        trades,
        key=lambda x: (
            ensure_utc(x.entry_at),
            str(x.direction),
            str(x.strategy_id),
        ),
    ):
        key = (
            ensure_utc(trade.entry_at),
            ensure_utc(trade.exit_at),
            str(trade.direction),
            round(float(trade.entry_price), 8),
            round(float(trade.stop_price), 8),
            round(float(trade.target_price), 8),
        )
        chosen.setdefault(key, trade)
    return tuple(
        sorted(
            chosen.values(),
            key=lambda x: (
                ensure_utc(x.entry_at),
                str(x.direction),
                str(x.strategy_id),
            ),
        )
    )


def evaluate_v53(
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
        raise ValueError("V53_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=end,
    )
    era_dates = _trading_dates(rows, start=start, end=end)
    era_days = len(era_dates)

    signals_by_variant = {
        variant_id: extract_session_signals(
            rows,
            variant=_VARIANT_BY_ID[variant_id],
        )
        for variant_id in SELECTED_VARIANT_IDS
    }

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=start,
            end=end,
        )

        variants: dict[str, Any] = {}
        all_gated_for_combined: list[TournamentTrade] = []

        for variant_id in SELECTED_VARIANT_IDS:
            candidate_all = simulate_trades(
                rows,
                signals=signals_by_variant[variant_id],
                costs=costs,
            )

            gated_streams: dict[str, tuple[TournamentTrade, ...]] = {}
            gate_payload: dict[str, Any] = {}
            for target_session in TARGET_SESSIONS:
                for direction in DIRECTIONS:
                    stream_id = f"{target_session}_{direction}"
                    candidate_stream = _stream(
                        candidate_all,
                        rows=rows,
                        target_session=target_session,
                        direction=direction,
                    )
                    gated, gate = gate_family_causally(
                        candidate_stream,
                        trading_dates=full_dates,
                    )
                    gated_streams[stream_id] = gated
                    gate_payload[stream_id] = {
                        **gate,
                        "candidate_full_metrics": _metrics(candidate_stream),
                        "era_ungated_metrics": _metrics(
                            _period(candidate_stream, start=start, end=end)
                        ),
                        "era_gated_metrics": _metrics(
                            _period(gated, start=start, end=end)
                        ),
                    }

            ungated_era = _period(candidate_all, start=start, end=end)
            gated_era = _merge_unique(
                tuple(
                    trade
                    for stream in gated_streams.values()
                    for trade in _period(stream, start=start, end=end)
                )
            )
            all_gated_for_combined.extend(gated_era)

            ungated_portfolio = _limit_concurrency(
                _dedupe_with_classic((*classic, *ungated_era))
            )
            gated_portfolio = _limit_concurrency(
                _dedupe_with_classic((*classic, *gated_era))
            )

            variants[variant_id] = {
                "variant": asdict(_VARIANT_BY_ID[variant_id]),
                "ungated": _stats(ungated_era, era_days),
                "gated": _stats(gated_era, era_days),
                "gates": gate_payload,
                "ungated_d1_plus_session": _stats(ungated_portfolio, era_days),
                "gated_d1_plus_session": _stats(gated_portfolio, era_days),
            }

        combined_gated = _merge_unique(all_gated_for_combined)
        combined_portfolio = _limit_concurrency(
            _dedupe_with_classic((*classic, *combined_gated))
        )

        payload = {
            "costs": asdict(costs),
            "core_d1_classic": _stats(classic, era_days),
            "variants": variants,
            "combined_gated_session": _stats(combined_gated, era_days),
            "combined_d1_plus_gated_session": _stats(combined_portfolio, era_days),
        }
        if cost_id == "V24_STRESS_4675":
            payload["combined_cash_fixed_001"] = _cash_path_stopout_safe(
                combined_portfolio,
                spec=broker_spec,
                tiers=leverage_tiers,
                account_leverage=ACCOUNT_LEVERAGE,
                stopout_pct=MARGIN_FLOOR_PCT,
                trading_dates=era_dates,
            )
        scenario_results[cost_id] = payload

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
            "frozen_session_windows_utc": {
                "ASIA": "22:00-07:00",
                "EUROPE": "07:00-12:00",
                "US": "12:00-21:00",
            },
            "selected_frozen_v3_variants": list(SELECTED_VARIANT_IDS),
            "target_sessions_gated_independently": list(TARGET_SESSIONS),
            "directions_gated_independently": list(DIRECTIONS),
            "gate_lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "gate_min_completed_trades": MIN_COMPLETED_TRADES,
            "gate_min_trailing_pf": MIN_TRAILING_PF,
            "gate_min_trailing_expectancy_r": MIN_TRAILING_EXPECTANCY_R,
            "gate_thresholds_identical_to_v40_v47_v52": True,
            "suppressed_signals_continue_shadow_tracking": True,
            "session_hours_retuned": False,
            "v3_signal_geometry_retuned": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V53 does not invent another session strategy. It freezes the existing V3 "
            "session-liquidity families and tests whether Europe/US and LONG/SHORT streams "
            "can self-qualify causally using the unchanged V40/V47/V52 family-health gate."
        ),
    }
