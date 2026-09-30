from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timedelta
from math import isfinite
from statistics import median
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_m5_pocket_entry_replay_v314 import (
    COMMISSION_USD,
    MAX_ADVERSE_PRECISE_USD,
    SPREAD_USD,
    SLIPPAGE_USD,
    _confirmed_opportunities,
    _limit_fill,
    _raw_entry,
    _raw_stop,
    _split,
    _times,
)
from .research_xau_supply_demand_reaction_v183 import (
    ZoneDestination,
    wilson_lower_bound,
)
from .research_xau_v229_historical_v242 import MIN_TERMINAL_RR
from .research_xau_zone_transition_ledger_v310 import _zone_gap, build_transition_ledger
from .research_xau_reusable_primary_reversal_v312 import _causal_active

RESEARCH_VERSION = "XAU_PRECISION_TP_LADDER_V315"
ARTIFACT_CONTRACT = "XAU_PRECISION_TP_LADDER_V315_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

# V314 development-selected entry/stop geometry. V315 freezes this geometry and
# changes only exit management.
ENTRY_MODE = "POCKET_PROXIMAL_LIMIT"
STOP_MODE = "POCKET_DISTAL_0P10_ATR"
LIMIT_FILL_WINDOW_MINUTES = 120
MAX_HOLD_MINUTES = 480

TP1_ATR_MULTIPLES = (0.25, 0.35, 0.50)
TP1_FRACTIONS = (0.25, 0.50, 0.75)
RUNNER_ATR_MULTIPLES = (0.75, 1.00)

DEVELOPMENT_FRACTION = 0.60
PURGE_HOURS = 24
MIN_DEVELOPMENT_FILLS = 30
MIN_DEVELOPMENT_TP1_RATE = 0.60
MIN_DEVELOPMENT_PROFIT_FACTOR = 1.10
MIN_DEVELOPMENT_AVG_NET_R = 0.0

MIN_HOLDOUT_FILLS = 30
MIN_HOLDOUT_FILL_RATE = 0.25
MIN_HOLDOUT_TP1_RATE = 0.65
MIN_HOLDOUT_TP1_WILSON = 0.55
MIN_HOLDOUT_PRECISION_TP1_RATE = 0.55
MIN_HOLDOUT_PROFIT_FACTOR = 1.30
MIN_HOLDOUT_AVG_NET_R = 0.15


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return ensure_utc(value)
    return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _nearest_active_opposite_h1(
    *,
    destinations: Sequence[ZoneDestination],
    direction: str,
    at: datetime,
    price: float,
) -> dict[str, Any] | None:
    opposite = "SHORT" if str(direction).upper() == "LONG" else "LONG"
    candidates: list[tuple[float, ZoneDestination]] = []
    for zone in destinations:
        if str(zone.direction).upper() != opposite:
            continue
        if str(zone.timeframe).upper() != "H1":
            continue
        if not _causal_active(zone, at):
            continue
        candidates.append((_zone_gap(float(price), zone), zone))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1].zone_id))
    gap, zone = candidates[0]
    return {
        "zone_id": zone.zone_id,
        "zone_class": zone.zone_class,
        "pattern": zone.pattern,
        "direction": zone.direction,
        "low": float(zone.low),
        "high": float(zone.high),
        "gap_usd": float(gap),
        "within_5_usd": bool(gap <= 5.0),
        "available_at": ensure_utc(zone.available_at).isoformat(),
    }


def _stop_exit_price(
    *,
    row: Bar,
    direction: str,
    stop: float,
) -> float:
    half = SPREAD_USD / 2.0
    if direction == "LONG":
        return min(float(stop), float(row.open) - half) - SLIPPAGE_USD
    return max(float(stop), float(row.open) + half) + SLIPPAGE_USD


def _time_exit_price(*, row: Bar, direction: str) -> float:
    half = SPREAD_USD / 2.0
    if direction == "LONG":
        return float(row.open) - half - SLIPPAGE_USD
    return float(row.open) + half + SLIPPAGE_USD


