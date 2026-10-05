from __future__ import annotations

"""V399 causal probe/add management replay for the AFIQ-pattern hypothesis.

V397 rejected full-size anticipatory entry. V398 rejected waiting for a frozen
reclaim and then entering full size. V399 tests the missing middle ground:
open one quarter of planned exposure in the effective HTF zone, freeze the
validation/invalidation/target geometry, then add the remaining three quarters
only after a later H1 close reclaims the frozen validation level.

If validation does not occur within a small predeclared window, the probe is
closed at the next H1 open instead of being allowed to drift to the structural
stop. STOP_FIRST remains conservative whenever stop and target coexist inside
one H1 bar. Research/shadow only; no order authority.
"""

from dataclasses import asdict, dataclass
from math import inf
from statistics import fmean
from typing import Any, Iterable

from .xau_afiq_challenger_v395 import MIN_RR, evaluate_afiq_challenger_v395
from .xau_afiq_frozen_reclaim_replay_v398 import _valid_frozen_geometry
from .xau_afiq_replay_v396 import (
    _close_at,
    _ts,
    build_context,
    build_liquidity_fractals,
    build_zone_metadata,
)
from .xau_afiq_risk_replay_v397 import (
    COST_STRESS_PRICE_UNITS,
    _max_drawdown,
    _minimum_risk,
    _pf,
    _valid_target,
)
from .xau_sd_liquidity_engine_v342_legacy import detect_zones

CONTRACT = "XAU_RIZAN_AFIQ_PROBE_ADD_REPLAY_V399"
PROBE_FRACTION = 0.25
ADD_FRACTION = 0.75
VALIDATION_WINDOWS = (2, 4, 8, 12)
MAX_HOLD_H1_BARS = 96


@dataclass(frozen=True, slots=True)
class ProbeAddTrade:
    variant: str
    direction: str
    signal_index: int
    probe_entry_index: int
    add_entry_index: int | None
    exit_index: int
    signal_at: str
    probe_entry_at: str
    add_entry_at: str | None
    exit_at: str
    probe_entry: float
    add_entry: float | None
    stop: float
    validation: float
    target: float
    exit_price: float
    pnl_price_weighted: float
    risk_price_weighted: float
    exposure_fraction: float
    confirmed: bool
    confirmation_delay_bars: int | None
    bars_held: int
    exit_reason: str
    zone_id: str | None
    timeframe: str
    effective_score: float
    rr_probe_initial: float


def _signed(direction: str, exit_price: float, entry: float) -> float:
    return exit_price - entry if direction == "LONG" else entry - exit_price


def _through(direction: str, close: float, level: float) -> bool:
    return close >= level if direction == "LONG" else close <= level


def _precheck(bars_h1: tuple[Any, ...], signal_index: int, candidate: dict[str, Any]) -> dict[str, float] | None:
    entry_index = signal_index + 1
    if entry_index >= len(bars_h1):
        return None
    if not _valid_frozen_geometry(candidate):
        return None
    direction = str(candidate.get("direction") or "")
    if direction not in {"LONG", "SHORT"}:
        return None
    probe_entry = float(bars_h1[entry_index].open)
    stop = float(candidate["structural_invalidation"])
    validation = float(candidate["validation_level"])
    target = _valid_target(direction, probe_entry, candidate.get("targets") or [])
    if target is None:
        return None
    low = float(candidate["low"])
    high = float(candidate["high"])
    tolerance = 0.25 * max(high - low, 0.01)
    if probe_entry < low - tolerance or probe_entry > high + tolerance:
        return None
    risk = probe_entry - stop if direction == "LONG" else stop - probe_entry
    reward = target - probe_entry if direction == "LONG" else probe_entry - target
    if risk <= 0 or reward <= 0:
        return None
    if risk < _minimum_risk(probe_entry, low, high):
        return None
    if reward / risk < MIN_RR:
        return None
    # The add trigger must occur before the terminal target.
    if direction == "LONG" and not (probe_entry < validation < target):
        return None
    if direction == "SHORT" and not (probe_entry > validation > target):
        return None
    return {
        "entry_index": float(entry_index),
        "probe_entry": probe_entry,
        "stop": stop,
        "validation": validation,
        "target": target,
        "risk": risk,
        "reward": reward,
    }


