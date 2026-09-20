from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    _family_streams,
    _route_family_candidates,
    gate_family_causally,
)
from .research_xau_hierarchical_regime_router_v35 import (
    _Asof,
    _direction_metrics,
    _max_losing_streak,
    _period,
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import _trading_dates
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1
from .research_xau_v47_target_credibility_v74 import build_h1_noise_context

RESEARCH_VERSION = "XAU_V47_OPR_CONTEXT_V76"
ARTIFACT_CONTRACT = "XAU_V47_OPR_CONTEXT_V76_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

FULL_START = datetime(2012, 1, 1, tzinfo=timezone.utc)
FULL_END = datetime(2026, 9, 20, tzinfo=timezone.utc)
FROZEN_ROUTE = "SECULAR_BULL_REACCEL_LONG_COST10"
REQUIRED_COSTS = ("LOW_1700", "V24_STRESS_4675")

NY = ZoneInfo("America/New_York")
OPR_START = time(9, 30)
OPR_MINUTES = 15

POSITION_STATES = ("ABOVE", "INSIDE", "BELOW", "UNAVAILABLE")
OPR_ATR_BUCKETS = (
    "LE_0_25",
    "GT_0_25_LE_0_50",
    "GT_0_50",
    "UNAVAILABLE",
)


@dataclass(frozen=True, slots=True)
class OprDay:
    local_date: str
    source_bar_at: datetime
    available_at: datetime
    high: float
    low: float
    open: float
    close: float

    @property
    def range(self) -> float:
        return float(self.high) - float(self.low)


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
        key=lambda x: (ensure_utc(x.signal_at), str(x.strategy_id)),
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


def build_opr_days(rows: Sequence[Bar]) -> dict[str, OprDay]:
    output: dict[str, OprDay] = {}
    for bar in sorted(rows, key=lambda x: ensure_utc(x.timestamp)):
        stamp = ensure_utc(bar.timestamp)
        local = stamp.astimezone(NY)
        if local.weekday() >= 5:
            continue
        if local.time().replace(tzinfo=None) != OPR_START:
            continue
        key = local.date().isoformat()
        output[key] = OprDay(
            local_date=key,
            source_bar_at=stamp,
            available_at=stamp + timedelta(minutes=OPR_MINUTES),
            high=float(bar.high),
            low=float(bar.low),
            open=float(bar.open),
            close=float(bar.close),
        )
    return output


def _position(value: float, opr: OprDay) -> str:
    if value > float(opr.high):
        return "ABOVE"
    if value < float(opr.low):
        return "BELOW"
    return "INSIDE"


def _range_bucket(value: float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    if value <= 0.25:
        return "LE_0_25"
    if value <= 0.50:
        return "GT_0_25_LE_0_50"
    return "GT_0_50"


def _context_for_trade(
    trade: TournamentTrade,
    *,
    opr_days: Mapping[str, OprDay],
    bar_by_time: Mapping[datetime, Bar],
    h1_lookup: _Asof,
) -> dict[str, Any]:
    signal_at = ensure_utc(trade.signal_at)
    decision_time = signal_at + timedelta(minutes=15)
    local_date = signal_at.astimezone(NY).date().isoformat()
    opr = opr_days.get(local_date)
    if opr is None or decision_time < opr.available_at:
        return {
            "available": False,
            "local_date": local_date,
            "signal_close_position": "UNAVAILABLE",
            "entry_position": "UNAVAILABLE",
            "touch_or_cross_close_above": False,
            "opr_range_to_h1_atr": None,
            "opr_atr_bucket": "UNAVAILABLE",
        }

    signal_bar = bar_by_time.get(signal_at)
    if signal_bar is None:
        return {
            "available": False,
            "local_date": local_date,
            "signal_close_position": "UNAVAILABLE",
            "entry_position": "UNAVAILABLE",
            "touch_or_cross_close_above": False,
            "opr_range_to_h1_atr": None,
            "opr_atr_bucket": "UNAVAILABLE",
        }

    h1 = h1_lookup.row(signal_at)
    atr14 = None
    if h1 is not None:
        try:
            candidate = float(h1.get("atr14"))
            if np.isfinite(candidate) and candidate > 0.0:
                atr14 = candidate
        except (TypeError, ValueError):
            atr14 = None

    range_to_atr = (
        None
        if atr14 is None
        else float(opr.range) / float(atr14)
    )
    close_position = _position(float(signal_bar.close), opr)
    entry_position = _position(float(trade.entry_price), opr)
    touch_or_cross_close_above = bool(
        float(signal_bar.low) <= float(opr.high)
        and float(signal_bar.close) > float(opr.high)
    )

    return {
        "available": True,
        "local_date": local_date,
        "opr_source_bar_at": opr.source_bar_at.isoformat(),
        "opr_available_at": opr.available_at.isoformat(),
        "opr_high": float(opr.high),
        "opr_low": float(opr.low),
        "opr_range": float(opr.range),
        "signal_close_position": close_position,
        "entry_position": entry_position,
        "touch_or_cross_close_above": touch_or_cross_close_above,
        "opr_range_to_h1_atr": range_to_atr,
        "opr_atr_bucket": _range_bucket(range_to_atr),
    }


def _payload(
    trades: Sequence[TournamentTrade],
    *,
    opr_days: Mapping[str, OprDay],
    bar_by_time: Mapping[datetime, Bar],
    h1_lookup: _Asof,
    trading_days: int,
) -> dict[str, Any]:
    close_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    entry_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    range_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    retest_groups: dict[str, list[TournamentTrade]] = defaultdict(list)
    available = 0

    for trade in trades:
        ctx = _context_for_trade(
            trade,
            opr_days=opr_days,
            bar_by_time=bar_by_time,
            h1_lookup=h1_lookup,
        )
        close_state = str(ctx["signal_close_position"])
        entry_state = str(ctx["entry_position"])
        bucket = str(ctx["opr_atr_bucket"])
        close_groups[close_state].append(trade)
        entry_groups[entry_state].append(trade)
        range_groups[bucket].append(trade)
        retest_groups[
            "TRUE" if bool(ctx["touch_or_cross_close_above"]) else "FALSE"
        ].append(trade)
        if bool(ctx["available"]):
            available += 1

    return {
        "all": _stats(tuple(trades), trading_days),
        "coverage": {
            "trades": len(trades),
            "opr_available": available,
            "fraction": 0.0 if not trades else available / float(len(trades)),
        },
        "signal_close_position": {
            state: _stats(tuple(close_groups.get(state, ())), trading_days)
            for state in POSITION_STATES
        },
        "entry_position": {
            state: _stats(tuple(entry_groups.get(state, ())), trading_days)
            for state in POSITION_STATES
        },
        "touch_or_cross_close_above": {
            state: _stats(tuple(retest_groups.get(state, ())), trading_days)
            for state in ("TRUE", "FALSE")
        },
        "opr_range_to_h1_atr": {
            bucket: _stats(tuple(range_groups.get(bucket, ())), trading_days)
            for bucket in OPR_ATR_BUCKETS
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


def evaluate_v76(
    bars: Sequence[Bar],
    *,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V76_EMPTY_HISTORY")
    missing = [x for x in REQUIRED_COSTS if x not in cost_scenarios]
    if missing:
        raise ValueError(f"V76_MISSING_REQUIRED_COSTS:{missing}")

    opr_days = build_opr_days(rows)
    if not opr_days:
        raise ValueError("V76_OPR_EMPTY")
    bar_by_time = {ensure_utc(row.timestamp): row for row in rows}
    h1_noise = build_h1_noise_context(rows)
    h1_lookup = _Asof(h1_noise)

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
                opr_days=opr_days,
                bar_by_time=bar_by_time,
                h1_lookup=h1_lookup,
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
                opr_days=opr_days,
                bar_by_time=bar_by_time,
                h1_lookup=h1_lookup,
                trading_days=days,
            )

        scenarios[cost_id] = {
            "family_gates": family_gates,
            "satellite": _stats(satellite, era_days),
            "full_period": _payload(
                satellite,
                opr_days=opr_days,
                bar_by_time=bar_by_time,
                h1_lookup=h1_lookup,
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
        "opr_definition": {
            "timezone": "America/New_York",
            "start": "09:30",
            "duration_minutes": OPR_MINUTES,
            "available_after": "09:45 local New York",
            "source": "XAUUSD M15 bar",
        },
        "preregistered_contract": {
            "base_route": FROZEN_ROUTE,
            "required_costs": list(REQUIRED_COSTS),
            "opr_is_public_operationalization_not_proprietary_replication": True,
            "position_states": list(POSITION_STATES),
            "opr_range_h1_atr_buckets": list(OPR_ATR_BUCKETS),
            "touch_or_cross_close_above_definition": "signal M15 low <= OPR high AND signal M15 close > OPR high",
            "entry_changed": False,
            "stop_changed": False,
            "target_changed": False,
            "trade_filter_applied": False,
            "opr_state_selected_as_winner": False,
            "threshold_grid_search": False,
            "selection_uses_future_outcomes": False,
            "execution_authority": False,
        },
        "scenarios": scenarios,
        "note": (
            "V76 tests a transparent 15-minute New York opening-range context on frozen V47 XAU "
            "trades. It is not claimed to reproduce proprietary LST rules, and no OPR state "
            "filters or modifies any trade."
        ),
    }
