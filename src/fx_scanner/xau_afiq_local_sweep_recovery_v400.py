from __future__ import annotations

"""V400 causal local sweep-recovery replay for the AFIQ-pattern hypothesis.

V397 rejected full-size anticipatory entry. V398 rejected entering full size
only after a distant frozen liquidity reclaim. V399 showed that a 25% probe +
75% add on that same distant reclaim still has negative expectancy.

V400 tests a different, predeclared hypothesis that is closer to the observed
AFIQ behavior: the useful confirmation may be *local* recovery after an
adverse-side liquidity sweep inside/around the HTF zone, not a distant BSL/SSL
reclaim. At the causal EARLY signal, only already-known and still-unswept H1
fractals may be used. One quarter is probed at the next H1 open; three quarters
are added only after a later H1 close recovers one of three structural levels:

* SWEPT_LIQUIDITY  -- weakest local recovery;
* ZONE_MID         -- balanced recovery;
* ZONE_PROXIMAL    -- strongest return through the zone edge.

The three levels are structural hypotheses, not optimized numeric thresholds.
STOP_FIRST is retained. Research/shadow only; no DEMO/LIVE order authority.
"""

from dataclasses import asdict, dataclass
from math import inf
from statistics import fmean
from typing import Any, Iterable

from .xau_afiq_challenger_v395 import MIN_RR, evaluate_afiq_challenger_v395
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

CONTRACT = "XAU_RIZAN_AFIQ_LOCAL_SWEEP_RECOVERY_V400"
PROBE_FRACTION = 0.25
ADD_FRACTION = 0.75
RECOVERY_MODES = ("SWEPT_LIQUIDITY", "ZONE_MID", "ZONE_PROXIMAL")
RECOVERY_WINDOW_H1 = 8
MAX_HOLD_H1_BARS = 96


@dataclass(frozen=True, slots=True)
class LocalRecoveryTrade:
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
    zone_low: float
    zone_high: float
    stop: float
    target: float
    swept_liquidity: float
    recovery_level: float
    sweep_index: int | None
    recovery_index: int | None
    exit_price: float
    pnl_price_weighted: float
    risk_price_weighted: float
    exposure_fraction: float
    bars_held: int
    exit_reason: str
    zone_id: str | None
    timeframe: str
    effective_score: float


def _signed(direction: str, exit_price: float, entry: float) -> float:
    return exit_price - entry if direction == "LONG" else entry - exit_price


def _unconsumed(row: dict[str, Any], bars_h1: tuple[Any, ...], signal_index: int) -> bool:
    """A fractal is eligible only if it has not been traded through after pivot."""
    try:
        pivot_index = int(row["pivot_index"])
        available_index = int(row["available_index"])
        price = float(row["price"])
    except (KeyError, TypeError, ValueError):
        return False
    if available_index > signal_index or pivot_index >= signal_index:
        return False
    start = max(pivot_index + 1, 0)
    if str(row.get("side") or "").upper() == "SELL_SIDE":
        return not any(float(bars_h1[j].low) <= price for j in range(start, signal_index + 1))
    if str(row.get("side") or "").upper() == "BUY_SIDE":
        return not any(float(bars_h1[j].high) >= price for j in range(start, signal_index + 1))
    return False