def resolve_probe_add(
    bars_h1: tuple[Any, ...],
    *,
    signal_index: int,
    candidate: dict[str, Any],
    validation_window: int,
    max_hold: int = MAX_HOLD_H1_BARS,
) -> ProbeAddTrade | None:
    checked = _precheck(bars_h1, signal_index, candidate)
    if checked is None:
        return None
    direction = str(candidate["direction"])
    entry_index = int(checked["entry_index"])
    probe_entry = checked["probe_entry"]
    stop = checked["stop"]
    validation = checked["validation"]
    target = checked["target"]
    probe_risk = checked["risk"]
    rr_probe = checked["reward"] / probe_risk

    confirm_index: int | None = None
    add_index: int | None = None
    add_entry: float | None = None
    deadline = min(len(bars_h1) - 1, entry_index + validation_window - 1)

    # Phase 1: one-quarter probe. A bar can hit the structural stop/target before
    # its close becomes available; therefore intrabar exits are evaluated first.
    for j in range(entry_index, deadline + 1):
        bar = bars_h1[j]
        if direction == "LONG":
            stop_hit = float(bar.low) <= stop
            target_hit = float(bar.high) >= target
        else:
            stop_hit = float(bar.high) >= stop
            target_hit = float(bar.low) <= target
        if stop_hit or target_hit:
            exit_price = stop if stop_hit else target
            pnl = PROBE_FRACTION * _signed(direction, exit_price, probe_entry)
            return ProbeAddTrade(
                variant=f"PROBE25_ADD75_W{validation_window}", direction=direction,
                signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=None,
                exit_index=j, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
                probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=None,
                exit_at=_ts(bars_h1[j]).isoformat(), probe_entry=probe_entry, add_entry=None,
                stop=stop, validation=validation, target=target, exit_price=exit_price,
                pnl_price_weighted=pnl, risk_price_weighted=PROBE_FRACTION * probe_risk,
                exposure_fraction=PROBE_FRACTION, confirmed=False, confirmation_delay_bars=None,
                bars_held=j-entry_index+1, exit_reason="STOP_FIRST_PROBE" if stop_hit else "TARGET_PROBE",
                zone_id=candidate.get("zone_id"), timeframe=str(candidate.get("timeframe") or "HTF"),
                effective_score=float(candidate.get("score") or 0.0), rr_probe_initial=rr_probe,
            )
        if _through(direction, float(bar.close), validation):
            confirm_index = j
            break

    # No confirmation in the allowed window: cut the probe causally at the next
    # H1 open (or the last close if history ends).
    if confirm_index is None:
        exit_index = min(deadline + 1, len(bars_h1) - 1)
        exit_price = float(bars_h1[exit_index].open) if exit_index > deadline else float(bars_h1[deadline].close)
        pnl = PROBE_FRACTION * _signed(direction, exit_price, probe_entry)
        return ProbeAddTrade(
            variant=f"PROBE25_ADD75_W{validation_window}", direction=direction,
            signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=None,
            exit_index=exit_index, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=None,
            exit_at=_ts(bars_h1[exit_index]).isoformat(), probe_entry=probe_entry, add_entry=None,
            stop=stop, validation=validation, target=target, exit_price=exit_price,
            pnl_price_weighted=pnl, risk_price_weighted=PROBE_FRACTION * probe_risk,
            exposure_fraction=PROBE_FRACTION, confirmed=False, confirmation_delay_bars=None,
            bars_held=exit_index-entry_index+1, exit_reason="VALIDATION_TIMEOUT_EXIT",
            zone_id=candidate.get("zone_id"), timeframe=str(candidate.get("timeframe") or "HTF"),
            effective_score=float(candidate.get("score") or 0.0), rr_probe_initial=rr_probe,
        )

    add_index = confirm_index + 1
    if add_index >= len(bars_h1):
        exit_price = float(bars_h1[confirm_index].close)
        pnl = PROBE_FRACTION * _signed(direction, exit_price, probe_entry)
        return ProbeAddTrade(
            variant=f"PROBE25_ADD75_W{validation_window}", direction=direction,
            signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=None,
            exit_index=confirm_index, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=None,
            exit_at=_close_at(bars_h1[confirm_index]).isoformat(), probe_entry=probe_entry, add_entry=None,
            stop=stop, validation=validation, target=target, exit_price=exit_price,
            pnl_price_weighted=pnl, risk_price_weighted=PROBE_FRACTION * probe_risk,
            exposure_fraction=PROBE_FRACTION, confirmed=True,
            confirmation_delay_bars=confirm_index-entry_index+1, bars_held=confirm_index-entry_index+1,
            exit_reason="HISTORY_END_AFTER_CONFIRM", zone_id=candidate.get("zone_id"),
            timeframe=str(candidate.get("timeframe") or "HTF"), effective_score=float(candidate.get("score") or 0.0),
            rr_probe_initial=rr_probe,
        )

    add_entry = float(bars_h1[add_index].open)
    # If the next open has already gapped outside the frozen structural path,
    # do not add three quarters; close the probe at that open.
    add_valid = (stop < add_entry < target) if direction == "LONG" else (stop > add_entry > target)
    if not add_valid:
        pnl = PROBE_FRACTION * _signed(direction, add_entry, probe_entry)
        return ProbeAddTrade(
            variant=f"PROBE25_ADD75_W{validation_window}", direction=direction,
            signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=None,
            exit_index=add_index, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=None,
            exit_at=_ts(bars_h1[add_index]).isoformat(), probe_entry=probe_entry, add_entry=None,
            stop=stop, validation=validation, target=target, exit_price=add_entry,
            pnl_price_weighted=pnl, risk_price_weighted=PROBE_FRACTION * probe_risk,
            exposure_fraction=PROBE_FRACTION, confirmed=True,
            confirmation_delay_bars=confirm_index-entry_index+1, bars_held=add_index-entry_index+1,
            exit_reason="ADD_GAP_INVALID_EXIT_PROBE", zone_id=candidate.get("zone_id"),
            timeframe=str(candidate.get("timeframe") or "HTF"), effective_score=float(candidate.get("score") or 0.0),
            rr_probe_initial=rr_probe,
        )

    add_risk = add_entry - stop if direction == "LONG" else stop - add_entry
    weighted_risk = PROBE_FRACTION * probe_risk + ADD_FRACTION * add_risk
    last = min(len(bars_h1) - 1, entry_index + max_hold - 1)
    for j in range(add_index, last + 1):
        bar = bars_h1[j]
        if direction == "LONG":
            stop_hit = float(bar.low) <= stop
            target_hit = float(bar.high) >= target
        else:
            stop_hit = float(bar.high) >= stop
            target_hit = float(bar.low) <= target
        if not (stop_hit or target_hit):
            continue
        exit_price = stop if stop_hit else target
        pnl = (
            PROBE_FRACTION * _signed(direction, exit_price, probe_entry)
            + ADD_FRACTION * _signed(direction, exit_price, add_entry)
        )
        return ProbeAddTrade(
            variant=f"PROBE25_ADD75_W{validation_window}", direction=direction,
            signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=add_index,
            exit_index=j, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=_ts(bars_h1[add_index]).isoformat(),
            exit_at=_ts(bars_h1[j]).isoformat(), probe_entry=probe_entry, add_entry=add_entry,
            stop=stop, validation=validation, target=target, exit_price=exit_price,
            pnl_price_weighted=pnl, risk_price_weighted=weighted_risk, exposure_fraction=1.0,
            confirmed=True, confirmation_delay_bars=confirm_index-entry_index+1,
            bars_held=j-entry_index+1, exit_reason="STOP_FIRST_AFTER_ADD" if stop_hit else "TARGET_AFTER_ADD",
            zone_id=candidate.get("zone_id"), timeframe=str(candidate.get("timeframe") or "HTF"),
            effective_score=float(candidate.get("score") or 0.0), rr_probe_initial=rr_probe,
        )

    exit_price = float(bars_h1[last].close)
    pnl = (
        PROBE_FRACTION * _signed(direction, exit_price, probe_entry)
        + ADD_FRACTION * _signed(direction, exit_price, add_entry)
    )
    return ProbeAddTrade(
        variant=f"PROBE25_ADD75_W{validation_window}", direction=direction,
        signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=add_index,
        exit_index=last, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
        probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=_ts(bars_h1[add_index]).isoformat(),
        exit_at=_close_at(bars_h1[last]).isoformat(), probe_entry=probe_entry, add_entry=add_entry,
        stop=stop, validation=validation, target=target, exit_price=exit_price,
        pnl_price_weighted=pnl, risk_price_weighted=weighted_risk, exposure_fraction=1.0,
        confirmed=True, confirmation_delay_bars=confirm_index-entry_index+1,
        bars_held=last-entry_index+1, exit_reason="TIMEOUT_AFTER_ADD",
        zone_id=candidate.get("zone_id"), timeframe=str(candidate.get("timeframe") or "HTF"),
        effective_score=float(candidate.get("score") or 0.0), rr_probe_initial=rr_probe,
    )


