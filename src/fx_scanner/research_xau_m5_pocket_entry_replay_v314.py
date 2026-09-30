from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timedelta
from math import inf, isfinite
from statistics import median
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_h1_m5_reconfirmation_v313 import (
    _dt,
    _evaluate_policy,
)
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_supply_demand_reaction_v183 import (
    ZoneDestination,
    wilson_lower_bound,
)
from .research_xau_v229_historical_v242 import (
    BASE_SLIPPAGE_PIPS,
    BASE_SPREAD_PIPS,
    COMMISSION_PIPS_ROUND_TRIP,
    MIN_TERMINAL_RR,
    PIP_SIZE,
)
from .research_xau_zone_transition_ledger_v310 import build_transition_ledger

RESEARCH_VERSION = "XAU_M5_POCKET_ENTRY_REPLAY_V314"
ARTIFACT_CONTRACT = "XAU_M5_POCKET_ENTRY_REPLAY_V314_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

ENTRY_MODES = (
    "MARKET_CONFIRM",
    "POCKET_PROXIMAL_LIMIT",
    "POCKET_MID_LIMIT",
    "POCKET_DEEP_LIMIT",
)
STOP_MODES = (
    "POCKET_DISTAL_0P10_ATR",
    "H1_DISTAL_0P10_ATR",
)
TARGET_ATR_MULTIPLES = (0.50, 0.75, 1.00)

LIMIT_FILL_WINDOW_MINUTES = 120
MAX_HOLD_MINUTES = 480
STOP_BUFFER_ATR = 0.10
MAX_ADVERSE_PRECISE_USD = 5.0
DEVELOPMENT_FRACTION = 0.60
PURGE_HOURS = 24

MIN_DEVELOPMENT_FILLS = 30
MIN_HOLDOUT_FILLS = 30
MIN_HOLDOUT_FILL_RATE = 0.25
MIN_HOLDOUT_TP_RATE = 0.55
MIN_HOLDOUT_TP_WILSON = 0.45
MIN_HOLDOUT_PROFIT_FACTOR = 1.30
MIN_HOLDOUT_AVG_NET_R = 0.15
MIN_HOLDOUT_PRECISE_TP_RATE = 0.50

SPREAD_USD = BASE_SPREAD_PIPS * PIP_SIZE
SLIPPAGE_USD = BASE_SLIPPAGE_PIPS * PIP_SIZE
COMMISSION_USD = COMMISSION_PIPS_ROUND_TRIP * PIP_SIZE


def _times(rows: Sequence[Bar]) -> tuple[datetime, ...]:
    return tuple(ensure_utc(row.timestamp) for row in rows)


def _raw_entry(
    *,
    entry_mode: str,
    direction: str,
    pocket: dict[str, Any],
) -> float | None:
    low = pocket.get("low")
    high = pocket.get("high")
    if low is None or high is None:
        return None
    low = float(low)
    high = float(high)
    if not isfinite(low) or not isfinite(high) or high <= low:
        return None
    if entry_mode == "POCKET_PROXIMAL_LIMIT":
        return high if direction == "LONG" else low
    if entry_mode == "POCKET_MID_LIMIT":
        return (low + high) / 2.0
    if entry_mode == "POCKET_DEEP_LIMIT":
        return low if direction == "LONG" else high
    return None


def _raw_stop(
    *,
    stop_mode: str,
    direction: str,
    pocket: dict[str, Any],
    zone: ZoneDestination,
) -> float | None:
    atr = float(zone.atr_points)
    buffer = STOP_BUFFER_ATR * atr
    if stop_mode == "POCKET_DISTAL_0P10_ATR":
        low = pocket.get("low")
        high = pocket.get("high")
        if low is None or high is None:
            return None
        return (
            float(low) - buffer
            if direction == "LONG"
            else float(high) + buffer
        )
    if stop_mode == "H1_DISTAL_0P10_ATR":
        return (
            float(zone.low) - buffer
            if direction == "LONG"
            else float(zone.high) + buffer
        )
    return None


