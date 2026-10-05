from __future__ import annotations

"""V401 causal local-confirmation entry replay.

V400 showed the first material improvement in the AFIQ reconstruction: after
requiring an *unswept adverse-side H1 liquidity sweep*, recovery through the HTF
zone midpoint approached breakeven gross PF, while probe losses still dragged
the combined result down. V401 therefore removes the anticipatory probe from
the experiment and asks a clean question: does the local sweep+recovery event
itself have enough edge to justify entry?

No position exists before confirmation. A wick through structural invalidation
before entry is not automatically fatal; the setup is cancelled only after two
H1 acceptance closes beyond the frozen structural boundary. If the frozen
terminal target trades before entry, the setup is also cancelled as consumed.
After a valid recovery close, entry is the next H1 open with STOP_FIRST risk.

Three predeclared structural recovery levels are retained to avoid tuning a
numeric threshold: swept liquidity, zone midpoint, and zone proximal edge.
Research/shadow only; no DEMO/LIVE order authority.
"""

from dataclasses import asdict, dataclass
from math import inf
from statistics import fmean
from typing import Any, Iterable

from .xau_afiq_challenger_v395 import MIN_RR, evaluate_afiq_challenger_v395
from .xau_afiq_local_sweep_recovery_v400 import (
    RECOVERY_MODES,
    RECOVERY_WINDOW_H1,
    _recovered,
    _recovery_level,
    _select_liquidity,
    _swept,
)
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

CONTRACT = "XAU_RIZAN_AFIQ_LOCAL_CONFIRM_ENTRY_V401"
MAX_HOLD_H1_BARS = 96


@dataclass(frozen=True, slots=True)
class ConfirmEntryTrade:
    variant: str
    direction: str
    signal_index: int
    sweep_index: int
    recovery_index: int
    entry_index: int
    exit_index: int
    signal_at: str
    recovery_at: str
    entry_at: str
    exit_at: str
    entry: float
    zone_low: float
    zone_high: float
    stop: float
    target: float
    swept_liquidity: float
    recovery_level: float
    exit_price: float
    pnl_price: float
    risk_price: float
    r_multiple: float
    bars_held: int
    exit_reason: str
    zone_id: str | None
    timeframe: str
    effective_score: float


def _signed(direction: str, exit_price: float, entry: float) -> float:
    return exit_price - entry if direction == "LONG" else entry - exit_price


def _target_consumed(direction: str, bar: Any, target: float) -> bool:
    return float(bar.high) >= target if direction == "LONG" else float(bar.low) <= target


def _beyond(direction: str, close: float, stop: float) -> bool:
    return close < stop if direction == "LONG" else close > stop


def resolve_confirm_entry(
    bars_h1: tuple[Any, ...],
    *,
    signal_index: int,
    candidate: dict[str, Any],
    recovery_mode: str,
    recovery_window: int = RECOVERY_WINDOW_H1,
    max_hold: int = MAX_HOLD_H1_BARS,
) -> ConfirmEntryTrade | None:
    if recovery_mode not in RECOVERY_MODES:
        raise ValueError(recovery_mode)
    direction = str(candidate.get("direction") or "")
    if direction not in {"LONG", "SHORT"}:
        return None
    first_monitor = signal_index + 1
    if first_monitor >= len(bars_h1):
        return None

    low = float(candidate["low"])
    high = float(candidate["high"])
    stop = float(candidate["structural_invalidation"])
    # Liquidity is selected using the next open only as a causal reference price;
    # the pool itself must already have been known and unswept at the signal.
    reference_open = float(bars_h1[first_monitor].open)
    liquidity = _select_liquidity(candidate, bars_h1, signal_index, reference_open, stop)
    if liquidity is None:
        return None
    recovery = _recovery_level(recovery_mode, direction, low, high, liquidity)

    # Freeze a pre-entry target from the signal geometry. It only needs to be
    # beyond the recovery trigger here; actual RR is rechecked at the fill.
    raw_targets = [float(value) for value in candidate.get("targets") or []]
    if direction == "LONG":
        valid_targets = [value for value in raw_targets if value > recovery]
        target = min(valid_targets) if valid_targets else None
        if target is None or not (stop < liquidity <= recovery < target):
            return None
    else:
        valid_targets = [value for value in raw_targets if value < recovery]
        target = max(valid_targets) if valid_targets else None
        if target is None or not (stop > liquidity >= recovery > target):
            return None

    deadline = min(len(bars_h1) - 2, first_monitor + recovery_window - 1)
    sweep_index: int | None = None
    recovery_index: int | None = None
    invalid_streak = 0
    for j in range(first_monitor, deadline + 1):
        bar = bars_h1[j]
        close = float(bar.close)
        invalid_streak = invalid_streak + 1 if _beyond(direction, close, stop) else 0
        if invalid_streak >= 2:
            return None
        if _target_consumed(direction, bar, target):
            return None
        if sweep_index is None and _swept(direction, bar, liquidity):
            sweep_index = j
        if sweep_index is not None and _recovered(direction, close, recovery):
            recovery_index = j
            break
    if sweep_index is None or recovery_index is None:
        return None

    entry_index = recovery_index + 1
    if entry_index >= len(bars_h1):
        return None
    entry = float(bars_h1[entry_index].open)
    risk = entry - stop if direction == "LONG" else stop - entry
    reward = target - entry if direction == "LONG" else entry - target
    if risk <= 0 or reward <= 0:
        return None
    if risk < _minimum_risk(entry, low, high) or reward / risk < MIN_RR:
        return None

    last = min(len(bars_h1) - 1, entry_index + max_hold - 1)
    for j in range(entry_index, last + 1):
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
        pnl = _signed(direction, exit_price, entry)
        return ConfirmEntryTrade(
            variant=f"CONFIRM_{recovery_mode}", direction=direction,
            signal_index=signal_index, sweep_index=sweep_index, recovery_index=recovery_index,
            entry_index=entry_index, exit_index=j,
            signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            recovery_at=_close_at(bars_h1[recovery_index]).isoformat(),
            entry_at=_ts(bars_h1[entry_index]).isoformat(), exit_at=_ts(bars_h1[j]).isoformat(),
            entry=entry, zone_low=low, zone_high=high, stop=stop, target=target,
            swept_liquidity=liquidity, recovery_level=recovery, exit_price=exit_price,
            pnl_price=pnl, risk_price=risk, r_multiple=pnl/risk,
            bars_held=j-entry_index+1, exit_reason="STOP_FIRST" if stop_hit else "TARGET",
            zone_id=candidate.get("zone_id"), timeframe=str(candidate.get("timeframe") or "HTF"),
            effective_score=float(candidate.get("score") or 0.0),
        )

    exit_price = float(bars_h1[last].close)
    pnl = _signed(direction, exit_price, entry)
    return ConfirmEntryTrade(
        variant=f"CONFIRM_{recovery_mode}", direction=direction,
        signal_index=signal_index, sweep_index=sweep_index, recovery_index=recovery_index,
        entry_index=entry_index, exit_index=last,
        signal_at=_close_at(bars_h1[signal_index]).isoformat(),
        recovery_at=_close_at(bars_h1[recovery_index]).isoformat(),
        entry_at=_ts(bars_h1[entry_index]).isoformat(), exit_at=_close_at(bars_h1[last]).isoformat(),
        entry=entry, zone_low=low, zone_high=high, stop=stop, target=target,
        swept_liquidity=liquidity, recovery_level=recovery, exit_price=exit_price,
        pnl_price=pnl, risk_price=risk, r_multiple=pnl/risk,
        bars_held=last-entry_index+1, exit_reason="TIMEOUT",
        zone_id=candidate.get("zone_id"), timeframe=str(candidate.get("timeframe") or "HTF"),
        effective_score=float(candidate.get("score") or 0.0),
    )