def _replay_ladder(
    *,
    rows: Sequence[Bar],
    times: Sequence[datetime],
    zone: ZoneDestination,
    confirmation_at: datetime,
    pocket: dict[str, Any],
    tp1_atr: float,
    tp1_fraction: float,
    runner_atr: float,
    destinations: Sequence[ZoneDestination],
) -> dict[str, Any]:
    direction = str(zone.direction).upper()
    if direction not in {"LONG", "SHORT"}:
        return {"state": "INVALID_DIRECTION", "filled": False}
    sign = 1 if direction == "LONG" else -1

    raw_entry = _raw_entry(
        entry_mode=ENTRY_MODE,
        direction=direction,
        pocket=pocket,
    )
    stop = _raw_stop(
        stop_mode=STOP_MODE,
        direction=direction,
        pocket=pocket,
        zone=zone,
    )
    if raw_entry is None or stop is None:
        return {"state": "INVALID_GEOMETRY", "filled": False}

    filled = _limit_fill(
        rows=rows,
        times=times,
        confirmation_at=confirmation_at,
        direction=direction,
        raw_entry=float(raw_entry),
        stop=float(stop),
    )
    if filled is None:
        return {"state": "MISSED_OR_INVALIDATED_BEFORE_FILL", "filled": False}
    fill_index, fill, same_bar_stop = filled

    risk = sign * (float(fill) - float(stop))
    atr = float(zone.atr_points)
    tp1 = float(fill) + sign * float(tp1_atr) * atr
    runner_target = float(fill) + sign * float(runner_atr) * atr
    runner_reward = sign * (runner_target - float(fill))
    terminal_rr = runner_reward / risk if risk > 0 else 0.0
    if (
        risk <= 0
        or runner_reward <= 0
        or float(runner_atr) <= float(tp1_atr)
        or terminal_rr < MIN_TERMINAL_RR
    ):
        return {
            "state": "TERMINAL_RR_BELOW_1P5",
            "filled": False,
            "risk_usd": risk,
            "terminal_rr": terminal_rr,
        }

    fill_at = ensure_utc(times[fill_index])
    deadline = fill_at + timedelta(minutes=MAX_HOLD_MINUTES)
    last_index = bisect_left(times, deadline)
    half = SPREAD_USD / 2.0
    remaining_fraction = 1.0 - float(tp1_fraction)
    max_adverse = 0.0
    tp1_hit = False
    tp1_at_known: datetime | None = None
    tp1_next_zone: dict[str, Any] | None = None
    runner_state = "NOT_ACTIVATED"
    full_exit_state = ""
    exit_at: datetime | None = None
    realized_price_pnl = 0.0
    final_exit_price: float | None = None

    for index in range(fill_index, min(last_index, len(rows))):
        row = rows[index]
        at = ensure_utc(times[index])
        low_quote = float(row.low) - half
        high_quote = float(row.high) + half
        adverse = (
            max(0.0, float(fill) - low_quote)
            if direction == "LONG"
            else max(0.0, high_quote - float(fill))
        )
        max_adverse = max(max_adverse, adverse)

        active_stop = float(fill) if tp1_hit else float(stop)
        stop_hit = (
            low_quote <= active_stop
            if direction == "LONG"
            else high_quote >= active_stop
        )
        tp1_reached = (
            high_quote >= tp1
            if direction == "LONG"
            else low_quote <= tp1
        )
        runner_reached = (
            high_quote >= runner_target
            if direction == "LONG"
            else low_quote <= runner_target
        )

        # Conservative M5 ordering: stop wins an ambiguous bar. No target credit
        # is allowed on the original fill candle.
        if stop_hit:
            exit_price = _stop_exit_price(
                row=row,
                direction=direction,
                stop=active_stop,
            )
            if tp1_hit:
                realized_price_pnl += remaining_fraction * sign * (
                    exit_price - float(fill)
                )
                runner_state = "BE_STOP"
                full_exit_state = "TP1_THEN_BE"
            else:
                realized_price_pnl = sign * (exit_price - float(fill))
                runner_state = "STOP_BEFORE_TP1"
                full_exit_state = "STOP_BEFORE_TP1"
            final_exit_price = exit_price
            exit_at = at + timedelta(minutes=5)
            break

        if index == fill_index:
            continue

        if not tp1_hit and tp1_reached:
            tp1_hit = True
            tp1_at_known = at + timedelta(minutes=5)
            realized_price_pnl += float(tp1_fraction) * sign * (
                tp1 - float(fill)
            )
            tp1_next_zone = _nearest_active_opposite_h1(
                destinations=destinations,
                direction=direction,
                at=tp1_at_known,
                price=tp1,
            )
            runner_state = "ACTIVE_AFTER_TP1"

            # If the same non-stop bar extends all the way through TP2, the path
            # necessarily crossed TP1 first, so both limits may be credited.
            if runner_reached:
                realized_price_pnl += remaining_fraction * sign * (
                    runner_target - float(fill)
                )
                runner_state = "RUNNER_TP"
                full_exit_state = "TP1_AND_RUNNER_TP"
                final_exit_price = runner_target
                exit_at = at + timedelta(minutes=5)
                break
            continue

        if tp1_hit and runner_reached:
            realized_price_pnl += remaining_fraction * sign * (
                runner_target - float(fill)
            )
            runner_state = "RUNNER_TP"
            full_exit_state = "TP1_AND_RUNNER_TP"
            final_exit_price = runner_target
            exit_at = at + timedelta(minutes=5)
            break

    if exit_at is None:
        if last_index >= len(rows):
            return {
                "state": "CENSORED",
                "filled": True,
                "fill_at": fill_at.isoformat(),
                "fill_price": float(fill),
                "tp1_hit": tp1_hit,
            }
        row = rows[last_index]
        time_price = _time_exit_price(row=row, direction=direction)
        if tp1_hit:
            realized_price_pnl += remaining_fraction * sign * (
                time_price - float(fill)
            )
            runner_state = "TIME_EXIT"
            full_exit_state = "TP1_THEN_TIME_EXIT"
        else:
            realized_price_pnl = sign * (time_price - float(fill))
            runner_state = "TIME_EXIT_BEFORE_TP1"
            full_exit_state = "TIME_EXIT_BEFORE_TP1"
        final_exit_price = time_price
        exit_at = ensure_utc(times[last_index])

    net_r = (realized_price_pnl - COMMISSION_USD) / risk
    precision_tp1 = bool(tp1_hit and max_adverse <= MAX_ADVERSE_PRECISE_USD)
    return {
        "state": full_exit_state or runner_state,
        "filled": True,
        "entry_mode": ENTRY_MODE,
        "stop_mode": STOP_MODE,
        "fill_at": fill_at.isoformat(),
        "fill_price": float(fill),
        "stop": float(stop),
        "risk_usd": risk,
        "tp1_atr": float(tp1_atr),
        "tp1_fraction": float(tp1_fraction),
        "tp1": tp1,
        "tp1_hit": tp1_hit,
        "tp1_at": None if tp1_at_known is None else tp1_at_known.isoformat(),
        "runner_atr": float(runner_atr),
        "runner_target": runner_target,
        "terminal_rr": terminal_rr,
        "runner_state": runner_state,
        "runner_tp": runner_state == "RUNNER_TP",
        "exit_at": exit_at.isoformat(),
        "exit_price": final_exit_price,
        "net_r": net_r,
        "max_adverse_usd": max_adverse,
        "precision_5_and_tp1": precision_tp1,
        "tp1_next_opposite_h1": tp1_next_zone,
        "minutes_confirmation_to_fill": (
            fill_at - ensure_utc(confirmation_at)
        ).total_seconds() / 60.0,
        "holding_minutes": (exit_at - fill_at).total_seconds() / 60.0,
    }


