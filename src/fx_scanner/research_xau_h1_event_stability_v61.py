from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    _family_streams,
    _route_family_candidates,
    gate_family_causally,
)
from .research_xau_h1_structure_context_v56 import (
    _annotate_trade_structure,
    build_h1_structure_context,
)
from .research_xau_hierarchical_regime_router_v35 import build_h1_context
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1
from .research_xau_v47_frozen_validation_v48 import FULL_END, FULL_START, FROZEN_ROUTE

RESEARCH_VERSION = "XAU_H1_EVENT_STABILITY_V61"
ARTIFACT_CONTRACT = "XAU_H1_EVENT_STABILITY_V61_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

EVENTS = ("BULL_MSS", "BULL_BOS", "BEAR_MSS", "BEAR_BOS")


def _metrics(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    return compute_metrics(tuple(trades)).payload()


def _stats(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    values = tuple(trades)
    return {
        "trades": len(values),
        "metrics": _metrics(values),
    }


def _year(trade: TournamentTrade) -> int:
    return ensure_utc(trade.entry_at).year


def evaluate_v61(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V61_EMPTY_HISTORY")

    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    structure_context = build_h1_structure_context(rows)
    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=FULL_END,
    )

    scenarios: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        families: dict[str, Any] = {}
        combined: list[TournamentTrade] = []

        for family in FAMILY_MAP:
            annotated = _family_streams(
                rows,
                costs=costs,
                pip_size=pip_size,
                d1_context=d1_context,
                h1_context=h1_context,
            )[family]
            candidate = _route_family_candidates(
                annotated,
                route=FROZEN_ROUTE,
            )
            gated, gate = gate_family_causally(
                candidate,
                trading_dates=full_dates,
            )
            gated = tuple(
                trade
                for trade in gated
                if FULL_START <= ensure_utc(trade.entry_at) < FULL_END
            )
            combined.extend(gated)

            by_event_year: dict[str, Any] = {}
            annotated_structure = _annotate_trade_structure(
                gated,
                structure_context=structure_context,
            )
            for year in range(FULL_START.year, FULL_END.year + 1):
                rows_year = [
                    (trade, ctx)
                    for trade, ctx in annotated_structure
                    if _year(trade) == year
                ]
                if not rows_year:
                    continue
                by_event_year[str(year)] = {
                    event: _stats(
                        tuple(
                            trade
                            for trade, ctx in rows_year
                            if str(ctx.get("last_break_event")) == event
                        )
                    )
                    for event in EVENTS
                }
                by_event_year[str(year)]["ALL"] = _stats(
                    tuple(trade for trade, _ in rows_year)
                )

            families[family] = {
                "gate": gate,
                "full_period": _stats(gated),
                "yearly_event_metrics": by_event_year,
            }

        combined = tuple(
            sorted(
                combined,
                key=lambda x: (ensure_utc(x.entry_at), str(x.strategy_id)),
            )
        )
        combined_structure = _annotate_trade_structure(
            combined,
            structure_context=structure_context,
        )
        combined_years: dict[str, Any] = {}
        for year in range(FULL_START.year, FULL_END.year + 1):
            rows_year = [
                (trade, ctx)
                for trade, ctx in combined_structure
                if _year(trade) == year
            ]
            if not rows_year:
                continue
            combined_years[str(year)] = {
                event: _stats(
                    tuple(
                        trade
                        for trade, ctx in rows_year
                        if str(ctx.get("last_break_event")) == event
                    )
                )
                for event in EVENTS
            }
            combined_years[str(year)]["ALL"] = _stats(
                tuple(trade for trade, _ in rows_year)
            )

        scenarios[cost_id] = {
            "families": families,
            "combined_full_period": _stats(combined),
            "combined_yearly_event_metrics": combined_years,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "period_start": FULL_START.isoformat(),
        "period_end_exclusive": FULL_END.isoformat(),
        "preregistered_contract": {
            "frozen_route": FROZEN_ROUTE,
            "frozen_families": FAMILY_MAP,
            "events_reported": list(EVENTS),
            "calendar_year_buckets_only": True,
            "event_filter_applied": False,
            "event_threshold_tuning": False,
            "signal_logic_retuned": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V61 is a stability diagnostic only. It asks whether the V56 BULL_MSS/BULL_BOS "
            "contrast repeats by calendar year and L12/L20 family inside the already-frozen "
            "V47/V48 route. It does not filter or resize trades."
        ),
    }