def _market_fill(
    *,
    rows: Sequence[Bar],
    times: Sequence[datetime],
    confirmation_at: datetime,
    direction: str,
) -> tuple[int, float] | None:
    index = bisect_left(times, ensure_utc(confirmation_at))
    if index >= len(rows) or times[index] != ensure_utc(confirmation_at):
        return None
    sign = 1 if direction == "LONG" else -1
    half = SPREAD_USD / 2.0
    fill = float(rows[index].open) + sign * (half + SLIPPAGE_USD)
    return index, fill


def _limit_fill(
    *,
    rows: Sequence[Bar],
    times: Sequence[datetime],
    confirmation_at: datetime,
    direction: str,
    raw_entry: float,
    stop: float,
) -> tuple[int, float, bool] | None:
    start = bisect_left(times, ensure_utc(confirmation_at))
    deadline = ensure_utc(confirmation_at) + timedelta(
        minutes=LIMIT_FILL_WINDOW_MINUTES
    )
    sign = 1 if direction == "LONG" else -1
    half = SPREAD_USD / 2.0
    entry_quote = raw_entry + sign * half

    for index in range(start, len(rows)):
        at = times[index]
        if at >= deadline:
            break
        row = rows[index]
        low_quote = float(row.low) - half
        high_quote = float(row.high) + half
        stop_crossed = low_quote <= stop if direction == "LONG" else high_quote >= stop
        touched = (
            float(row.low) <= raw_entry
            if direction == "LONG"
            else float(row.high) >= raw_entry
        )
        if stop_crossed and not touched:
            return None
        if touched:
            # If stop and entry are both inside the fill candle, replay remains
            # conservative: the setup is filled and STOP_FIRST applies.
            return index, entry_quote, bool(stop_crossed)
    return None


