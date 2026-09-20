from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, time, timezone
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_causal_regime_edge_gate_v47 import (
    FAMILY_MAP,
    gate_family_causally,
    _family_streams,
    _route_family_candidates,
)
from .research_xau_era_robustness_v31 import _dedupe_with_classic, _simulate_d1_classic
from .research_xau_hierarchical_regime_router_v35 import (
    _max_losing_streak,
    _period,
    build_h1_context,
)
from .research_xau_multihorizon_100usd_v20 import (
    _daily_frame,
    _limit_concurrency,
    _trading_dates,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts
from .research_xau_secular_regime_router_v46 import build_secular_d1

RESEARCH_VERSION = "XAU_CHANGEPOINT_RESET_ROUTER_V87"
ARTIFACT_CONTRACT = "XAU_CHANGEPOINT_RESET_ROUTER_V87_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
PROMOTION_ELIGIBLE = False
DIAGNOSTIC_ONLY = True

# Predeclared before historical outcome inspection.
BASELINE_D1_DAYS = 252
ROBUST_Z_THRESHOLD = 3.0
MIN_SHOCK_FEATURES = 2
CONFIRM_CONSECUTIVE_DAYS = 3
MIN_CHANGE_SPACING_DAYS = 20

# Frozen from V40/V47: no post-hoc retuning.
LOOKBACK_TRADING_DAYS = 126
MIN_COMPLETED_TRADES = 30
MIN_TRAILING_PF = 1.10
MIN_TRAILING_EXPECTANCY_R = 0.05

ROUTE_ID = "SECULAR_BULL_REACCEL_LONG_COST10"
FEATURES = (
    "trend60_atr",
    "ema200_distance_atr",
    "atr14_pct",
    "efficiency20",
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
    }


def build_regime_feature_frame(rows: Sequence[Bar]) -> pd.DataFrame:
    d1 = _daily_frame(rows).copy().sort_values("time").reset_index(drop=True)
    close = d1["close"].astype(float)
    atr = d1["atr14"].astype(float)
    d1["trend60_atr"] = (close - close.shift(60)) / atr
    d1["ema200_distance_atr"] = (close - d1["ema200"].astype(float)) / atr
    d1["atr14_pct"] = atr / close
    path = close.diff().abs().rolling(20, min_periods=20).sum()
    d1["efficiency20"] = (close - close.shift(20)).abs() / path
    return d1


def _robust_z(value: float, history: np.ndarray) -> float | None:
    x = history[np.isfinite(history)]
    if len(x) < max(40, BASELINE_D1_DAYS // 2):
        return None
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    if not np.isfinite(mad) or mad <= 1e-12:
        return None
    # 1.4826 converts MAD to a normal-consistent sigma estimate.
    return (float(value) - med) / (1.4826 * mad)


def detect_change_points(frame: pd.DataFrame) -> tuple[dict[str, Any], ...]:
    x = frame.copy().sort_values("time").reset_index(drop=True)
    shocks: list[dict[str, Any]] = []
    for i in range(len(x)):
        if i < BASELINE_D1_DAYS:
            shocks.append({"shock": False, "count": 0, "z": {}})
            continue
        zmap: dict[str, float | None] = {}
        count = 0
        for feature in FEATURES:
            value = float(x.loc[i, feature]) if pd.notna(x.loc[i, feature]) else float("nan")
            hist = x.loc[max(0, i - BASELINE_D1_DAYS): i - 1, feature].to_numpy(dtype=float)
            z = _robust_z(value, hist)
            zmap[feature] = z
            if z is not None and abs(z) >= ROBUST_Z_THRESHOLD:
                count += 1
        shocks.append({"shock": count >= MIN_SHOCK_FEATURES, "count": count, "z": zmap})

    out: list[dict[str, Any]] = []
    run = 0
    last_effective_i = -10_000
    armed = True
    for i, state in enumerate(shocks):
        if not state["shock"]:
            # A detected regime shift must return to a non-shock state before
            # another shift can be armed. This prevents one persistent level
            # shift from generating repeated resets every spacing interval.
            run = 0
            armed = True
            continue
        if not armed:
            continue
        run += 1
        if run < CONFIRM_CONSECUTIVE_DAYS:
            continue
        confirm_i = i
        effective_i = i + 1
        if effective_i >= len(x):
            continue
        if effective_i - last_effective_i < MIN_CHANGE_SPACING_DAYS:
            continue
        confirm_at = ensure_utc(x.loc[confirm_i, "time"])
        effective_at = ensure_utc(x.loc[effective_i, "time"])
        out.append(
            {
                "confirm_at": confirm_at.isoformat(),
                "effective_at": effective_at.isoformat(),
                "effective_index": int(effective_i),
                "shock_feature_count": int(state["count"]),
                "z": state["z"],
            }
        )
        last_effective_i = effective_i
        armed = False
        run = 0
    return tuple(out)


def _trailing_health(values: Sequence[TournamentTrade]) -> dict[str, Any]:
    trades = tuple(values)
    if not trades:
        return {
            "completed_trades": 0,
            "profit_factor": None,
            "expectancy_r": None,
            "net_r": 0.0,
            "active": False,
        }
    net = [float(x.net_r) for x in trades]
    gp = sum(x for x in net if x > 0.0)
    gl = -sum(x for x in net if x < 0.0)
    pf = float("inf") if gl <= 0.0 and gp > 0.0 else (None if gl <= 0.0 else gp / gl)
    expectancy = sum(net) / float(len(net))
    active = (
        len(net) >= MIN_COMPLETED_TRADES
        and pf is not None
        and pf >= MIN_TRAILING_PF
        and expectancy >= MIN_TRAILING_EXPECTANCY_R
    )
    return {
        "completed_trades": len(net),
        "profit_factor": pf,
        "expectancy_r": expectancy,
        "net_r": sum(net),
        "active": bool(active),
    }


def _date_cutoff(signal_at, trading_dates: Sequence[Any]):
    signal_date = ensure_utc(signal_at).date()
    dates = tuple(trading_dates)
    pos = bisect_left(dates, signal_date)
    if not dates or pos <= LOOKBACK_TRADING_DAYS:
        return dates[0] if dates else signal_date
    return dates[pos - LOOKBACK_TRADING_DAYS]


def gate_family_with_changepoint_reset(
    trades: Sequence[TournamentTrade],
    *,
    trading_dates: Sequence[Any],
    change_points: Sequence[Mapping[str, Any]],
) -> tuple[tuple[TournamentTrade, ...], dict[str, Any]]:
    ordered_signal = tuple(sorted(trades, key=lambda t: ensure_utc(t.signal_at)))
    ordered_exit = tuple(sorted(trades, key=lambda t: ensure_utc(t.exit_at)))
    exit_times = tuple(ensure_utc(t.exit_at) for t in ordered_exit)
    cp_times = tuple(
        ensure_utc(pd.Timestamp(x["effective_at"]).to_pydatetime())
        for x in change_points
    )

    kept: list[TournamentTrade] = []
    active_checks = 0
    reset_checks = 0
    first_active_by_epoch: dict[str, str] = {}
    last_health: dict[str, Any] | None = None

    first_date = trading_dates[0] if trading_dates else ensure_utc(ordered_signal[0].signal_at).date() if ordered_signal else datetime.now(timezone.utc).date()
    first_epoch = datetime.combine(first_date, time.min, tzinfo=timezone.utc)

    for trade in ordered_signal:
        signal_at = ensure_utc(trade.signal_at)
        cp_pos = bisect_right(cp_times, signal_at)
        epoch_start = first_epoch if cp_pos == 0 else cp_times[cp_pos - 1]

        completed_end = bisect_left(exit_times, signal_at)
        rolling_start_date = _date_cutoff(signal_at, trading_dates)
        rolling_start = datetime.combine(rolling_start_date, time.min, tzinfo=timezone.utc)
        history_start = max(epoch_start, rolling_start)
        completed_start = bisect_left(exit_times, history_start, hi=completed_end)
        trailing = ordered_exit[completed_start:completed_end]
        health = _trailing_health(trailing)
        last_health = health

        if health["active"]:
            active_checks += 1
            key = epoch_start.isoformat()
            if key not in first_active_by_epoch:
                first_active_by_epoch[key] = signal_at.isoformat()
            kept.append(trade)
        else:
            reset_checks += 1

    total = active_checks + reset_checks
    return tuple(kept), {
        "candidate_trades": len(ordered_signal),
        "kept_trades": len(kept),
        "suppressed_trades": len(ordered_signal) - len(kept),
        "activation_fraction": 0.0 if total == 0 else active_checks / float(total),
        "first_active_by_epoch": first_active_by_epoch,
        "last_health": last_health,
        "change_points_seen": len(change_points),
    }


def evaluate_v87(
    bars: Sequence[Bar],
    *,
    evaluation_start,
    evaluation_end,
    pip_size: float,
    cost_scenarios: Mapping[str, M15ResearchCosts],
    era_windows: Mapping[str, tuple[Any, Any]],
) -> dict[str, Any]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if not rows:
        raise ValueError("V87_EMPTY_HISTORY")
    start = ensure_utc(evaluation_start)
    end = ensure_utc(evaluation_end)
    if ensure_utc(rows[0].timestamp) >= start:
        raise ValueError("V87_WARMUP_REQUIRED")

    feature_frame = build_regime_feature_frame(rows)
    change_points = detect_change_points(feature_frame)
    d1_context = build_secular_d1(rows)
    h1_context = build_h1_context(rows)
    full_dates = _trading_dates(rows, start=ensure_utc(rows[0].timestamp), end=end)

    scenario_results: dict[str, Any] = {}
    for cost_id, costs in cost_scenarios.items():
        classic_all = _simulate_d1_classic(rows, costs=costs, pip_size=pip_size)
        annotated_by_family = _family_streams(
            rows,
            costs=costs,
            pip_size=pip_size,
            d1_context=d1_context,
            h1_context=h1_context,
        )

        v47_gated_all: dict[str, tuple[TournamentTrade, ...]] = {}
        reset_gated_all: dict[str, tuple[TournamentTrade, ...]] = {}
        gates: dict[str, Any] = {}

        for family in FAMILY_MAP:
            candidate = _route_family_candidates(annotated_by_family[family], route=ROUTE_ID)
            v47_gated, v47_gate = gate_family_causally(candidate, trading_dates=full_dates)
            reset_gated, reset_gate = gate_family_with_changepoint_reset(
                candidate,
                trading_dates=full_dates,
                change_points=change_points,
            )
            v47_gated_all[family] = v47_gated
            reset_gated_all[family] = reset_gated
            gates[family] = {
                "candidate_metrics": _metrics(candidate),
                "frozen_v47_gate": v47_gate,
                "changepoint_reset_gate": reset_gate,
            }

        def portfolio(gated: Mapping[str, Sequence[TournamentTrade]], a, b):
            core = _period(classic_all, start=a, end=b)
            sat = tuple(
                t
                for family in FAMILY_MAP
                for t in _period(gated[family], start=a, end=b)
            )
            return core, sat, _limit_concurrency(_dedupe_with_classic((*core, *sat)))

        all_core, all_v47_sat, all_v47_port = portfolio(v47_gated_all, start, end)
        _, all_reset_sat, all_reset_port = portfolio(reset_gated_all, start, end)

        era_payload: dict[str, Any] = {}
        for era_id, (era_start, era_end) in era_windows.items():
            a = ensure_utc(era_start)
            b = ensure_utc(era_end)
            days = len(_trading_dates(rows, start=a, end=b))
            core, v47_sat, v47_port = portfolio(v47_gated_all, a, b)
            _, reset_sat, reset_port = portfolio(reset_gated_all, a, b)
            era_payload[era_id] = {
                "core_d1": _stats(core, days),
                "frozen_v47_satellite": _stats(v47_sat, days),
                "frozen_v47_portfolio": _stats(v47_port, days),
                "reset_satellite": _stats(reset_sat, days),
                "reset_portfolio": _stats(reset_port, days),
            }

        full_days = len(_trading_dates(rows, start=start, end=end))
        scenario_results[cost_id] = {
            "full_period": {
                "core_d1": _stats(all_core, full_days),
                "frozen_v47_satellite": _stats(all_v47_sat, full_days),
                "frozen_v47_portfolio": _stats(all_v47_port, full_days),
                "reset_satellite": _stats(all_reset_sat, full_days),
                "reset_portfolio": _stats(all_reset_port, full_days),
            },
            "eras": era_payload,
            "gates": gates,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_eligible": PROMOTION_ELIGIBLE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "evaluation_start": start.isoformat(),
        "evaluation_end_exclusive": end.isoformat(),
        "change_points": list(change_points),
        "preregistered_contract": {
            "route": ROUTE_ID,
            "families": list(FAMILY_MAP),
            "market_features": list(FEATURES),
            "baseline_d1_days": BASELINE_D1_DAYS,
            "robust_z_threshold": ROBUST_Z_THRESHOLD,
            "minimum_simultaneous_shock_features": MIN_SHOCK_FEATURES,
            "confirmation_consecutive_completed_d1_days": CONFIRM_CONSECUTIVE_DAYS,
            "minimum_change_spacing_trading_days": MIN_CHANGE_SPACING_DAYS,
            "detector_rearms_only_after_nonshock_state": True,
            "change_effective_next_completed_d1_bar": True,
            "health_lookback_trading_days": LOOKBACK_TRADING_DAYS,
            "health_min_completed_trades": MIN_COMPLETED_TRADES,
            "health_min_pf": MIN_TRAILING_PF,
            "health_min_expectancy_r": MIN_TRAILING_EXPECTANCY_R,
            "health_thresholds_identical_to_v40_v47": True,
            "reset_discards_pre_change_strategy_outcomes": True,
            "suppressed_candidates_remain_shadow_tracked": True,
            "year_or_era_feature_used_for_routing": False,
            "selection_uses_future_outcomes": False,
            "threshold_grid_search": False,
            "execution_authority": False,
        },
        "scenario_results": scenario_results,
        "note": (
            "V87 tests whether a market-only structural change detector can reduce V40/V47 lag. "
            "A confirmed change point resets satellite health to cold-start OFF; each frozen V47 "
            "L12/L20 stream must re-qualify using only completed post-change outcomes. Era labels "
            "are evaluation-only and never enter routing decisions."
        ),
    }