def _metrics(trades: list[ConfirmEntryTrade]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0, "win_rate": None, "fixed_price_pf": None, "expectancy_price": None}
    pnl = [trade.pnl_price for trade in trades]
    rs = [trade.r_multiple for trade in trades]
    stress: dict[str, Any] = {}
    for cost in COST_STRESS_PRICE_UNITS:
        adjusted = [value - cost for value in pnl]
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
        "avg_risk_price": fmean(trade.risk_price for trade in trades),
        "avg_bars_held": fmean(trade.bars_held for trade in trades),
        "long_trades": sum(trade.direction == "LONG" for trade in trades),
        "short_trades": sum(trade.direction == "SHORT" for trade in trades),
        "targets": sum(trade.exit_reason == "TARGET" for trade in trades),
        "stops": sum(trade.exit_reason == "STOP_FIRST" for trade in trades),
        "timeouts": sum(trade.exit_reason == "TIMEOUT" for trade in trades),
        "cost_stress": stress,
    }


def _by_year(trades: list[ConfirmEntryTrade], bars_h1: tuple[Any, ...]) -> dict[str, Any]:
    years = sorted({_ts(bars_h1[trade.entry_index]).year for trade in trades})
    return {
        str(year): _metrics([trade for trade in trades if _ts(bars_h1[trade.entry_index]).year == year])
        for year in years
    }


def run_replay(bars_h1: Iterable[Any], bars_h4: Iterable[Any]) -> dict[str, Any]:
    h1 = tuple(sorted(bars_h1, key=lambda bar: _ts(bar)))
    h4 = tuple(sorted(bars_h4, key=lambda bar: _ts(bar)))
    if len(h1) < 200 or len(h4) < 30:
        raise ValueError("V401_REPLAY_INSUFFICIENT_HISTORY")

    as_of = _close_at(h1[-1])
    zones = tuple(detect_zones(h1, timeframe="H1", as_of=as_of)) + tuple(
        detect_zones(h4, timeframe="H4", as_of=as_of)
    )
    metas = build_zone_metadata(zones, h1)
    fractals = build_liquidity_fractals(h1)

    trades_by_mode: dict[str, list[ConfirmEntryTrade]] = {mode: [] for mode in RECOVERY_MODES}
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
            trade = resolve_confirm_entry(
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
        name = f"CONFIRM_{mode}"
        trades = trades_by_mode[mode]
        metrics = _metrics(trades)
        by_year = _by_year(trades, h1)
        variants[name] = {"metrics": metrics, "by_year": by_year, "trades": [asdict(trade) for trade in trades]}
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
            "pre_entry_position": "NONE",
            "liquidity_pool": "KNOWN_AND_UNSWEPT_H1_FRACTAL_AT_SIGNAL",
            "sweep": "ADVERSE_INTRABAR_TOUCH_OF_FROZEN_POOL",
            "setup_invalidation_before_entry": "TWO_H1_ACCEPTANCE_CLOSES_BEYOND_FROZEN_STOP",
            "recovery": "H1_CLOSE_THROUGH_PREDECLARED_LOCAL_LEVEL",
            "fill": "NEXT_H1_OPEN_AFTER_RECOVERY",
            "post_entry_same_bar_conflict": "STOP_FIRST",
            "future_outcomes_as_inputs": False,
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