def _replay(
    *,
    rows: Sequence[Bar],
    times: Sequence[datetime],
    zone: ZoneDestination,
    confirmation_at: datetime,
    pocket: dict[str, Any],
    entry_mode: str,
    stop_mode: str,
    target_atr: float,
) -> dict[str, Any]:
    direction = str(zone.direction).upper()
    if direction not in {"LONG", "SHORT"}:
        return {"state": "INVALID_DIRECTION", "filled": False}
    sign = 1 if direction == "LONG" else -1
    stop = _raw_stop(
        stop_mode=stop_mode,
        direction=direction,
        pocket=pocket,
        zone=zone,
    )
    if stop is None or not isfinite(stop):
        return {"state": "INVALID_STOP_GEOMETRY", "filled": False}

    same_bar_stop = False
    if entry_mode == "MARKET_CONFIRM":
        market = _market_fill(
            rows=rows,
            times=times,
            confirmation_at=confirmation_at,
            direction=direction,
        )
        if market is None:
            return {"state": "NO_CONFIRMATION_OPEN", "filled": False}
        fill_index, fill = market
    else:
        raw_entry = _raw_entry(
            entry_mode=entry_mode,
            direction=direction,
            pocket=pocket,
        )
        if raw_entry is None:
            return {"state": "INVALID_ENTRY_GEOMETRY", "filled": False}
        limit = _limit_fill(
            rows=rows,
            times=times,
            confirmation_at=confirmation_at,
            direction=direction,
            raw_entry=raw_entry,
            stop=stop,
        )
        if limit is None:
            return {"state": "MISSED_OR_INVALIDATED_BEFORE_FILL", "filled": False}
        fill_index, fill, same_bar_stop = limit

    risk = sign * (fill - stop)
    target_distance = float(target_atr) * float(zone.atr_points)
    target = fill + sign * target_distance
    reward = sign * (target - fill)
    if not all(isfinite(x) for x in (fill, stop, target, risk, reward)):
        return {"state": "NONFINITE_GEOMETRY", "filled": False}
    if risk <= 0:
        return {"state": "STOP_WRONG_SIDE", "filled": False}
    rr = reward / risk
    if rr < MIN_TERMINAL_RR:
        return {
            "state": "RR_BELOW_1P5",
            "filled": False,
            "risk_usd": risk,
            "reward_usd": reward,
            "rr": rr,
        }

    fill_at = times[fill_index]
    half = SPREAD_USD / 2.0
    max_adverse = 0.0
    deadline = fill_at + timedelta(minutes=MAX_HOLD_MINUTES)
    last_index = bisect_left(times, deadline)
    state = None
    exit_price = None
    exit_at = None

    for index in range(fill_index, min(last_index, len(rows))):
        row = rows[index]
        low_quote = float(row.low) - half
        high_quote = float(row.high) + half
        adverse = (
            max(0.0, fill - low_quote)
            if direction == "LONG"
            else max(0.0, high_quote - fill)
        )
        max_adverse = max(max_adverse, adverse)
        stop_hit = (
            low_quote <= stop
            if direction == "LONG"
            else high_quote >= stop
        )
        target_hit = (
            high_quote >= target
            if direction == "LONG"
            else low_quote <= target
        )

        if index == fill_index and same_bar_stop:
            stop_hit = True
        # STOP_FIRST. Target is not credited on the fill candle.
        if stop_hit:
            state = "STOP"
            exit_price = (
                min(stop, float(row.open) - half) - SLIPPAGE_USD
                if direction == "LONG"
                else max(stop, float(row.open) + half) + SLIPPAGE_USD
            )
            exit_at = times[index] + timedelta(minutes=5)
            break
        if index > fill_index and target_hit:
            state = "TP"
            exit_price = target
            exit_at = times[index] + timedelta(minutes=5)
            break

    if state is None:
        if last_index >= len(rows):
            return {
                "state": "CENSORED",
                "filled": True,
                "fill_at": fill_at.isoformat(),
                "fill_price": fill,
            }
        row = rows[last_index]
        quote = (
            float(row.open) - half
            if direction == "LONG"
            else float(row.open) + half
        )
        exit_price = (
            quote - SLIPPAGE_USD
            if direction == "LONG"
            else quote + SLIPPAGE_USD
        )
        exit_at = times[last_index]
        state = "TIME_EXIT"

    gross = sign * (float(exit_price) - fill)
    net_r = (gross - COMMISSION_USD) / risk
    precise_tp = bool(state == "TP" and max_adverse <= MAX_ADVERSE_PRECISE_USD)
    return {
        "state": state,
        "filled": True,
        "entry_mode": entry_mode,
        "stop_mode": stop_mode,
        "target_atr": float(target_atr),
        "fill_at": fill_at.isoformat(),
        "fill_price": fill,
        "stop": stop,
        "target": target,
        "risk_usd": risk,
        "reward_usd": reward,
        "rr": rr,
        "exit_at": exit_at.isoformat(),
        "exit_price": float(exit_price),
        "net_r": net_r,
        "max_adverse_usd": max_adverse,
        "precision_5_and_tp": precise_tp,
        "minutes_confirmation_to_fill": (
            fill_at - ensure_utc(confirmation_at)
        ).total_seconds() / 60.0,
        "holding_minutes": (
            ensure_utc(exit_at) - fill_at
        ).total_seconds() / 60.0,
    }


def _confirmed_opportunities(
    m15_rows: Sequence[Bar],
    m5_rows: Sequence[Bar],
) -> tuple[tuple[dict[str, Any], ...], dict[str, ZoneDestination]]:
    destinations, episodes, _ = build_transition_ledger(m15_rows)
    zone_by_id = {zone.zone_id: zone for zone in destinations}
    rows = _evaluate_policy(
        policy="ALL_H1_MICRO_REQUIRED",
        m15_rows=m15_rows,
        destinations=destinations,
        episodes=episodes,
        m5_rows=m5_rows,
    )
    confirmed = tuple(
        row
        for row in rows
        if dict(row.get("micro") or {}).get("confirmed")
        and dict(row.get("micro") or {}).get("confirmation_at")
        and dict(row.get("micro") or {}).get("refined_entry_pocket")
    )
    return confirmed, zone_by_id