def _metrics(trades: list[ProbeAddTrade]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "win_rate": None, "fixed_price_pf": None, "expectancy_price": None}
    pnl = [trade.pnl_price_weighted for trade in trades]
    r = [trade.pnl_price_weighted / trade.risk_price_weighted for trade in trades if trade.risk_price_weighted > 0]
    stress: dict[str, Any] = {}
    for cost in COST_STRESS_PRICE_UNITS:
        adjusted = [trade.pnl_price_weighted - cost * trade.exposure_fraction for trade in trades]
        stress[f"cost_{cost:.2f}"] = {
            "fixed_price_pf": _pf(adjusted),
            "expectancy_price": fmean(adjusted),
            "net_price": sum(adjusted),
            "max_drawdown_price": _max_drawdown(adjusted),
        }
    return {
        "trades": len(trades),
        "wins": sum(value > 0 for value in pnl),
        "losses": sum(value < 0 for value in pnl),
        "win_rate": sum(value > 0 for value in pnl) / len(pnl),
        "fixed_price_pf": _pf(pnl),
        "expectancy_price": fmean(pnl),
        "net_price": sum(pnl),
        "max_drawdown_price": _max_drawdown(pnl),
        "r_pf": _pf(r),
        "expectancy_r": fmean(r),
        "net_r": sum(r),
        "confirmed_trades": sum(trade.confirmed for trade in trades),
        "added_trades": sum(trade.add_entry_index is not None for trade in trades),
        "probe_only_trades": sum(trade.add_entry_index is None for trade in trades),
        "avg_exposure_fraction": fmean(trade.exposure_fraction for trade in trades),
        "avg_bars_held": fmean(trade.bars_held for trade in trades),
        "avg_confirmation_delay": fmean(
            trade.confirmation_delay_bars for trade in trades if trade.confirmation_delay_bars is not None
        ) if any(trade.confirmation_delay_bars is not None for trade in trades) else None,
        "long_trades": sum(trade.direction == "LONG" for trade in trades),
        "short_trades": sum(trade.direction == "SHORT" for trade in trades),
        "cost_stress": stress,
    }


