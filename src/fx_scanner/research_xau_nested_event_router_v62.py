from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
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
from .research_xau_era_robustness_v31 import (
    _dedupe_with_classic,
    _simulate_d1_classic,
)
from .research_xau_h1_event_stability_v61 import (
    EVENTS,
    FULL_END,
    FULL_START,
    FROZEN_ROUTE,
)
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

RESEARCH_VERSION = "XAU_NESTED_EVENT_ROUTER_V62"
ARTIFACT_CONTRACT = "XAU_NESTED_EVENT_ROUTER_V62_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")
EVENT_STREAMS = (*EVENTS, "NONE")


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


def _unique(trades: Sequence[TournamentTrade]) -> tuple[TournamentTrade, ...]:
    chosen: dict[tuple[Any, ...], TournamentTrade] = {}
    for trade in sorted(
        trades,
        key=lambda x: (
            ensure_utc(x.entry_at),
            str(x.strategy_id),
            str(x.direction),
        ),
    ):
        key = (
            str(x := trade.strategy_id),
            ensure_utc(trade.entry_at),
            ensure_utc(trade.exit_at),
            str(trade.direction),
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
                str(x.strategy_id),
                str(x.direction),
            ),
        )
    )


def _net_r(stats: Mapping[str, Any]) -> float:
    metrics = stats["metrics"]
    return float(metrics.get("gross_profit_r") or 0.0) - float(
        metrics.get("gross_loss_r") or 0.0
    )