def _summary(
    results: Sequence[dict[str, Any]],
    *,
    opportunities: int,
) -> dict[str, Any]:
    sample = list(results)
    fills = [row for row in sample if row.get("filled")]
    resolved = [
        row
        for row in fills
        if row.get("state") not in {"CENSORED", ""}
    ]
    tp1_hits = [row for row in resolved if row.get("tp1_hit")]
    precise_tp1 = [row for row in resolved if row.get("precision_5_and_tp1")]
    runner_tp = [row for row in resolved if row.get("runner_tp")]
    be = [row for row in resolved if row.get("runner_state") == "BE_STOP"]
    stops_before = [
        row for row in resolved if row.get("runner_state") == "STOP_BEFORE_TP1"
    ]
    net = [float(row["net_r"]) for row in resolved if row.get("net_r") is not None]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    adverse = [
        float(row["max_adverse_usd"])
        for row in resolved
        if row.get("max_adverse_usd") is not None
    ]
    fill_delays = [
        float(row["minutes_confirmation_to_fill"])
        for row in fills
        if row.get("minutes_confirmation_to_fill") is not None
    ]
    opposite_rows = [
        dict(row.get("tp1_next_opposite_h1") or {})
        for row in tp1_hits
        if row.get("tp1_next_opposite_h1")
    ]
    opposite_within_5 = [
        row for row in opposite_rows if bool(row.get("within_5_usd"))
    ]
    opposite_gaps = [
        float(row["gap_usd"])
        for row in opposite_rows
        if row.get("gap_usd") is not None
    ]
    tp1_rate = len(tp1_hits) / len(resolved) if resolved else None
    profit_factor = (
        sum(wins) / abs(sum(losses))
        if losses
        else None
    )
    return {
        "opportunities": opportunities,
        "fills": len(fills),
        "fill_rate": len(fills) / opportunities if opportunities else None,
        "resolved": len(resolved),
        "tp1_hits": len(tp1_hits),
        "tp1_hit_rate": tp1_rate,
        "tp1_wilson_lower_95": (
            wilson_lower_bound(len(tp1_hits), len(resolved))
            if resolved else None
        ),
        "precision_5_and_tp1": len(precise_tp1),
        "precision_5_and_tp1_rate": (
            len(precise_tp1) / len(resolved) if resolved else None
        ),
        "runner_tp": len(runner_tp),
        "runner_tp_rate_all_resolved": (
            len(runner_tp) / len(resolved) if resolved else None
        ),
        "runner_tp_rate_after_tp1": (
            len(runner_tp) / len(tp1_hits) if tp1_hits else None
        ),
        "be_after_tp1": len(be),
        "stop_before_tp1": len(stops_before),
        "avg_net_r": sum(net) / len(net) if net else None,
        "median_net_r": median(net) if net else None,
        "profit_factor": profit_factor,
        "profit_factor_unbounded": bool(wins and not losses),
        "median_max_adverse_usd": median(adverse) if adverse else None,
        "median_minutes_confirmation_to_fill": (
            median(fill_delays) if fill_delays else None
        ),
        "tp1_with_active_opposite_h1": len(opposite_rows),
        "tp1_opposite_h1_within_5_usd": len(opposite_within_5),
        "tp1_opposite_h1_within_5_rate": (
            len(opposite_within_5) / len(tp1_hits) if tp1_hits else None
        ),
        "median_tp1_to_opposite_h1_gap_usd": (
            median(opposite_gaps) if opposite_gaps else None
        ),
    }


