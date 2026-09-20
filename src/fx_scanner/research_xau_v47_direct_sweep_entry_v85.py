from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, time, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .demo_xau_m15_ict_layer import evaluate_ict_execution_context
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    BreakoutSignal,
    simulate as simulate_m15,
)
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    _date_cutoff,
    _family_streams,
    _route_family_candidates,
    _trailing_health,
    gate_family_causally,
)
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    build_h1_context,
)
from .research_xau_m15_continuation_tournament import _indicator_series
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_secular_regime_router_v46 import COST_R_CAP, build_secular_d1

RESEARCH_VERSION = "XAU_V47_DIRECT_SWEEP_ENTRY_V85"
ARTIFACT_CONTRACT = "XAU_V47_DIRECT_SWEEP_ENTRY_V85_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
CONTEXT_WINDOW_M15 = 700
PIP_SIZE = 0.01

DIRECT_VARIANTS = {
    "L12": {
        "variant_id": "V85_DIRECT_SWEEP_L12_R150",
        "reward_r": 1.50,
        "cooldown_bars": 3,
    },
    "L20": {
        "variant_id": "V85_DIRECT_SWEEP_L20_R200",
        "reward_r": 2.00,
        "cooldown_bars": 4,
    },
}


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


def _friction_pips(costs: M15ResearchCosts) -> float:
    return (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
    )


def _family_health_at(
    *,
    ordered_exit: Sequence[TournamentTrade],
    exit_times: Sequence[datetime],
    signal_at: datetime,
    trading_dates: Sequence[Any],
) -> dict[str, Any]:
    stamp = ensure_utc(signal_at)
    completed_end = bisect_left(exit_times, stamp)
    cutoff_date = _date_cutoff(stamp, trading_dates=trading_dates)
    cutoff = datetime.combine(cutoff_date, time.min, tzinfo=timezone.utc)
    completed_start = bisect_left(exit_times, cutoff, hi=completed_end)
    return _trailing_health(ordered_exit[completed_start:completed_end])


def _base_route_ok(d1: Mapping[str, Any], h1: Mapping[str, Any]) -> bool:
    try:
        return bool(
            int(d1.get("regime_side") or 0) == 1
            and str(d1.get("secular_regime") or "") == "SECULAR_BULL"
            and str(d1.get("transition_outcome") or "") == "REACCELERATION"
            and 1 <= int(d1.get("post_transition_age_days") or 0) <= 20
            and float(h1.get("close")) > float(h1.get("ema200"))
            and float(h1.get("ema20")) > float(h1.get("ema50"))
        )
    except (TypeError, ValueError):
        return False


def _current_bar_sweeps_sellside(
    rows: Sequence[Bar],
    *,
    signal_index: int,
    atr_value: float,
) -> tuple[bool, tuple[str, ...]]:
    start = max(0, signal_index - CONTEXT_WINDOW_M15 + 1)
    window = tuple(rows[start:signal_index + 1])
    if not window:
        return False, ()

    signal = rows[signal_index]
    as_of = ensure_utc(signal.timestamp) + __import__("datetime").timedelta(minutes=15)
    ict = evaluate_ict_execution_context(
        window,
        direction="LONG",
        atr_value=float(atr_value),
        as_of=as_of,
    )
    if not ict.available:
        return False, ()

    levels = {
        "PDL": ict.previous_day_low,
        "ASIA_LOW": ict.asian_low,
        "LONDON_LOW": ict.london_low,
        "NEW_YORK_LOW": ict.new_york_low,
    }
    sources: list[str] = []
    for name, raw_level in levels.items():
        if raw_level is None:
            continue
        level = float(raw_level)
        if float(signal.low) < level and float(signal.close) > level:
            sources.append(str(name))
    return bool(sources), tuple(sorted(set(sources)))


def _extract_direct_signals(
    rows: Sequence[Bar],
    *,
    family: str,
    costs: M15ResearchCosts,
    d1_lookup: _Asof,
    h1_lookup: _Asof,
    health_history: Sequence[TournamentTrade],
    trading_dates: Sequence[Any],
) -> tuple[BreakoutSignal, ...]:
    cfg = DIRECT_VARIANTS[family]
    indicators = _indicator_series(rows)
    ordered_exit = tuple(sorted(health_history, key=lambda x: ensure_utc(x.exit_at)))
    exit_times = tuple(ensure_utc(x.exit_at) for x in ordered_exit)

    output: list[BreakoutSignal] = []
    last_signal_i: int | None = None
    friction_pips = _friction_pips(costs)

    for i in range(CONTEXT_WINDOW_M15, len(rows) - 1):
        atr_raw = indicators["atr"][i]
        if atr_raw is None:
            continue
        atr_value = float(atr_raw)
        if not isfinite(atr_value) or atr_value <= 0.0:
            continue

        signal_at = ensure_utc(rows[i].timestamp)
        d1 = d1_lookup.row(signal_at)
        h1 = h1_lookup.row(signal_at)
        if d1 is None or h1 is None or not _base_route_ok(d1, h1):
            continue

        health = _family_health_at(
            ordered_exit=ordered_exit,
            exit_times=exit_times,
            signal_at=signal_at,
            trading_dates=trading_dates,
        )
        if not bool(health.get("active")):
            continue

        swept, _ = _current_bar_sweeps_sellside(
            rows,
            signal_index=i,
            atr_value=atr_value,
        )
        if not swept:
            continue

        entry = float(rows[i + 1].open)
        stop = float(rows[i].low)
        risk = entry - stop
        if not isfinite(risk) or risk <= 0.0:
            continue
        risk_pips = risk / PIP_SIZE
        if risk_pips <= 0.0:
            continue
        entry_friction_r = friction_pips / risk_pips
        if entry_friction_r > COST_R_CAP:
            continue

        if last_signal_i is not None and i - last_signal_i < int(cfg["cooldown_bars"]):
            continue

        output.append(
            BreakoutSignal(
                variant_id=str(cfg["variant_id"]),
                symbol=str(rows[i].symbol),
                signal_index=i,
                direction="LONG",
                signal_at=signal_at,
                atr=atr_value,
                stop=stop,
                reward_r=float(cfg["reward_r"]),
            )
        )
        last_signal_i = i

    return tuple(output)