def _by_year(trades: list[ProbeAddTrade], bars_h1: tuple[Any, ...]) -> dict[str, Any]:
    years = sorted({_ts(bars_h1[t.probe_entry_index]).year for t in trades})
    return {str(year): _metrics([t for t in trades if _ts(bars_h1[t.probe_entry_index]).year == year]) for year in years}


def run_replay(bars_h1: Iterable[Any], bars_h4: Iterable[Any]) -> dict[str, Any]:
    h1 = tuple(sorted(bars_h1, key=lambda bar: _ts(bar)))
    h4 = tuple(sorted(bars_h4, key=lambda bar: _ts(bar)))
    if len(h1) < 200 or len(h4) < 30:
        raise ValueError("V399_REPLAY_INSUFFICIENT_HISTORY")
    as_of = _close_at(h1[-1])
    zones = tuple(detect_zones(h1, timeframe="H1", as_of=as_of)) + tuple(detect_zones(h4, timeframe="H4", as_of=as_of))
    metas = build_zone_metadata(zones, h1)
    fractals = build_liquidity_fractals(h1)

    trades_by_window: dict[int, list[ProbeAddTrade]] = {window: [] for window in VALIDATION_WINDOWS}
    next_free: dict[int, int] = {window: 0 for window in VALIDATION_WINDOWS}
    rejects: dict[int, int] = {window: 0 for window in VALIDATION_WINDOWS}
    state_counts: dict[str, int] = {}

    for i in range(120, len(h1) - 1):
        context = build_context(h1, metas, fractals, i)
        result = evaluate_afiq_challenger_v395(context)
        state = str(result.get("state") or "UNKNOWN")
        state_counts[state] = state_counts.get(state, 0) + 1
        candidates = list(result.get("candidates") or [])
        if state != "EARLY_TAKE_RISK" or not candidates:
            continue
        candidate = dict(candidates[0])
        for window in VALIDATION_WINDOWS:
            if i < next_free[window]:
                continue
            trade = resolve_probe_add(h1, signal_index=i, candidate=candidate, validation_window=window)
            if trade is None:
                rejects[window] += 1
                continue
            trades_by_window[window].append(trade)
            next_free[window] = trade.exit_index + 1

    variants: dict[str, Any] = {}
    gates: dict[str, Any] = {}
    for window in VALIDATION_WINDOWS:
        name = f"PROBE25_ADD75_W{window}"
        trades = trades_by_window[window]
        metrics = _metrics(trades)
        by_year = _by_year(trades, h1)
        variants[name] = {"metrics": metrics, "by_year": by_year, "trades": [asdict(t) for t in trades]}
        pf = metrics.get("fixed_price_pf")
        exp = metrics.get("expectancy_price")
        yearly_pfs = [row.get("fixed_price_pf") for row in by_year.values()]
        stress_pf = metrics.get("cost_stress", {}).get("cost_0.50", {}).get("fixed_price_pf")
        gates[name] = {
            "fixed_price_pf_gte_1_5": pf is not None and pf != inf and float(pf) >= 1.5,
            "expectancy_price_positive": exp is not None and float(exp) > 0,
            "each_year_pf_gte_1_0": bool(yearly_pfs) and all(value is not None and (value == inf or float(value) >= 1.0) for value in yearly_pfs),
            "cost_0_50_pf_gte_1_2": stress_pf is not None and (stress_pf == inf or float(stress_pf) >= 1.2),
        }

    return {
        "contract": CONTRACT,
        "engine_contract": "XAU_RIZAN_AFIQ_CHALLENGER_V395",
        "period": {"start": _ts(h1[0]).isoformat(), "end": _close_at(h1[-1]).isoformat()},
        "bars": {"H1": len(h1), "H4": len(h4)},
        "causality": {
            "signal": "EARLY_TAKE_RISK_AT_H1_CLOSE",
            "probe_fill": "NEXT_H1_OPEN",
            "validation": "LATER_H1_CLOSE_THROUGH_FROZEN_LEVEL",
            "add_fill": "NEXT_H1_OPEN_AFTER_VALIDATION",
            "failed_validation_exit": "NEXT_H1_OPEN_AFTER_WINDOW",
            "same_bar_conflict": "STOP_FIRST",
            "future_outcomes_as_inputs": False,
        },
        "sizing_model": {"probe_fraction": PROBE_FRACTION, "add_fraction": ADD_FRACTION, "max_total_fraction": 1.0},
        "validation_windows_h1": list(VALIDATION_WINDOWS),
        "state_counts": state_counts,
        "reject_counts": {str(k): v for k, v in rejects.items()},
        "variants": variants,
        "numeric_gates": gates,
        "promotion_eligible": False,
        "promotion_blockers": [
            "HISTORICAL_SPREAD_AND_COMMISSION_NOT_OBSERVED",
            "CAUSAL_EVENT_BLACKOUT_ARCHIVE_NOT_APPLIED",
            "WINDOW_SELECTION_REQUIRES_OUT_OF_SAMPLE_CONFIRMATION",
            "LONGER_HISTORY_REQUIRED",
        ],
    }