def _combo_key(tp1_atr: float, fraction: float, runner_atr: float) -> str:
    return (
        f"TP1_{tp1_atr:.2f}ATR|PART_{int(round(fraction * 100))}|"
        f"RUNNER_{runner_atr:.2f}ATR"
    )


def _evaluate_grid(
    opportunities: Sequence[dict[str, Any]],
    *,
    zone_by_id: dict[str, ZoneDestination],
    destinations: Sequence[ZoneDestination],
    m5_rows: Sequence[Bar],
) -> dict[str, Any]:
    times = _times(m5_rows)
    output: dict[str, Any] = {}
    for tp1_atr in TP1_ATR_MULTIPLES:
        for fraction in TP1_FRACTIONS:
            for runner_atr in RUNNER_ATR_MULTIPLES:
                if runner_atr <= tp1_atr:
                    continue
                key = _combo_key(tp1_atr, fraction, runner_atr)
                results: list[dict[str, Any]] = []
                for opportunity in opportunities:
                    zone = zone_by_id.get(str(opportunity["selected_zone_id"]))
                    if zone is None:
                        continue
                    micro = dict(opportunity.get("micro") or {})
                    pocket = dict(micro.get("refined_entry_pocket") or {})
                    confirmation_at = _dt(micro["confirmation_at"])
                    replay = _replay_ladder(
                        rows=m5_rows,
                        times=times,
                        zone=zone,
                        confirmation_at=confirmation_at,
                        pocket=pocket,
                        tp1_atr=tp1_atr,
                        tp1_fraction=fraction,
                        runner_atr=runner_atr,
                        destinations=destinations,
                    )
                    results.append({
                        "selected_zone_id": zone.zone_id,
                        "confirmation_at": confirmation_at.isoformat(),
                        **replay,
                    })
                output[key] = {
                    "tp1_atr": tp1_atr,
                    "tp1_fraction": fraction,
                    "runner_atr": runner_atr,
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
        tp1_rate = float(summary.get("tp1_hit_rate") or 0.0)
        avg_r = summary.get("avg_net_r")
        pf = summary.get("profit_factor")
        pf_rank = (
            1_000_000.0
            if bool(summary.get("profit_factor_unbounded"))
            else float(pf or 0.0)
        )
        if (
            fills < MIN_DEVELOPMENT_FILLS
            or tp1_rate < MIN_DEVELOPMENT_TP1_RATE
            or pf_rank < MIN_DEVELOPMENT_PROFIT_FACTOR
            or avg_r is None
            or float(avg_r) < MIN_DEVELOPMENT_AVG_NET_R
        ):
            continue
        eligible.append((
            -float(summary.get("precision_5_and_tp1_rate") or 0.0),
            -tp1_rate,
            -float(avg_r),
            -pf_rank,
            key,
        ))
    if not eligible:
        return None
    eligible.sort()
    return str(eligible[0][-1])


def _holdout_gate(summary: dict[str, Any]) -> dict[str, Any]:
    fills = int(summary.get("fills") or 0)
    fill_rate = float(summary.get("fill_rate") or 0.0)
    tp1_rate = float(summary.get("tp1_hit_rate") or 0.0)
    wilson = float(summary.get("tp1_wilson_lower_95") or 0.0)
    precise = float(summary.get("precision_5_and_tp1_rate") or 0.0)
    pf = (
        1_000_000.0
        if bool(summary.get("profit_factor_unbounded"))
        else float(summary.get("profit_factor") or 0.0)
    )
    avg_r = float(summary.get("avg_net_r") or 0.0)
    passed = bool(
        fills >= MIN_HOLDOUT_FILLS
        and fill_rate >= MIN_HOLDOUT_FILL_RATE
        and tp1_rate >= MIN_HOLDOUT_TP1_RATE
        and wilson >= MIN_HOLDOUT_TP1_WILSON
        and precise >= MIN_HOLDOUT_PRECISION_TP1_RATE
        and pf >= MIN_HOLDOUT_PROFIT_FACTOR
        and avg_r >= MIN_HOLDOUT_AVG_NET_R
    )
    return {
        "min_fills": MIN_HOLDOUT_FILLS,
        "min_fill_rate": MIN_HOLDOUT_FILL_RATE,
        "min_tp1_hit_rate": MIN_HOLDOUT_TP1_RATE,
        "min_tp1_wilson_lower_95": MIN_HOLDOUT_TP1_WILSON,
        "min_precision_5_and_tp1_rate": MIN_HOLDOUT_PRECISION_TP1_RATE,
        "min_profit_factor": MIN_HOLDOUT_PROFIT_FACTOR,
        "min_avg_net_r": MIN_HOLDOUT_AVG_NET_R,
        "passed": passed,
    }


def evaluate_precision_tp_ladder(
    m15_bars: Sequence[Bar],
    m5_bars: Sequence[Bar],
) -> dict[str, Any]:
    m15_rows = _validate_bars(m15_bars)
    m5_rows = tuple(sorted(m5_bars, key=lambda row: ensure_utc(row.timestamp)))
    confirmed, zone_by_id = _confirmed_opportunities(m15_rows, m5_rows)
    destinations, _, _ = build_transition_ledger(m15_rows)
    development, holdout = _split(confirmed)

    development_grid = _evaluate_grid(
        development,
        zone_by_id=zone_by_id,
        destinations=destinations,
        m5_rows=m5_rows,
    )
    selected_key = _select_development_combo(development_grid)

    holdout_grid = _evaluate_grid(
        holdout,
        zone_by_id=zone_by_id,
        destinations=destinations,
        m5_rows=m5_rows,
    )
    selected_holdout = (
        None if selected_key is None else holdout_grid.get(selected_key)
    )
    selected_summary = (
        {} if selected_holdout is None
        else dict(selected_holdout.get("summary") or {})
    )
    gate = (
        _holdout_gate(selected_summary)
        if selected_holdout is not None
        else {"passed": False, "reason": "NO_DEVELOPMENT_COMBO_SELECTED"}
    )

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
        "entry_contract": {
            "source": "V314_DEVELOPMENT_SELECTED_GEOMETRY",
            "entry_mode": ENTRY_MODE,
            "stop_mode": STOP_MODE,
            "limit_fill_window_minutes": LIMIT_FILL_WINDOW_MINUTES,
            "terminal_rr_floor": MIN_TERMINAL_RR,
        },
        "ladder_grid": {
            "tp1_atr_multiples": list(TP1_ATR_MULTIPLES),
            "tp1_fractions": list(TP1_FRACTIONS),
            "runner_atr_multiples": list(RUNNER_ATR_MULTIPLES),
            "move_remaining_stop_to_break_even_after_tp1": True,
            "break_even_activation": "NEXT_M5_BAR_OR_LATER",
            "stop_first": True,
            "no_tp_credit_on_fill_candle": True,
            "max_hold_minutes": MAX_HOLD_MINUTES,
        },
        "cost_contract": {
            "spread_usd": SPREAD_USD,
            "slippage_usd": SLIPPAGE_USD,
            "commission_usd_round_trip": COMMISSION_USD,
            "provenance": "V242_FIXED_PROXY_COSTS",
        },
        "selection_contract": {
            "development_fraction": DEVELOPMENT_FRACTION,
            "purge_hours": PURGE_HOURS,
            "min_development_fills": MIN_DEVELOPMENT_FILLS,
            "min_development_tp1_rate": MIN_DEVELOPMENT_TP1_RATE,
            "min_development_profit_factor": MIN_DEVELOPMENT_PROFIT_FACTOR,
            "min_development_avg_net_r": MIN_DEVELOPMENT_AVG_NET_R,
            "ranking": (
                "PRECISION_5_TP1_THEN_TP1_RATE_THEN_AVG_NET_R_THEN_PROFIT_FACTOR"
            ),
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
            "V315_REUSES_V313_V314_RECENT_ERA_SAMPLE_NOT_EXTERNAL_OOS",
            "V314_HOLDOUT_WAS_PREVIOUSLY_OBSERVED_SO_V315_IS_STAGE3_REANALYSIS",
            "FIXED_SPREAD_SLIPPAGE_COMMISSION_PROXY_NOT_HISTORICAL_TICK_COST",
            "M5_OHLC_INTRABAR_AMBIGUITY_RESOLVED_WITH_STOP_FIRST",
            "BREAK_EVEN_ACTIVATES_ONLY_AFTER_TP1_BAR_COMPLETES",
            "OPPOSITE_H1_PROXIMITY_IS_CONTEXT_NOT_NEXT_TRADE_AUTHORITY",
            "NO_EXECUTION_OR_PROMOTION_AUTHORITY",
        ],
    }
