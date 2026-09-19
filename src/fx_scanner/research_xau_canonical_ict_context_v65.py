from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .demo_xau_m15_ict_layer import evaluate_ict_execution_context
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    extract_signals as extract_m15_breakout,
    simulate as simulate_m15,
)
from .research_xau_hierarchical_regime_router_v35 import (
    L12_ID,
    L20_ID,
    _direction_metrics,
    _max_losing_streak,
    _period,
)
from .research_xau_multihorizon_100usd_v20 import M15_VARIANTS
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_CANONICAL_ICT_CONTEXT_V65"
ARTIFACT_CONTRACT = "XAU_CANONICAL_ICT_CONTEXT_V65_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FAMILY_IDS = {"L12": L12_ID, "L20": L20_ID}
CONTEXT_WINDOW_M15 = 700


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


def _signal_key(trade: TournamentTrade) -> tuple[str, Any, str]:
    return (
        str(trade.strategy_id),
        ensure_utc(trade.signal_at),
        str(trade.direction).upper(),
    )


def _build_context_map(
    rows: Sequence[Bar],
    trades: Sequence[TournamentTrade],
) -> dict[tuple[str, Any, str], dict[str, Any]]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    output: dict[tuple[str, Any, str], dict[str, Any]] = {}
    for trade in trades:
        key = _signal_key(trade)
        if key in output:
            continue
        i = int(trade.signal_index)
        if i < 0 or i >= len(bars):
            continue
        window = bars[max(0, i - CONTEXT_WINDOW_M15 + 1): i + 1]
        context = evaluate_ict_execution_context(
            window,
            direction=str(trade.direction).upper(),
            atr_value=float(trade.atr_at_signal),
            as_of=ensure_utc(trade.signal_at) + timedelta(minutes=15),
        )
        output[key] = {
            "available": bool(context.available),
            "execution_ready": bool(context.execution_ready),
            "fvg_retest": bool(context.fvg_retest),
            "order_block_retest": bool(context.order_block_retest),
            "ote_retest": bool(context.ote_retest),
            "premium_discount_ok": bool(context.premium_discount_ok),
            "swept_liquidity": bool(context.swept_liquidity),
            "anti_chase_ok": bool(context.anti_chase_ok),
            "external_target_available": context.external_liquidity_target is not None,
            "internal_target_available": context.internal_liquidity_target is not None,
            "confluence_count": int(context.confluence_count),
            "reasons": tuple(context.reasons),
        }
    return output


def _bucket_boolean(
    trades: Sequence[TournamentTrade],
    *,
    context_map: Mapping[tuple[str, Any, str], Mapping[str, Any]],
    key: str,
    trading_days: int,
) -> dict[str, Any]:
    groups: dict[bool, list[TournamentTrade]] = {False: [], True: []}
    unavailable: list[TournamentTrade] = []
    for trade in trades:
        context = context_map.get(_signal_key(trade))
        if context is None:
            unavailable.append(trade)
            continue
        groups[bool(context.get(key))].append(trade)
    return {
        "TRUE": _stats(tuple(groups[True]), trading_days),
        "FALSE": _stats(tuple(groups[False]), trading_days),
        "UNAVAILABLE": _stats(tuple(unavailable), trading_days),
    }


def _bucket_confluence(
    trades: Sequence[TournamentTrade],
    *,
    context_map: Mapping[tuple[str, Any, str], Mapping[str, Any]],
    trading_days: int,
) -> dict[str, Any]:
    groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    for trade in trades:
        context = context_map.get(_signal_key(trade))
        if context is None:
            groups["UNAVAILABLE"].append(trade)
            continue
        count = int(context.get("confluence_count") or 0)
        bucket = str(count) if count <= 2 else "3_PLUS"
        groups[bucket].append(trade)
    return {
        bucket: _stats(tuple(groups.get(bucket, ())), trading_days)
        for bucket in ("0", "1", "2", "3_PLUS", "UNAVAILABLE")
    }