def _dedupe_direct(trades: Sequence[TournamentTrade]) -> tuple[TournamentTrade, ...]:
    priority = {
        "V85_DIRECT_SWEEP_L20_R200": 2,
        "V85_DIRECT_SWEEP_L12_R150": 1,
    }
    chosen: dict[tuple[Any, str], TournamentTrade] = {}
    for trade in sorted(trades, key=lambda x: (ensure_utc(x.entry_at), str(x.strategy_id))):
        key = (ensure_utc(trade.entry_at), str(trade.direction))
        current = chosen.get(key)
        if current is None or priority.get(str(trade.strategy_id), 0) > priority.get(
            str(current.strategy_id), 0
        ):
            chosen[key] = trade
    return tuple(sorted(chosen.values(), key=lambda x: ensure_utc(x.entry_at)))


def evaluate_v85(
    bars: Sequence[Bar],
    *,
    era_id: str,
    era_start,
    era_end,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V85_EMPTY_HISTORY")
    if abs(float(pip_size) - PIP_SIZE) > 1e-12:
        raise ValueError("V85_REQUIRES_XAU_PIP_SIZE_001")

    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    d1_lookup = _Asof(d1_context)
    h1_lookup = _Asof(h1_context)

    full_dates = _trading_dates(
        rows,
        start=ensure_utc(rows[0].timestamp),
        end=end,
    )
    era_dates = _trading_dates(rows, start=start, end=end)
    era_days = len(era_dates)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        annotated_by_family = _family_streams(
            rows,
            costs=costs,
            pip_size=pip_size,
            d1_context=d1_context,
            h1_context=h1_context,
        )

        baseline_by_family: dict[str, tuple[TournamentTrade, ...]] = {}
        candidate_by_family: dict[str, tuple[TournamentTrade, ...]] = {}
        baseline_gate_payload: dict[str, Any] = {}
        direct_by_family: dict[str, tuple[TournamentTrade, ...]] = {}
        signal_counts: dict[str, int] = {}

        for family in FAMILY_MAP:
            candidate = _route_family_candidates(
                annotated_by_family[family],
                route=FROZEN_ROUTE,
            )
            candidate_by_family[family] = candidate
            gated, gate = gate_family_causally(
                candidate,
                trading_dates=full_dates,
            )
            baseline_by_family[family] = _period(gated, start=start, end=end)
            baseline_gate_payload[family] = gate

            direct_signals = _extract_direct_signals(
                rows,
                family=family,
                costs=costs,
                d1_lookup=d1_lookup,
                h1_lookup=h1_lookup,
                health_history=candidate,
                trading_dates=full_dates,
            )
            signal_counts[family] = len(direct_signals)
            direct_trades = simulate_m15(
                rows,
                signals=direct_signals,
                costs=costs,
                pip_size=pip_size,
            )
            direct_by_family[family] = _period(
                direct_trades,
                start=start,
                end=end,
            )

        baseline_combined = tuple(
            trade
            for family in FAMILY_MAP
            for trade in baseline_by_family[family]
        )
        direct_combined = _dedupe_direct(
            tuple(
                trade
                for family in FAMILY_MAP
                for trade in direct_by_family[family]
            )
        )

        scenario_results[cost_id] = {
            "baseline_v47": {
                "combined": _stats(baseline_combined, era_days),
                "families": {
                    family: _stats(baseline_by_family[family], era_days)
                    for family in FAMILY_MAP
                },
                "gates": baseline_gate_payload,
            },
            "direct_sweep": {
                "combined_deduped": _stats(direct_combined, era_days),
                "families": {
                    family: {
                        **_stats(direct_by_family[family], era_days),
                        "all_history_signal_count": signal_counts[family],
                    }
                    for family in FAMILY_MAP
                },
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
        "era_trading_days": era_days,
        "preregistered_contract": {
            "base_regime": FROZEN_ROUTE,
            "entry": "next M15 open after current completed M15 bar sweeps canonical sell-side liquidity and closes back above it",
            "stop": "exact low of the sweep/reclaim signal bar; no added buffer",
            "max_hold_m15_bars": 16,
            "variants": DIRECT_VARIANTS,
            "family_permission": "corresponding L12/L20 V47 trailing-health gate must be active using only completed prior trades",
            "direct_entry_cost_r_cap": COST_R_CAP,
            "current_bar_sweep_only": True,
            "post_sweep_displacement_required": False,
            "fvg_required": False,
            "target_grid_search": False,
            "stop_grid_search": False,
            "signal_logic_selected_from_future_outcomes": False,
            "v69_forward_contract_changed": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V85 is a genuinely new execution-timing family inside the frozen V47 regime. "
            "It tests entry on the next M15 open immediately after a canonical current-bar "
            "sell-side sweep/reclaim, while inheriting L12/L20 reward-R, cooldown, family-health "
            "permission, V18 max hold, and the V47 cost/R cap. It does not alter V69/V77 forward experiments."
        ),
    }
