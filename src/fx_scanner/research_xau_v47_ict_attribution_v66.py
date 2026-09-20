from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_canonical_ict_context_v65 import (
    _build_context_map,
    _signal_key,
)
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    _family_streams,
    _route_family_candidates,
    gate_family_causally,
)
from .research_xau_hierarchical_regime_router_v35 import (
    _direction_metrics,
    _max_losing_streak,
    _period,
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_V47_ICT_ATTRIBUTION_V66"
ARTIFACT_CONTRACT = "XAU_V47_ICT_ATTRIBUTION_V66_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")
BOOLEAN_FEATURES = (
    "execution_ready",
    "fvg_retest",
    "order_block_retest",
    "ote_retest",
    "premium_discount_ok",
    "swept_liquidity",
    "anti_chase_ok",
    "external_target_available",
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


def _unique(trades: Sequence[TournamentTrade]) -> tuple[TournamentTrade, ...]:
    seen: set[tuple[Any, ...]] = set()
    out: list[TournamentTrade] = []
    for trade in sorted(
        trades,
        key=lambda x: (
            ensure_utc(x.entry_at),
            str(x.strategy_id),
            str(x.direction),
        ),
    ):
        key = (
            str(trade.strategy_id),
            ensure_utc(trade.signal_at),
            ensure_utc(trade.entry_at),
            ensure_utc(trade.exit_at),
            str(trade.direction),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(trade)
    return tuple(out)


def _feature_payload(
    trades: Sequence[TournamentTrade],
    *,
    context_map: Mapping[tuple[str, Any, str], Mapping[str, Any]],
    trading_days: int,
) -> dict[str, Any]:
    boolean_payload: dict[str, Any] = {}
    for feature in BOOLEAN_FEATURES:
        yes: list[TournamentTrade] = []
        no: list[TournamentTrade] = []
        unavailable: list[TournamentTrade] = []
        for trade in trades:
            ctx = context_map.get(_signal_key(trade))
            if ctx is None:
                unavailable.append(trade)
            elif bool(ctx.get(feature)):
                yes.append(trade)
            else:
                no.append(trade)
        boolean_payload[feature] = {
            "TRUE": _stats(tuple(yes), trading_days),
            "FALSE": _stats(tuple(no), trading_days),
            "UNAVAILABLE": _stats(tuple(unavailable), trading_days),
        }

    confluence: dict[str, list[TournamentTrade]] = defaultdict(list)
    for trade in trades:
        ctx = context_map.get(_signal_key(trade))
        if ctx is None:
            confluence["UNAVAILABLE"].append(trade)
            continue
        count = int(ctx.get("confluence_count") or 0)
        confluence[str(count) if count <= 2 else "3_PLUS"].append(trade)

    return {
        "all": _stats(tuple(trades), trading_days),
        "boolean_features": boolean_payload,
        "confluence_count": {
            bucket: _stats(tuple(confluence.get(bucket, ())), trading_days)
            for bucket in ("0", "1", "2", "3_PLUS", "UNAVAILABLE")
        },
    }


def _slice(
    trades: Sequence[TournamentTrade],
    *,
    start: datetime,
    end: datetime,
) -> tuple[TournamentTrade, ...]:
    return tuple(
        trade
        for trade in trades
        if start <= ensure_utc(trade.entry_at) < end
    )


def evaluate_v66(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V66_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V66_MISSING_REQUIRED_COSTS:{missing}")

    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
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
        annotated_by_family = _family_streams(
            rows,
            costs=costs,
            pip_size=pip_size,
            d1_context=d1_context,
            h1_context=h1_context,
        )

        gated_all: list[TournamentTrade] = []
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
            gated_all.extend(gated)
            family_gates[family] = {
                **gate,
                "era_metrics": _metrics(gated),
            }

        satellite = _unique(gated_all)
        context_map = _build_context_map(rows, satellite)

        annual: dict[str, Any] = {}
        for year in range(FULL_START.year, FULL_END.year + 1):
            start = datetime(year, 1, 1, tzinfo=timezone.utc)
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            period = _slice(satellite, start=start, end=end)
            if not period:
                continue
            days = sum(1 for d in era_dates if start.date() <= d < end.date())
            annual[str(year)] = _feature_payload(
                period,
                context_map=context_map,
                trading_days=days,
            )

        diagnostic_windows = {}
        for label, start, end in (
            (
                "WEAK_2022_2024",
                datetime(2022, 1, 1, tzinfo=timezone.utc),
                datetime(2025, 1, 1, tzinfo=timezone.utc),
            ),
            (
                "RECENT_2025_2026YTD",
                datetime(2025, 1, 1, tzinfo=timezone.utc),
                FULL_END,
            ),
        ):
            period = _slice(satellite, start=start, end=end)
            days = sum(1 for d in era_dates if start.date() <= d < end.date())
            diagnostic_windows[label] = _feature_payload(
                period,
                context_map=context_map,
                trading_days=days,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "satellite": _stats(satellite, era_days),
            "ict_context_coverage": {
                "trades": len(satellite),
                "context_rows": len(context_map),
                "coverage": 0.0 if not satellite else len(context_map) / len(satellite),
            },
            "full_period_features": _feature_payload(
                satellite,
                context_map=context_map,
                trading_days=era_days,
            ),
            "annual": annual,
            "diagnostic_windows": diagnostic_windows,
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
            "base_route": FROZEN_ROUTE,
            "required_costs": list(REQUIRED_COSTS),
            "canonical_ict_contract": "ICT_XAU_M15_EXECUTION_CONTEXT_V1",
            "canonical_ict_parameters_changed": False,
            "v47_family_gate_changed": False,
            "features_reported": list(BOOLEAN_FEATURES),
            "confluence_buckets": ["0", "1", "2", "3_PLUS", "UNAVAILABLE"],
            "trade_filter_applied": False,
            "feature_selected_as_winner": False,
            "weak_2022_2024_window_is_diagnostic_known_after_v59": True,
            "recent_2025_2026_window_is_diagnostic": True,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V66 is attribution only. It asks whether the unchanged canonical ICT context "
            "describes the already-frozen V47 satellite differently in the known weak "
            "2022-2024 window versus 2025-2026 YTD. It does not suppress or add trades."
        ),
    }