def _payload(
    trades: Sequence[TournamentTrade],
    *,
    context_map: Mapping[tuple[str, Any, str], Mapping[str, Any]],
    trading_days: int,
) -> dict[str, Any]:
    return {
        "all": _stats(trades, trading_days),
        "execution_ready": _bucket_boolean(
            trades,
            context_map=context_map,
            key="execution_ready",
            trading_days=trading_days,
        ),
        "fvg_retest": _bucket_boolean(
            trades,
            context_map=context_map,
            key="fvg_retest",
            trading_days=trading_days,
        ),
        "order_block_retest": _bucket_boolean(
            trades,
            context_map=context_map,
            key="order_block_retest",
            trading_days=trading_days,
        ),
        "ote_retest": _bucket_boolean(
            trades,
            context_map=context_map,
            key="ote_retest",
            trading_days=trading_days,
        ),
        "premium_discount_ok": _bucket_boolean(
            trades,
            context_map=context_map,
            key="premium_discount_ok",
            trading_days=trading_days,
        ),
        "swept_liquidity": _bucket_boolean(
            trades,
            context_map=context_map,
            key="swept_liquidity",
            trading_days=trading_days,
        ),
        "anti_chase_ok": _bucket_boolean(
            trades,
            context_map=context_map,
            key="anti_chase_ok",
            trading_days=trading_days,
        ),
        "external_target_available": _bucket_boolean(
            trades,
            context_map=context_map,
            key="external_target_available",
            trading_days=trading_days,
        ),
        "confluence_count": _bucket_confluence(
            trades,
            context_map=context_map,
            trading_days=trading_days,
        ),
    }


def evaluate_v65(
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
        raise ValueError("V65_EMPTY_HISTORY")
    start = ensure_utc(era_start)
    end = ensure_utc(era_end)
    trading_dates = sorted(
        {
            ensure_utc(row.timestamp).date()
            for row in rows
            if start <= ensure_utc(row.timestamp) < end
        }
    )
    trading_days = len(trading_dates)

    variants = {
        family: next(x for x in M15_VARIANTS if x.variant_id == variant_id)
        for family, variant_id in FAMILY_IDS.items()
    }
    signals = {
        family: extract_m15_breakout(rows, variant=variant)
        for family, variant in variants.items()
    }

    # Signal geometry is identical across cost scenarios. Build ICT context once
    # from the first scenario's simulated trades and reuse by signal identity.
    first_costs = next(iter(cost_scenarios.values()))
    reference_trades: list[TournamentTrade] = []
    for family in FAMILY_IDS:
        reference_trades.extend(
            _period(
                simulate_m15(
                    rows,
                    signals=signals[family],
                    costs=first_costs,
                    pip_size=pip_size,
                ),
                start=start,
                end=end,
            )
        )
    context_map = _build_context_map(rows, reference_trades)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        by_family: dict[str, tuple[TournamentTrade, ...]] = {}
        combined: list[TournamentTrade] = []
        for family in FAMILY_IDS:
            trades = _period(
                simulate_m15(
                    rows,
                    signals=signals[family],
                    costs=costs,
                    pip_size=pip_size,
                ),
                start=start,
                end=end,
            )
            by_family[family] = trades
            combined.extend(trades)
        combined = sorted(
            combined,
            key=lambda x: (
                ensure_utc(x.entry_at),
                str(x.strategy_id),
                str(x.direction),
            ),
        )
        scenario_results[cost_id] = {
            "families": {
                family: _payload(
                    trades,
                    context_map=context_map,
                    trading_days=trading_days,
                )
                for family, trades in by_family.items()
            },
            "combined": _payload(
                tuple(combined),
                context_map=context_map,
                trading_days=trading_days,
            ),
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
        "era_trading_days": trading_days,
        "ict_context_signals": len(context_map),
        "preregistered_contract": {
            "ict_contract": "ICT_XAU_M15_EXECUTION_CONTEXT_V1",
            "canonical_ict_layer_reused_without_parameter_changes": True,
            "context_window_m15_bars": CONTEXT_WINDOW_M15,
            "features_reported": [
                "execution_ready",
                "fvg_retest",
                "order_block_retest",
                "ote_retest",
                "premium_discount_ok",
                "swept_liquidity",
                "anti_chase_ok",
                "external_target_available",
                "confluence_count",
            ],
            "entry_families": FAMILY_IDS,
            "trade_filter_applied": False,
            "ict_feature_selected_as_winner": False,
            "entry_signal_logic_retuned": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V65 audits the existing canonical ICT execution-context layer against frozen L12/L20 "
            "historical trades. No ICT feature is allowed to filter or modify a trade in this study."
        ),
    }