def _window_payload(
    *,
    core: Sequence[TournamentTrade],
    v47_portfolio: Sequence[TournamentTrade],
    nested_portfolio: Sequence[TournamentTrade],
    satellite_v47: Sequence[TournamentTrade],
    satellite_nested: Sequence[TournamentTrade],
    trading_dates,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    days = sum(1 for d in trading_dates if start.date() <= d < end.date())

    def pick(values):
        return tuple(
            trade
            for trade in values
            if start <= ensure_utc(trade.entry_at) < end
        )

    core_s = _stats(pick(core), days)
    v47_s = _stats(pick(v47_portfolio), days)
    nested_s = _stats(pick(nested_portfolio), days)
    sat_v47_s = _stats(pick(satellite_v47), days)
    sat_nested_s = _stats(pick(satellite_nested), days)

    return {
        "core": core_s,
        "v47_portfolio": v47_s,
        "nested_portfolio": nested_s,
        "v47_satellite": sat_v47_s,
        "nested_satellite": sat_nested_s,
        "nested_incremental_vs_core_r": _net_r(nested_s) - _net_r(core_s),
        "v47_incremental_vs_core_r": _net_r(v47_s) - _net_r(core_s),
        "nested_delta_vs_v47_r": _net_r(nested_s) - _net_r(v47_s),
        "nested_drawdown_delta_vs_core_r": (
            float(nested_s["metrics"].get("max_drawdown_r") or 0.0)
            - float(core_s["metrics"].get("max_drawdown_r") or 0.0)
        ),
        "nested_drawdown_delta_vs_v47_r": (
            float(nested_s["metrics"].get("max_drawdown_r") or 0.0)
            - float(v47_s["metrics"].get("max_drawdown_r") or 0.0)
        ),
    }


def _rolling_three_year(
    *,
    core,
    v47_portfolio,
    nested_portfolio,
    satellite_v47,
    satellite_nested,
    trading_dates,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for year in range(FULL_START.year, FULL_END.year - 1):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 3, 1, 1, tzinfo=timezone.utc)
        out[f"{year}_{year+2}"] = _window_payload(
            core=core,
            v47_portfolio=v47_portfolio,
            nested_portfolio=nested_portfolio,
            satellite_v47=satellite_v47,
            satellite_nested=satellite_nested,
            trading_dates=trading_dates,
            start=start,
            end=end,
        )
    return out


def _annual(
    *,
    core,
    v47_portfolio,
    nested_portfolio,
    satellite_v47,
    satellite_nested,
    trading_dates,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for year in range(FULL_START.year, FULL_END.year + 1):
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        out[str(year)] = _window_payload(
            core=core,
            v47_portfolio=v47_portfolio,
            nested_portfolio=nested_portfolio,
            satellite_v47=satellite_v47,
            satellite_nested=satellite_nested,
            trading_dates=trading_dates,
            start=start,
            end=end,
        )
    return out


def evaluate_v62(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
    broker_spec: BrokerLotSpec,
    leverage_tiers: Sequence[LeverageTier],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V62_EMPTY_HISTORY")

    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V62_MISSING_REQUIRED_COSTS:{missing}")

    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    structure_context = build_h1_structure_context(rows)
    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=FULL_END,
    )
    era_dates = _trading_dates(rows, start=FULL_START, end=FULL_END)
    era_days = len(era_dates)

    scenarios: dict[str, Any] = {}
    for cost_id in REQUIRED_COSTS:
        costs = cost_scenarios[cost_id]
        core = _period(
            _simulate_d1_classic(rows, costs=costs, pip_size=pip_size),
            start=FULL_START,
            end=FULL_END,
        )
        annotated_by_family = _family_streams(
            rows,
            costs=costs,
            pip_size=pip_size,
            d1_context=d1_context,
            h1_context=h1_context,
        )

        family_gated_all: list[TournamentTrade] = []
        family_gates: dict[str, Any] = {}
        for family in FAMILY_MAP:
            candidate = _route_family_candidates(
                annotated_by_family[family],
                route=FROZEN_ROUTE,
            )
            gated, gate = gate_family_causally(
                candidate,
                trading_dates=full_dates,
            )
            gated = _period(gated, start=FULL_START, end=FULL_END)
            family_gated_all.extend(gated)
            family_gates[family] = {
                **gate,
                "era_metrics": _metrics(gated),
            }

        v47_satellite = _unique(family_gated_all)
        annotated_structure = _annotate_trade_structure(
            v47_satellite,
            structure_context=structure_context,
        )

        event_candidates: dict[str, list[TournamentTrade]] = defaultdict(list)
        for trade, context in annotated_structure:
            event = str(context.get("last_break_event") or "NONE")
            if event not in EVENT_STREAMS:
                event = "NONE"
            event_candidates[event].append(trade)

        nested_all: list[TournamentTrade] = []
        event_gates: dict[str, Any] = {}
        for event in EVENT_STREAMS:
            candidate_stream = tuple(event_candidates.get(event, ()))
            gated_stream, gate = gate_family_causally(
                candidate_stream,
                trading_dates=full_dates,
            )
            gated_stream = _period(
                gated_stream,
                start=FULL_START,
                end=FULL_END,
            )
            nested_all.extend(gated_stream)
            event_gates[event] = {
                **gate,
                "candidate_full_metrics": _metrics(candidate_stream),
                "nested_era_metrics": _metrics(gated_stream),
            }

        nested_satellite = _unique(nested_all)
        v47_portfolio = _limit_concurrency(
            _dedupe_with_classic((*core, *v47_satellite))
        )
        nested_portfolio = _limit_concurrency(
            _dedupe_with_classic((*core, *nested_satellite))
        )

        rolling = _rolling_three_year(
            core=core,
            v47_portfolio=v47_portfolio,
            nested_portfolio=nested_portfolio,
            satellite_v47=v47_satellite,
            satellite_nested=nested_satellite,
            trading_dates=era_dates,
        )
        annual = _annual(
            core=core,
            v47_portfolio=v47_portfolio,
            nested_portfolio=nested_portfolio,
            satellite_v47=v47_satellite,
            satellite_nested=nested_satellite,
            trading_dates=era_dates,
        )

        negative_nested_vs_core = [
            key
            for key, payload in rolling.items()
            if int(payload["nested_portfolio"]["trades"]) > 0
            and float(payload["nested_incremental_vs_core_r"]) < 0.0
        ]
        negative_nested_vs_v47 = [
            key
            for key, payload in rolling.items()
            if int(payload["nested_portfolio"]["trades"]) > 0
            and float(payload["nested_delta_vs_v47_r"]) < 0.0
        ]

        scenario = {
            "costs": asdict(costs),
            "family_gates": family_gates,
            "event_gates": event_gates,
            "core": _stats(core, era_days),
            "v47_satellite": _stats(v47_satellite, era_days),
            "nested_satellite": _stats(nested_satellite, era_days),
            "v47_portfolio": _stats(v47_portfolio, era_days),
            "nested_portfolio": _stats(nested_portfolio, era_days),
            "annual": annual,
            "rolling_3y": rolling,
            "summary": {
                "nested_full_incremental_vs_core_r": (
                    _net_r(_stats(nested_portfolio, era_days))
                    - _net_r(_stats(core, era_days))
                ),
                "v47_full_incremental_vs_core_r": (
                    _net_r(_stats(v47_portfolio, era_days))
                    - _net_r(_stats(core, era_days))
                ),
                "nested_full_delta_vs_v47_r": (
                    _net_r(_stats(nested_portfolio, era_days))
                    - _net_r(_stats(v47_portfolio, era_days))
                ),
                "nested_dd_delta_vs_core_r": (
                    float(_stats(nested_portfolio, era_days)["metrics"].get("max_drawdown_r") or 0.0)
                    - float(_stats(core, era_days)["metrics"].get("max_drawdown_r") or 0.0)
                ),
                "negative_rolling_nested_vs_core": negative_nested_vs_core,
                "negative_rolling_nested_vs_v47": negative_nested_vs_v47,
            },
        }
        if cost_id == "V24_STRESS_4675":
            scenario["nested_cash_fixed_001"] = _cash_path_stopout_safe(
                nested_portfolio,
                spec=broker_spec,
                tiers=leverage_tiers,
                account_leverage=ACCOUNT_LEVERAGE,
                stopout_pct=MARGIN_FLOOR_PCT,
                trading_dates=era_dates,
            )
        scenarios[cost_id] = scenario

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
            "base_route": FROZEN_ROUTE,
            "required_costs": list(REQUIRED_COSTS),
            "first_gate": "V47 L12/L20 FAMILY HEALTH",
            "second_gate": "H1 BREAK EVENT HEALTH",
            "event_streams": list(EVENT_STREAMS),
            "no_event_preselected_as_winner": True,
            "event_gate_lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "event_gate_min_completed_trades": MIN_COMPLETED_TRADES,
            "event_gate_min_pf": MIN_TRAILING_PF,
            "event_gate_min_expectancy_r": MIN_TRAILING_EXPECTANCY_R,
            "event_gate_thresholds_identical_to_v47": True,
            "market_structure_can_only_suppress_v47_trades": True,
            "market_structure_cannot_open_new_v47_ineligible_trades": True,
            "signal_logic_retuned": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V62 nests a second causal health gate by H1 BOS/MSS event inside the already-frozen "
            "V47/V48 satellite. It cannot reopen trades rejected by V47. All event types are "
            "eligible to self-qualify; no static MSS/BOS winner is hard-coded."
        ),
    }