def _select_liquidity(
    candidate: dict[str, Any],
    bars_h1: tuple[Any, ...],
    signal_index: int,
    probe_entry: float,
    stop: float,
) -> float | None:
    direction = str(candidate.get("direction") or "")
    wanted = "SELL_SIDE" if direction == "LONG" else "BUY_SIDE"
    valid: list[float] = []
    for raw in list(candidate.get("liquidity") or []):
        row = dict(raw or {})
        if str(row.get("side") or "").upper() != wanted:
            continue
        if not _unconsumed(row, bars_h1, signal_index):
            continue
        try:
            price = float(row["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if direction == "LONG" and stop < price < probe_entry:
            valid.append(price)
        elif direction == "SHORT" and probe_entry < price < stop:
            valid.append(price)
    if not valid:
        return None
    # Closest adverse-side pool is the first pool expected to be swept.
    return max(valid) if direction == "LONG" else min(valid)


def _recovery_level(mode: str, direction: str, low: float, high: float, liquidity: float) -> float:
    if mode == "SWEPT_LIQUIDITY":
        return liquidity
    if mode == "ZONE_MID":
        return (low + high) / 2.0
    if mode == "ZONE_PROXIMAL":
        return high if direction == "LONG" else low
    raise ValueError(mode)


def _recovered(direction: str, close: float, level: float) -> bool:
    return close >= level if direction == "LONG" else close <= level


def _swept(direction: str, bar: Any, level: float) -> bool:
    return float(bar.low) <= level if direction == "LONG" else float(bar.high) >= level


def resolve_local_recovery(
    bars_h1: tuple[Any, ...],
    *,
    signal_index: int,
    candidate: dict[str, Any],
    recovery_mode: str,
    recovery_window: int = RECOVERY_WINDOW_H1,
    max_hold: int = MAX_HOLD_H1_BARS,
) -> LocalRecoveryTrade | None:
    if recovery_mode not in RECOVERY_MODES:
        raise ValueError(recovery_mode)
    entry_index = signal_index + 1
    if entry_index >= len(bars_h1):
        return None
    direction = str(candidate.get("direction") or "")
    if direction not in {"LONG", "SHORT"}:
        return None

    probe_entry = float(bars_h1[entry_index].open)
    low = float(candidate["low"])
    high = float(candidate["high"])
    stop = float(candidate["structural_invalidation"])
    target = _valid_target(direction, probe_entry, candidate.get("targets") or [])
    if target is None:
        return None

    tolerance = 0.25 * max(high - low, 0.01)
    if probe_entry < low - tolerance or probe_entry > high + tolerance:
        return None
    probe_risk = probe_entry - stop if direction == "LONG" else stop - probe_entry
    reward = target - probe_entry if direction == "LONG" else probe_entry - target
    if probe_risk <= 0 or reward <= 0:
        return None
    if probe_risk < _minimum_risk(probe_entry, low, high) or reward / probe_risk < MIN_RR:
        return None

    liquidity = _select_liquidity(candidate, bars_h1, signal_index, probe_entry, stop)
    if liquidity is None:
        return None
    recovery = _recovery_level(recovery_mode, direction, low, high, liquidity)
    # A recovery trigger must sit between structural stop and target and must not
    # be beyond the terminal target.
    if direction == "LONG" and not (stop < liquidity <= recovery < target):
        return None
    if direction == "SHORT" and not (stop > liquidity >= recovery > target):
        return None

    deadline = min(len(bars_h1) - 1, entry_index + recovery_window - 1)
    sweep_index: int | None = None
    recovery_index: int | None = None

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
            return LocalRecoveryTrade(
                variant=f"LOCAL_{recovery_mode}", direction=direction,
                signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=None,
                exit_index=j, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
                probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=None,
                exit_at=_ts(bars_h1[j]).isoformat(), probe_entry=probe_entry, add_entry=None,
                zone_low=low, zone_high=high, stop=stop, target=target,
                swept_liquidity=liquidity, recovery_level=recovery, sweep_index=sweep_index,
                recovery_index=None, exit_price=exit_price, pnl_price_weighted=pnl,
                risk_price_weighted=PROBE_FRACTION * probe_risk,
                exposure_fraction=PROBE_FRACTION, bars_held=j-entry_index+1,
                exit_reason="STOP_FIRST_PROBE" if stop_hit else "TARGET_PROBE",
                zone_id=candidate.get("zone_id"), timeframe=str(candidate.get("timeframe") or "HTF"),
                effective_score=float(candidate.get("score") or 0.0),
            )

        if sweep_index is None and _swept(direction, bar, liquidity):
            sweep_index = j
        if sweep_index is not None and _recovered(direction, float(bar.close), recovery):
            recovery_index = j
            break

    if recovery_index is None:
        exit_index = min(deadline + 1, len(bars_h1) - 1)
        exit_price = float(bars_h1[exit_index].open) if exit_index > deadline else float(bars_h1[deadline].close)
        pnl = PROBE_FRACTION * _signed(direction, exit_price, probe_entry)
        return LocalRecoveryTrade(
            variant=f"LOCAL_{recovery_mode}", direction=direction,
            signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=None,
            exit_index=exit_index, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=None,
            exit_at=_ts(bars_h1[exit_index]).isoformat(), probe_entry=probe_entry, add_entry=None,
            zone_low=low, zone_high=high, stop=stop, target=target,
            swept_liquidity=liquidity, recovery_level=recovery, sweep_index=sweep_index,
            recovery_index=None, exit_price=exit_price, pnl_price_weighted=pnl,
            risk_price_weighted=PROBE_FRACTION * probe_risk,
            exposure_fraction=PROBE_FRACTION, bars_held=exit_index-entry_index+1,
            exit_reason="NO_SWEEP_TIMEOUT_EXIT" if sweep_index is None else "NO_RECOVERY_TIMEOUT_EXIT",
            zone_id=candidate.get("zone_id"), timeframe=str(candidate.get("timeframe") or "HTF"),
            effective_score=float(candidate.get("score") or 0.0),
        )

    add_index = recovery_index + 1
    if add_index >= len(bars_h1):
        exit_price = float(bars_h1[recovery_index].close)
        pnl = PROBE_FRACTION * _signed(direction, exit_price, probe_entry)
        return LocalRecoveryTrade(
            variant=f"LOCAL_{recovery_mode}", direction=direction,
            signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=None,
            exit_index=recovery_index, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=None,
            exit_at=_close_at(bars_h1[recovery_index]).isoformat(), probe_entry=probe_entry, add_entry=None,
            zone_low=low, zone_high=high, stop=stop, target=target,
            swept_liquidity=liquidity, recovery_level=recovery, sweep_index=sweep_index,
            recovery_index=recovery_index, exit_price=exit_price, pnl_price_weighted=pnl,
            risk_price_weighted=PROBE_FRACTION * probe_risk,
            exposure_fraction=PROBE_FRACTION, bars_held=recovery_index-entry_index+1,
            exit_reason="HISTORY_END_AFTER_RECOVERY", zone_id=candidate.get("zone_id"),
            timeframe=str(candidate.get("timeframe") or "HTF"), effective_score=float(candidate.get("score") or 0.0),
        )

    add_entry = float(bars_h1[add_index].open)
    add_valid = (stop < add_entry < target) if direction == "LONG" else (stop > add_entry > target)
    if not add_valid:
        pnl = PROBE_FRACTION * _signed(direction, add_entry, probe_entry)
        return LocalRecoveryTrade(
            variant=f"LOCAL_{recovery_mode}", direction=direction,
            signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=None,
            exit_index=add_index, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=None,
            exit_at=_ts(bars_h1[add_index]).isoformat(), probe_entry=probe_entry, add_entry=None,
            zone_low=low, zone_high=high, stop=stop, target=target,
            swept_liquidity=liquidity, recovery_level=recovery, sweep_index=sweep_index,
            recovery_index=recovery_index, exit_price=add_entry, pnl_price_weighted=pnl,
            risk_price_weighted=PROBE_FRACTION * probe_risk,
            exposure_fraction=PROBE_FRACTION, bars_held=add_index-entry_index+1,
            exit_reason="ADD_GAP_INVALID_EXIT_PROBE", zone_id=candidate.get("zone_id"),
            timeframe=str(candidate.get("timeframe") or "HTF"), effective_score=float(candidate.get("score") or 0.0),
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
        return LocalRecoveryTrade(
            variant=f"LOCAL_{recovery_mode}", direction=direction,
            signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=add_index,
            exit_index=j, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=_ts(bars_h1[add_index]).isoformat(),
            exit_at=_ts(bars_h1[j]).isoformat(), probe_entry=probe_entry, add_entry=add_entry,
            zone_low=low, zone_high=high, stop=stop, target=target,
            swept_liquidity=liquidity, recovery_level=recovery, sweep_index=sweep_index,
            recovery_index=recovery_index, exit_price=exit_price, pnl_price_weighted=pnl,
            risk_price_weighted=weighted_risk, exposure_fraction=1.0, bars_held=j-entry_index+1,
            exit_reason="STOP_FIRST_AFTER_ADD" if stop_hit else "TARGET_AFTER_ADD",
            zone_id=candidate.get("zone_id"), timeframe=str(candidate.get("timeframe") or "HTF"),
            effective_score=float(candidate.get("score") or 0.0),
        )

    exit_price = float(bars_h1[last].close)
    pnl = (
        PROBE_FRACTION * _signed(direction, exit_price, probe_entry)
        + ADD_FRACTION * _signed(direction, exit_price, add_entry)
    )
    return LocalRecoveryTrade(
        variant=f"LOCAL_{recovery_mode}", direction=direction,
        signal_index=signal_index, probe_entry_index=entry_index, add_entry_index=add_index,
        exit_index=last, signal_at=_close_at(bars_h1[signal_index]).isoformat(),
        probe_entry_at=_ts(bars_h1[entry_index]).isoformat(), add_entry_at=_ts(bars_h1[add_index]).isoformat(),
        exit_at=_close_at(bars_h1[last]).isoformat(), probe_entry=probe_entry, add_entry=add_entry,
        zone_low=low, zone_high=high, stop=stop, target=target,
        swept_liquidity=liquidity, recovery_level=recovery, sweep_index=sweep_index,
        recovery_index=recovery_index, exit_price=exit_price, pnl_price_weighted=pnl,
        risk_price_weighted=weighted_risk, exposure_fraction=1.0, bars_held=last-entry_index+1,
        exit_reason="TIMEOUT_AFTER_ADD", zone_id=candidate.get("zone_id"),
        timeframe=str(candidate.get("timeframe") or "HTF"), effective_score=float(candidate.get("score") or 0.0),
    )


def _metrics(trades: list[LocalRecoveryTrade]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "win_rate": None, "fixed_price_pf": None, "expectancy_price": None}
    pnl = [trade.pnl_price_weighted for trade in trades]
    rs = [trade.pnl_price_weighted / trade.risk_price_weighted for trade in trades if trade.risk_price_weighted > 0]
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
        "r_pf": _pf(rs),
        "expectancy_r": fmean(rs),
        "net_r": sum(rs),
        "added_trades": sum(trade.add_entry_index is not None for trade in trades),
        "probe_only_trades": sum(trade.add_entry_index is None for trade in trades),
        "sweep_observed": sum(trade.sweep_index is not None for trade in trades),
        "recovery_observed": sum(trade.recovery_index is not None for trade in trades),
        "avg_exposure_fraction": fmean(trade.exposure_fraction for trade in trades),
        "avg_bars_held": fmean(trade.bars_held for trade in trades),
        "long_trades": sum(trade.direction == "LONG" for trade in trades),
        "short_trades": sum(trade.direction == "SHORT" for trade in trades),
        "cost_stress": stress,
    }


def _by_year(trades: list[LocalRecoveryTrade], bars_h1: tuple[Any, ...]) -> dict[str, Any]:
    years = sorted({_ts(bars_h1[trade.probe_entry_index]).year for trade in trades})
    return {
        str(year): _metrics([trade for trade in trades if _ts(bars_h1[trade.probe_entry_index]).year == year])
        for year in years
    }


def run_replay(bars_h1: Iterable[Any], bars_h4: Iterable[Any]) -> dict[str, Any]:
    h1 = tuple(sorted(bars_h1, key=lambda bar: _ts(bar)))
    h4 = tuple(sorted(bars_h4, key=lambda bar: _ts(bar)))
    if len(h1) < 200 or len(h4) < 30:
        raise ValueError("V400_REPLAY_INSUFFICIENT_HISTORY")

    as_of = _close_at(h1[-1])
    zones = tuple(detect_zones(h1, timeframe="H1", as_of=as_of)) + tuple(
        detect_zones(h4, timeframe="H4", as_of=as_of)
    )
    metas = build_zone_metadata(zones, h1)
    fractals = build_liquidity_fractals(h1)

    trades_by_mode: dict[str, list[LocalRecoveryTrade]] = {mode: [] for mode in RECOVERY_MODES}
    next_free: dict[str, int] = {mode: 0 for mode in RECOVERY_MODES}
    rejects: dict[str, int] = {mode: 0 for mode in RECOVERY_MODES}
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
        for mode in RECOVERY_MODES:
            if i < next_free[mode]:
                continue
            trade = resolve_local_recovery(
                h1,
                signal_index=i,
                candidate=candidate,
                recovery_mode=mode,
            )
            if trade is None:
                rejects[mode] += 1
                continue
            trades_by_mode[mode].append(trade)
            next_free[mode] = trade.exit_index + 1

    variants: dict[str, Any] = {}
    gates: dict[str, Any] = {}
    for mode in RECOVERY_MODES:
        name = f"LOCAL_{mode}"
        trades = trades_by_mode[mode]
        metrics = _metrics(trades)
        by_year = _by_year(trades, h1)
        variants[name] = {
            "metrics": metrics,
            "by_year": by_year,
            "trades": [asdict(trade) for trade in trades],
        }
        pf = metrics.get("fixed_price_pf")
        exp = metrics.get("expectancy_price")
        yearly_pfs = [row.get("fixed_price_pf") for row in by_year.values()]
        stress_pf = metrics.get("cost_stress", {}).get("cost_0.50", {}).get("fixed_price_pf")
        gates[name] = {
            "fixed_price_pf_gte_1_5": pf is not None and pf != inf and float(pf) >= 1.5,
            "expectancy_price_positive": exp is not None and float(exp) > 0,
            "each_year_pf_gte_1_0": bool(yearly_pfs) and all(
                value is not None and (value == inf or float(value) >= 1.0) for value in yearly_pfs
            ),
            "cost_0_50_pf_gte_1_2": stress_pf is not None and (stress_pf == inf or float(stress_pf) >= 1.2),
        }

    return {
        "contract": CONTRACT,
        "engine_contract": "XAU_RIZAN_AFIQ_CHALLENGER_V395",
        "period": {"start": _ts(h1[0]).isoformat(), "end": _close_at(h1[-1]).isoformat()},
        "bars": {"H1": len(h1), "H4": len(h4)},
        "causality": {
            "signal": "EARLY_TAKE_RISK_AT_H1_CLOSE",
            "liquidity_pool": "KNOWN_AND_UNSWEPT_H1_FRACTAL_AT_SIGNAL",
            "probe_fill": "NEXT_H1_OPEN",
            "sweep": "ADVERSE_INTRABAR_TOUCH_OF_FROZEN_POOL",
            "recovery": "LATER_H1_CLOSE_THROUGH_PREDECLARED_LOCAL_LEVEL",
            "add_fill": "NEXT_H1_OPEN_AFTER_RECOVERY",
            "failed_recovery_exit": "NEXT_H1_OPEN_AFTER_8_BAR_WINDOW",
            "same_bar_conflict": "STOP_FIRST",
            "future_outcomes_as_inputs": False,
        },
        "sizing_model": {
            "probe_fraction": PROBE_FRACTION,
            "add_fraction": ADD_FRACTION,
            "max_total_fraction": 1.0,
        },
        "recovery_modes": list(RECOVERY_MODES),
        "recovery_window_h1": RECOVERY_WINDOW_H1,
        "state_counts": state_counts,
        "reject_counts": rejects,
        "variants": variants,
        "numeric_gates": gates,
        "promotion_eligible": False,
        "promotion_blockers": [
            "HISTORICAL_SPREAD_AND_COMMISSION_NOT_OBSERVED",
            "CAUSAL_EVENT_BLACKOUT_ARCHIVE_NOT_APPLIED",
            "LONGER_HISTORY_REQUIRED",
            "RECOVERY_MODE_SELECTION_REQUIRES_OUT_OF_SAMPLE_CONFIRMATION",
        ],
    }
