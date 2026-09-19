from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_100usd_stopout_v23 import _cash_path_stopout_safe
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    LOOKBACK_TRADING_DAYS,
    MIN_COMPLETED_TRADES,
    MIN_TRAILING_EXPECTANCY_R,
    MIN_TRAILING_PF,
    _family_streams,
    _route_family_candidates,
    gate_family_causally,
)
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_h1_structure_context_v56 import (
    _annotate_trade_structure,
    build_h1_structure_context,
)
from .research_xau_hierarchical_regime_router_v35 import (
    ACCOUNT_LEVERAGE,
    MARGIN_FLOOR_PCT,
    _direction_metrics,
    _max_losing_streak,
    _period,
    build_h1_context,
)
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_CAUSAL_STRUCTURE_ROUTER_V57"
ARTIFACT_CONTRACT = "XAU_CAUSAL_STRUCTURE_ROUTER_V57_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

BASE_ROUTE = "LONG_REACCEL_COST10"
ROUTER_TYPES = ("BREAK_EVENT", "STRUCTURE_STATE")

BREAK_STREAMS = (
    "BULL_BOS",
    "BULL_MSS",
    "BEAR_BOS",
    "BEAR_MSS",
    "NONE",
)
STRUCTURE_STREAMS = (
    "BULL_HH_HL",
    "BEAR_LH_LL",
    "MIXED_OR_RANGE",
    "INSUFFICIENT",
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


def _stream_name(row: Mapping[str, Any], router_type: str) -> str:
    if router_type == "BREAK_EVENT":
        value = str(row.get("last_break_event") or "NONE")
        return value if value in BREAK_STREAMS else "NONE"
    if router_type == "STRUCTURE_STATE":
        value = str(row.get("structure_state") or "INSUFFICIENT")
        return value if value in STRUCTURE_STREAMS else "INSUFFICIENT"
    raise ValueError(f"V57_ROUTER_INVALID:{router_type}")


def _unique(trades: Sequence[TournamentTrade]) -> tuple[TournamentTrade, ...]:
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
            str(trade.strategy_id),
            round(float(trade.entry_price), 8),
            round(float(trade.stop_loss), 8),
            round(float(trade.take_profit), 8),
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


def evaluate_v57(
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
        raise ValueError("V57_EMPTY_HISTORY")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    structure_context = build_h1_structure_context(rows)

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

        family_candidates: dict[str, tuple[TournamentTrade, ...]] = {}
        combined_candidate: list[TournamentTrade] = []
        for family in FAMILY_MAP:
            candidate = _route_family_candidates(
                annotated_by_family[family],
                route=BASE_ROUTE,
            )
            family_candidates[family] = candidate
            combined_candidate.extend(candidate)

        candidate_all = _unique(combined_candidate)
        structure_annotated = _annotate_trade_structure(
            candidate_all,
            structure_context=structure_context,
        )

        routers: dict[str, Any] = {}
        for router_type in ROUTER_TYPES:
            stream_candidates: dict[str, list[TournamentTrade]] = defaultdict(list)
            for trade, row in structure_annotated:
                stream_candidates[_stream_name(row, router_type)].append(trade)

            stream_names = (
                BREAK_STREAMS if router_type == "BREAK_EVENT" else STRUCTURE_STREAMS
            )
            stream_payload: dict[str, Any] = {}
            gated_all: list[TournamentTrade] = []
            for stream in stream_names:
                candidate_stream = tuple(stream_candidates.get(stream, ()))
                gated, gate = gate_family_causally(
                    candidate_stream,
                    trading_dates=full_dates,
                )
                gated_era = _period(gated, start=start, end=end)
                gated_all.extend(gated_era)
                stream_payload[stream] = {
                    **gate,
                    "all_candidate_metrics": _metrics(candidate_stream),
                    "era_ungated_metrics": _metrics(
                        _period(candidate_stream, start=start, end=end)
                    ),
                    "era_gated_metrics": _metrics(gated_era),
                }

            gated_era_all = _unique(gated_all)
            ungated_era_all = _period(candidate_all, start=start, end=end)
            ungated_portfolio = _limit_concurrency(
                _dedupe_with_classic((*classic, *ungated_era_all))
            )
            gated_portfolio = _limit_concurrency(
                _dedupe_with_classic((*classic, *gated_era_all))
            )

            payload = {
                "streams": stream_payload,
                "ungated_satellite": _stats(ungated_era_all, era_days),
                "gated_satellite": _stats(gated_era_all, era_days),
                "ungated_d1_plus_satellite": _stats(ungated_portfolio, era_days),
                "gated_d1_plus_satellite": _stats(gated_portfolio, era_days),
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
            routers[router_type] = payload

        scenario_results[cost_id] = {
            "costs": asdict(costs),
            "core_d1_classic": _stats(classic, era_days),
            "base_route_ungated": _stats(
                _period(candidate_all, start=start, end=end),
                era_days,
            ),
            "routers": routers,
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
            "base_route": BASE_ROUTE,
            "base_route_reason": (
                "broader frozen V47 reacceleration route restores old-era sample "
                "without selecting the V56 historical winner"
            ),
            "router_types": list(ROUTER_TYPES),
            "break_streams": list(BREAK_STREAMS),
            "structure_streams": list(STRUCTURE_STREAMS),
            "all_streams_self_qualify": True,
            "no_stream_preselected_as_winner": True,
            "gate_lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "gate_min_completed_trades": MIN_COMPLETED_TRADES,
            "gate_min_trailing_pf": MIN_TRAILING_PF,
            "gate_min_trailing_expectancy_r": MIN_TRAILING_EXPECTANCY_R,
            "gate_thresholds_identical_to_v40_v47_v52_v53": True,
            "suppressed_signals_continue_shadow_tracking": True,
            "pivot_definition_identical_to_v56": True,
            "signal_logic_retuned": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V57 is the causal validation of the V56 structure hypothesis. It does not hard-code "
            "BULL_MSS or exclude BULL_BOS. Every H1 structure/break stream must earn activation "
            "from trailing completed trades under the unchanged causal health gate."
        ),
    }