def _split(
    rows: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(
        rows,
        key=lambda row: _dt(dict(row.get("micro") or {})["confirmation_at"]),
    )
    if len(ordered) < 20:
        return [], []
    split_index = max(
        1,
        min(len(ordered) - 1, int(len(ordered) * DEVELOPMENT_FRACTION)),
    )
    split_at = _dt(dict(ordered[split_index].get("micro") or {})["confirmation_at"])
    purge = timedelta(hours=PURGE_HOURS)
    development = [
        row
        for row in ordered
        if _dt(dict(row.get("micro") or {})["confirmation_at"]) < split_at - purge
    ]
    holdout = [
        row
        for row in ordered
        if _dt(dict(row.get("micro") or {})["confirmation_at"]) >= split_at
    ]
    return development, holdout


def _combo_key(entry_mode: str, stop_mode: str, target_atr: float) -> str:
    return f"{entry_mode}|{stop_mode}|T{target_atr:.2f}ATR"


def _summary(
    results: Sequence[dict[str, Any]],
    *,
    opportunities: int,
) -> dict[str, Any]:
    sample = list(results)
    fills = [row for row in sample if row.get("filled")]
    resolved = [
        row for row in fills if row.get("state") in {"TP", "STOP", "TIME_EXIT"}
    ]
    tps = [row for row in resolved if row.get("state") == "TP"]
    stops = [row for row in resolved if row.get("state") == "STOP"]
    time_exits = [row for row in resolved if row.get("state") == "TIME_EXIT"]
    positive = [float(row["net_r"]) for row in resolved if float(row.get("net_r") or 0.0) > 0]
    negative = [float(row["net_r"]) for row in resolved if float(row.get("net_r") or 0.0) < 0]
    precise = [row for row in resolved if row.get("precision_5_and_tp")]
    net = [float(row["net_r"]) for row in resolved]
    fill_delays = [
        float(row["minutes_confirmation_to_fill"])
        for row in fills
        if row.get("minutes_confirmation_to_fill") is not None
    ]
    adverse = [
        float(row["max_adverse_usd"])
        for row in resolved
        if row.get("max_adverse_usd") is not None
    ]
    tp_rate = len(tps) / len(resolved) if resolved else None
    return {
        "opportunities": opportunities,
        "fills": len(fills),
        "fill_rate": len(fills) / opportunities if opportunities else None,
        "resolved": len(resolved),
        "tp": len(tps),
        "stop": len(stops),
        "time_exit": len(time_exits),
        "tp_rate": tp_rate,
        "tp_wilson_lower_95": (
            wilson_lower_bound(len(tps), len(resolved))
            if resolved else None
        ),
        "avg_net_r": sum(net) / len(net) if net else None,
        "median_net_r": median(net) if net else None,
        "profit_factor": (
            sum(positive) / abs(sum(negative))
            if negative
            else None
        ),
        "profit_factor_unbounded": bool(positive and not negative),
        "precision_5_and_tp": len(precise),
        "precision_5_and_tp_rate": (
            len(precise) / len(resolved) if resolved else None
        ),
        "median_max_adverse_usd": median(adverse) if adverse else None,
        "median_minutes_confirmation_to_fill": (
            median(fill_delays) if fill_delays else None
        ),
    }


def _evaluate_grid(
    opportunities: Sequence[dict[str, Any]],
    *,
    zone_by_id: dict[str, ZoneDestination],
    m5_rows: Sequence[Bar],
) -> dict[str, Any]:
    times = _times(m5_rows)
    output: dict[str, Any] = {}
    for entry_mode in ENTRY_MODES:
        for stop_mode in STOP_MODES:
            for target_atr in TARGET_ATR_MULTIPLES:
                key = _combo_key(entry_mode, stop_mode, target_atr)
                results: list[dict[str, Any]] = []
                for opportunity in opportunities:
                    zone = zone_by_id.get(str(opportunity["selected_zone_id"]))
                    if zone is None:
                        continue
                    micro = dict(opportunity.get("micro") or {})
                    confirmation_at = _dt(micro["confirmation_at"])
                    pocket = dict(micro.get("refined_entry_pocket") or {})
                    replay = _replay(
                        rows=m5_rows,
                        times=times,
                        zone=zone,
                        confirmation_at=confirmation_at,
                        pocket=pocket,
                        entry_mode=entry_mode,
                        stop_mode=stop_mode,
                        target_atr=target_atr,
                    )
                    results.append(
                        {
                            "selected_zone_id": zone.zone_id,
                            "confirmation_at": confirmation_at.isoformat(),
                            **replay,
                        }
                    )
                output[key] = {
                    "entry_mode": entry_mode,
                    "stop_mode": stop_mode,
                    "target_atr": target_atr,
                    "summary": _summary(
                        results,
                        opportunities=len(opportunities),
                    ),
                    "results": results,
                }
    return output


def _select_development_combo(grid: dict[str, Any]) -> str | None:
    eligible: list[tuple[Any, ...]] = []
    for key, row in grid.items():
        summary = dict(row.get("summary") or {})
        fills = int(summary.get("fills") or 0)
        if fills < MIN_DEVELOPMENT_FILLS:
            continue
        pf = summary.get("profit_factor")
        avg_r = summary.get("avg_net_r")
        fill_rate = summary.get("fill_rate")
        unbounded_pf = bool(summary.get("profit_factor_unbounded"))
        if (pf is None and not unbounded_pf) or avg_r is None or fill_rate is None:
            continue
        rank_pf = 1_000_000.0 if unbounded_pf else float(pf)
        eligible.append(
            (
                -rank_pf,
                -float(avg_r),
                -float(summary.get("precision_5_and_tp_rate") or 0.0),
                -float(fill_rate),
                key,
            )
        )
    if not eligible:
        return None
    eligible.sort()
    return str(eligible[0][-1])


def _holdout_gate(summary: dict[str, Any]) -> dict[str, Any]:
    fills = int(summary.get("fills") or 0)
    fill_rate = float(summary.get("fill_rate") or 0.0)
    tp_rate = float(summary.get("tp_rate") or 0.0)
    wilson = float(summary.get("tp_wilson_lower_95") or 0.0)
    pf = (
        1_000_000.0
        if bool(summary.get("profit_factor_unbounded"))
        else float(summary.get("profit_factor") or 0.0)
    )
    avg_r = float(summary.get("avg_net_r") or 0.0)
    precise = float(summary.get("precision_5_and_tp_rate") or 0.0)
    passed = bool(
        fills >= MIN_HOLDOUT_FILLS
        and fill_rate >= MIN_HOLDOUT_FILL_RATE
        and tp_rate >= MIN_HOLDOUT_TP_RATE
        and wilson >= MIN_HOLDOUT_TP_WILSON
        and pf >= MIN_HOLDOUT_PROFIT_FACTOR
        and avg_r >= MIN_HOLDOUT_AVG_NET_R
        and precise >= MIN_HOLDOUT_PRECISE_TP_RATE
    )
    return {
        "min_fills": MIN_HOLDOUT_FILLS,
        "min_fill_rate": MIN_HOLDOUT_FILL_RATE,
        "min_tp_rate": MIN_HOLDOUT_TP_RATE,
        "min_tp_wilson_lower_95": MIN_HOLDOUT_TP_WILSON,
        "min_profit_factor": MIN_HOLDOUT_PROFIT_FACTOR,
        "min_avg_net_r": MIN_HOLDOUT_AVG_NET_R,
        "min_precision_5_and_tp_rate": MIN_HOLDOUT_PRECISE_TP_RATE,
        "passed": passed,
    }


def evaluate_m5_pocket_entry_replay(
    m15_bars: Sequence[Bar],
    m5_bars: Sequence[Bar],
) -> dict[str, Any]:
    m15_rows = _validate_bars(m15_bars)
    m5_rows = tuple(sorted(m5_bars, key=lambda row: ensure_utc(row.timestamp)))
    confirmed, zone_by_id = _confirmed_opportunities(m15_rows, m5_rows)
    development, holdout = _split(confirmed)

    development_grid = _evaluate_grid(
        development,
        zone_by_id=zone_by_id,
        m5_rows=m5_rows,
    )
    selected_key = _select_development_combo(development_grid)

    holdout_grid = _evaluate_grid(
        holdout,
        zone_by_id=zone_by_id,
        m5_rows=m5_rows,
    )
    selected_holdout = (
        None if selected_key is None else holdout_grid.get(selected_key)
    )
    selected_summary = (
        {} if selected_holdout is None
        else dict(selected_holdout.get("summary") or {})
    )
    gate = _holdout_gate(selected_summary) if selected_holdout else {
        "passed": False,
        "reason": "NO_DEVELOPMENT_COMBO_SELECTED",
    }

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "closed_m15_bars": len(m15_rows),
        "closed_m5_bars": len(m5_rows),
        "confirmed_v313_opportunities": len(confirmed),
        "development_opportunities": len(development),
        "holdout_opportunities": len(holdout),
        "cost_contract": {
            "spread_usd": SPREAD_USD,
            "slippage_usd": SLIPPAGE_USD,
            "commission_usd_round_trip": COMMISSION_USD,
            "provenance": "V242_FIXED_PROXY_COSTS",
        },
        "grid_contract": {
            "entry_modes": list(ENTRY_MODES),
            "stop_modes": list(STOP_MODES),
            "target_atr_multiples": list(TARGET_ATR_MULTIPLES),
            "limit_fill_window_minutes": LIMIT_FILL_WINDOW_MINUTES,
            "max_hold_minutes": MAX_HOLD_MINUTES,
            "stop_buffer_atr": STOP_BUFFER_ATR,
            "min_terminal_rr": MIN_TERMINAL_RR,
            "stop_first": True,
            "no_target_credit_on_fill_candle": True,
        },
        "selection_contract": {
            "development_fraction": DEVELOPMENT_FRACTION,
            "purge_hours": PURGE_HOURS,
            "min_development_fills": MIN_DEVELOPMENT_FILLS,
            "ranking": "PROFIT_FACTOR_THEN_AVG_NET_R_THEN_PRECISION_THEN_FILL_RATE",
            "selected_key": selected_key,
        },
        "development_grid": development_grid,
        "selected_holdout": selected_holdout,
        "holdout_gate": gate,
        "decision": (
            "HOLDOUT_GATE_PASSED_FORWARD_DEMO_SHADOW_NEXT"
            if bool(gate.get("passed"))
            else "HOLDOUT_GATE_NOT_PASSED"
        ),
        "limitations": [
            "V314_REUSES_V313_RECENT_ERA_SAMPLE_AND_IS_NOT_INDEPENDENT_EXTERNAL_OOS",
            "HISTORICAL_SPREAD_IS_FIXED_PROXY_NOT_TICK_SPREAD",
            "M5_OHLC_CANNOT_PROVE_INTRABAR_EVENT_ORDER_STOP_FIRST_USED",
            "LIMIT_QUEUE_POSITION_AND_BROKER_LATENCY_NOT_MODELED",
            "NO_EXECUTION_OR_PROMOTION_AUTHORITY",
        ],
    }
