from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite, sqrt
from statistics import median
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .demo_xau_m15_ict_layer import (
    LIQUIDITY_SWEEP_LOOKBACK,
    evaluate_ict_execution_context,
)
from .models import Bar, ensure_utc
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

RESEARCH_VERSION = "XAU_V47_SWEEP_STRENGTH_V83"
ARTIFACT_CONTRACT = "XAU_V47_SWEEP_STRENGTH_V83_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")
CONTEXT_WINDOW_M15 = 700

RAW_FEATURES = (
    "age_m15_bars",
    "penetration_atr",
    "reclaim_atr",
    "body_atr",
    "close_location",
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
            ensure_utc(x.signal_at),
            str(x.strategy_id),
            ensure_utc(x.entry_at),
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


def _latest_sweep_geometry(
    rows: Sequence[Bar],
    trade: TournamentTrade,
) -> dict[str, Any] | None:
    signal_index = int(trade.signal_index)
    if signal_index < 0 or signal_index >= len(rows):
        return None
    start = max(0, signal_index - CONTEXT_WINDOW_M15 + 1)
    window = tuple(rows[start: signal_index + 1])
    if not window:
        return None

    direction = str(trade.direction).upper()
    as_of = ensure_utc(trade.signal_at) + timedelta(minutes=15)
    atr_value = float(trade.atr_at_signal)
    if direction not in {"LONG", "SHORT"} or not isfinite(atr_value) or atr_value <= 0.0:
        return None

    ict = evaluate_ict_execution_context(
        window,
        direction=direction,
        atr_value=atr_value,
        as_of=as_of,
    )
    if not ict.available:
        return None

    completed = tuple(
        row
        for row in sorted(window, key=lambda x: ensure_utc(x.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=15) <= as_of
    )
    if not completed:
        return None

    levels = (
        {
            "PDL": ict.previous_day_low,
            "ASIA_LOW": ict.asian_low,
            "LONDON_LOW": ict.london_low,
            "NEW_YORK_LOW": ict.new_york_low,
        }
        if direction == "LONG"
        else {
            "PDH": ict.previous_day_high,
            "ASIA_HIGH": ict.asian_high,
            "LONDON_HIGH": ict.london_high,
            "NEW_YORK_HIGH": ict.new_york_high,
        }
    )

    events: list[dict[str, Any]] = []
    begin = max(0, len(completed) - LIQUIDITY_SWEEP_LOOKBACK)
    for index in range(begin, len(completed)):
        bar = completed[index]
        candle_range = max(float(bar.high) - float(bar.low), 1e-12)
        body_atr = abs(float(bar.close) - float(bar.open)) / atr_value
        close_location = (
            (float(bar.close) - float(bar.low)) / candle_range
            if direction == "LONG"
            else (float(bar.high) - float(bar.close)) / candle_range
        )
        for source, raw_level in levels.items():
            if raw_level is None:
                continue
            level = float(raw_level)
            if direction == "LONG":
                swept = float(bar.low) < level and float(bar.close) > level
                penetration = (level - float(bar.low)) / atr_value
                reclaim = (float(bar.close) - level) / atr_value
            else:
                swept = float(bar.high) > level and float(bar.close) < level
                penetration = (float(bar.high) - level) / atr_value
                reclaim = (level - float(bar.close)) / atr_value
            if not swept:
                continue
            events.append(
                {
                    "source": str(source),
                    "sweep_at": ensure_utc(bar.timestamp),
                    "age_m15_bars": len(completed) - 1 - index,
                    "penetration_atr": float(penetration),
                    "reclaim_atr": float(reclaim),
                    "body_atr": float(body_atr),
                    "close_location": float(close_location),
                }
            )

    if not events:
        return None
    return max(
        events,
        key=lambda row: (
            ensure_utc(row["sweep_at"]),
            str(row["source"]),
        ),
    )


def _average_ranks(values: Sequence[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda x: (float(x[1]), int(x[0])))
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        value = float(indexed[i][1])
        while j < len(indexed) and float(indexed[j][1]) == value:
            j += 1
        average_rank = ((i + 1) + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = average_rank
        i = j
    return ranks


def _pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or len(x) < 5:
        return None
    mean_x = sum(float(v) for v in x) / len(x)
    mean_y = sum(float(v) for v in y) / len(y)
    dx = [float(v) - mean_x for v in x]
    dy = [float(v) - mean_y for v in y]
    denom = sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    if denom <= 0.0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denom


def _spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 5:
        return None
    return _pearson(_average_ranks(x), _average_ranks(y))


def _feature_summary(rows: Sequence[tuple[TournamentTrade, Mapping[str, Any]]], feature: str) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    winners: list[float] = []
    losers: list[float] = []
    for trade, ctx in rows:
        raw = ctx.get(feature)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not isfinite(value):
            continue
        net_r = float(trade.net_r)
        pairs.append((value, net_r))
        (winners if net_r > 0.0 else losers).append(value)

    xs = [row[0] for row in pairs]
    ys = [row[1] for row in pairs]

    def _mean(values: Sequence[float]) -> float | None:
        return None if not values else sum(values) / float(len(values))

    return {
        "n": len(pairs),
        "spearman_vs_net_r": _spearman(xs, ys),
        "winner_n": len(winners),
        "loser_n": len(losers),
        "winner_mean": _mean(winners),
        "loser_mean": _mean(losers),
        "winner_median": None if not winners else float(median(winners)),
        "loser_median": None if not losers else float(median(losers)),
    }


def _payload(
    trades: Sequence[TournamentTrade],
    *,
    geometry_map: Mapping[tuple[Any, ...], Mapping[str, Any] | None],
    trading_days: int,
) -> dict[str, Any]:
    sweep_rows: list[tuple[TournamentTrade, Mapping[str, Any]]] = []
    no_sweep: list[TournamentTrade] = []
    source_groups: dict[str, list[TournamentTrade]] = defaultdict(list)

    for trade in trades:
        ctx = geometry_map.get(_trade_key(trade))
        if not ctx:
            no_sweep.append(trade)
            continue
        sweep_rows.append((trade, ctx))
        source_groups[str(ctx["source"])].append(trade)

    sweep_trades = tuple(row[0] for row in sweep_rows)
    return {
        "all": _stats(tuple(trades), trading_days),
        "sweep": _stats(sweep_trades, trading_days),
        "non_sweep": _stats(tuple(no_sweep), trading_days),
        "raw_feature_relationships": {
            feature: _feature_summary(sweep_rows, feature)
            for feature in RAW_FEATURES
        },
        "sweep_sources": {
            source: _stats(tuple(values), trading_days)
            for source, values in sorted(source_groups.items())
        },
    }


def _trade_key(trade: TournamentTrade) -> tuple[Any, ...]:
    return (
        str(trade.strategy_id),
        ensure_utc(trade.signal_at),
        ensure_utc(trade.entry_at),
        str(trade.direction),
    )


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


def evaluate_v83(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V83_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V83_MISSING_REQUIRED_COSTS:{missing}")

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
        annotated = _family_streams(
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
                annotated[family],
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
        geometry_map = {
            _trade_key(trade): _latest_sweep_geometry(rows, trade)
            for trade in satellite
        }

        annual: dict[str, Any] = {}
        for year in range(FULL_START.year, FULL_END.year + 1):
            start = datetime(year, 1, 1, tzinfo=timezone.utc)
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            period = _slice(satellite, start=start, end=end)
            if not period:
                continue
            days = sum(1 for d in era_dates if start.date() <= d < end.date())
            annual[str(year)] = _payload(
                period,
                geometry_map=geometry_map,
                trading_days=days,
            )

        windows: dict[str, Any] = {}
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
            windows[label] = _payload(
                period,
                geometry_map=geometry_map,
                trading_days=days,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "satellite": _stats(satellite, era_days),
            "full_period": _payload(
                satellite,
                geometry_map=geometry_map,
                trading_days=era_days,
            ),
            "annual": annual,
            "diagnostic_windows": windows,
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
            "sweep_definition_identical_to_v69_v80_v82": True,
            "latest_sweep_lookback_m15": LIQUIDITY_SWEEP_LOOKBACK,
            "raw_features": list(RAW_FEATURES),
            "relationship_measure": "Spearman rank correlation with net-R plus winner/loser raw means and medians",
            "feature_thresholds_added": False,
            "feature_buckets_added": False,
            "score_added": False,
            "trade_filter_applied": False,
            "v69_forward_contract_changed": False,
            "v82_forward_telemetry_changed": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V83 is a monotonic mechanism audit of raw sweep strength fields already captured "
            "prospectively by V82. It adds no threshold, bucket, score, trade filter, or forward "
            "decision rule."
        ),
    }
