from __future__ import annotations

"""V397 risk-realism replay for the V395 AFIQ-pattern challenger.

V396 proved the signal can look strong when every trade is normalized by the
raw structural distance. That distance can be only a few cents in XAUUSD,
which makes R-multiples explode and is not representative of the project's
fixed 0.01-lot child execution. V397 therefore evaluates causal signals with:

* STOP_FIRST execution at the structural stop;
* a causal minimum executable risk-distance gate;
* fixed-price-unit PnL / profit factor as the primary metric;
* transaction-cost stress tests; and
* a separate confirmation-entry path armed only by a prior EARLY signal.

No DEMO or LIVE order authority is granted by this module.
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
from .xau_sd_liquidity_engine_v342_legacy import detect_zones

CONTRACT = "XAU_RIZAN_AFIQ_RISK_REALISM_REPLAY_V397"
MAX_HOLD_H1_BARS = 96
CONFIRM_ARM_MAX_BARS = 48
MIN_RISK_ENTRY_FRACTION = 0.0005
MIN_RISK_ZONE_WIDTH_MULT = 0.50
MIN_RISK_ABSOLUTE = 0.75
COST_STRESS_PRICE_UNITS = (0.0, 0.25, 0.50, 1.00)


@dataclass(frozen=True, slots=True)
class ReplayTrade397:
    variant: str
    direction: str
    signal_index: int
    entry_index: int
    exit_index: int
    signal_at: str
    entry_at: str
    exit_at: str
    entry: float
    raw_structural_invalidation: float
    stop: float
    target: float
    exit_price: float
    pnl_price: float
    r_multiple: float
    risk_price: float
    reward_price: float
    rr_initial: float
    min_risk_required: float
    bars_held: int
    exit_reason: str
    zone_id: str | None
    timeframe: str
    effective_score: float


def _f(value: Any) -> float:
    return float(value)


def _valid_target(direction: str, entry: float, targets: Iterable[Any]) -> float | None:
    values = [float(value) for value in targets]
    if direction == "LONG":
        valid = [value for value in values if value > entry]
        return min(valid) if valid else None
    valid = [value for value in values if value < entry]
    return max(valid) if valid else None


def _minimum_risk(entry: float, low: float, high: float) -> float:
    width = max(high - low, 0.01)
    return max(
        MIN_RISK_ABSOLUTE,
        MIN_RISK_ENTRY_FRACTION * entry,
        MIN_RISK_ZONE_WIDTH_MULT * width,
    )


def resolve_stop_first(
    bars_h1: tuple[Any, ...],
    *,
    signal_index: int,
    candidate: dict[str, Any],
    variant: str,
    require_entry_in_zone: bool,
    max_hold: int = MAX_HOLD_H1_BARS,
) -> ReplayTrade397 | None:
    entry_index = signal_index + 1
    if entry_index >= len(bars_h1):
        return None

    direction = str(candidate.get("direction") or "")
    if direction not in {"LONG", "SHORT"}:
        return None
    entry = _f(bars_h1[entry_index].open)
    raw_stop = float(candidate["structural_invalidation"])
    target = _valid_target(direction, entry, candidate.get("targets") or [])
    if target is None:
        return None

    low = float(candidate["low"])
    high = float(candidate["high"])
    if require_entry_in_zone:
        tolerance = 0.25 * max(high - low, 0.01)
        if entry < low - tolerance or entry > high + tolerance:
            return None

    raw_risk = entry - raw_stop if direction == "LONG" else raw_stop - entry
    reward = target - entry if direction == "LONG" else entry - target
    if raw_risk <= 0 or reward <= 0:
        return None

    min_risk = _minimum_risk(entry, low, high)
    if raw_risk < min_risk:
        return None
    if reward / raw_risk < MIN_RR:
        return None

    stop = raw_stop
    risk = raw_risk
    last = min(len(bars_h1) - 1, entry_index + max_hold - 1)
    for j in range(entry_index, last + 1):
        bar = bars_h1[j]
        if direction == "LONG":
            stop_hit = float(bar.low) <= stop
            target_hit = float(bar.high) >= target
        else:
            stop_hit = float(bar.high) >= stop
            target_hit = float(bar.low) <= target

        if stop_hit:
            exit_price = stop
            pnl = -risk
            reason = "STOP_FIRST"
        elif target_hit:
            exit_price = target
            pnl = reward
            reason = "TARGET"
        else:
            continue
        return ReplayTrade397(
            variant=variant,
            direction=direction,
            signal_index=signal_index,
            entry_index=entry_index,
            exit_index=j,
            signal_at=_close_at(bars_h1[signal_index]).isoformat(),
            entry_at=_ts(bars_h1[entry_index]).isoformat(),
            exit_at=_ts(bars_h1[j]).isoformat(),
            entry=entry,
            raw_structural_invalidation=raw_stop,
            stop=stop,
            target=target,
            exit_price=exit_price,
            pnl_price=pnl,
            r_multiple=pnl / risk,
            risk_price=risk,
            reward_price=reward,
            rr_initial=reward / risk,
            min_risk_required=min_risk,
            bars_held=j - entry_index + 1,
            exit_reason=reason,
            zone_id=candidate.get("zone_id"),
            timeframe=str(candidate.get("timeframe") or "HTF"),
            effective_score=float(candidate.get("score") or 0.0),
        )

    exit_price = float(bars_h1[last].close)
    pnl = exit_price - entry if direction == "LONG" else entry - exit_price
    return ReplayTrade397(
        variant=variant,
        direction=direction,
        signal_index=signal_index,
        entry_index=entry_index,
        exit_index=last,
        signal_at=_close_at(bars_h1[signal_index]).isoformat(),
        entry_at=_ts(bars_h1[entry_index]).isoformat(),
        exit_at=_close_at(bars_h1[last]).isoformat(),
        entry=entry,
        raw_structural_invalidation=raw_stop,
        stop=stop,
        target=target,
        exit_price=exit_price,
        pnl_price=pnl,
        r_multiple=pnl / risk,
        risk_price=risk,
        reward_price=reward,
        rr_initial=reward / risk,
        min_risk_required=min_risk,
        bars_held=last - entry_index + 1,
        exit_reason="TIMEOUT",
        zone_id=candidate.get("zone_id"),
        timeframe=str(candidate.get("timeframe") or "HTF"),
        effective_score=float(candidate.get("score") or 0.0),
    )


def _pf(values: list[float]) -> float | None:
    positives = sum(value for value in values if value > 0)
    negatives = -sum(value for value in values if value < 0)
    if negatives == 0:
        return inf if positives > 0 else None
    return positives / negatives


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _metrics(trades: list[ReplayTrade397]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "win_rate": None,
            "fixed_price_pf": None,
            "expectancy_price": None,
            "r_pf": None,
            "expectancy_r": None,
            "max_drawdown_price": None,
        }
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
        "max_drawdown_r": _max_drawdown(rs),
        "avg_risk_price": fmean(trade.risk_price for trade in trades),
        "avg_reward_price": fmean(trade.reward_price for trade in trades),
        "avg_rr_initial": fmean(trade.rr_initial for trade in trades),
        "avg_bars_held": fmean(trade.bars_held for trade in trades),
        "targets": sum(trade.exit_reason == "TARGET" for trade in trades),
        "stops": sum(trade.exit_reason == "STOP_FIRST" for trade in trades),
        "timeouts": sum(trade.exit_reason == "TIMEOUT" for trade in trades),
        "long_trades": sum(trade.direction == "LONG" for trade in trades),
        "short_trades": sum(trade.direction == "SHORT" for trade in trades),
        "cost_stress": stress,
    }


def _year_metrics(trades: list[ReplayTrade397], bars_h1: tuple[Any, ...]) -> dict[str, Any]:
    years = sorted({_ts(bars_h1[trade.entry_index]).year for trade in trades})
    return {
        str(year): _metrics(
            [trade for trade in trades if _ts(bars_h1[trade.entry_index]).year == year]
        )
        for year in years
    }


def run_replay(bars_h1: Iterable[Any], bars_h4: Iterable[Any]) -> dict[str, Any]:
    h1 = tuple(sorted(bars_h1, key=lambda bar: _ts(bar)))
    h4 = tuple(sorted(bars_h4, key=lambda bar: _ts(bar)))
    if len(h1) < 200 or len(h4) < 30:
        raise ValueError("V397_REPLAY_INSUFFICIENT_HISTORY")

    as_of = _close_at(h1[-1])
    zones = tuple(detect_zones(h1, timeframe="H1", as_of=as_of)) + tuple(
        detect_zones(h4, timeframe="H4", as_of=as_of)
    )
    metas = build_zone_metadata(zones, h1)
    fractals = build_liquidity_fractals(h1)

    early: list[ReplayTrade397] = []
    confirmed: list[ReplayTrade397] = []
    next_free_early = 0
    next_free_confirmed = 0
    armed: dict[str, int] = {}
    reject_counts = {"EARLY": 0, "CONFIRMED": 0}
    state_counts: dict[str, int] = {}

    for i in range(120, len(h1) - 1):
        context = build_context(h1, metas, fractals, i)
        result = evaluate_afiq_challenger_v395(context)
        state = str(result.get("state") or "UNKNOWN")
        state_counts[state] = state_counts.get(state, 0) + 1
        candidates = list(result.get("candidates") or [])
        candidate = dict(candidates[0]) if candidates else None
        if candidate is None:
            continue
        zone_id = str(candidate.get("zone_id") or "")

        if state == "EARLY_TAKE_RISK":
            if zone_id:
                armed[zone_id] = i
            if i >= next_free_early:
                trade = resolve_stop_first(
                    h1,
                    signal_index=i,
                    candidate=candidate,
                    variant="EARLY_STOP_FIRST",
                    require_entry_in_zone=True,
                )
                if trade is None:
                    reject_counts["EARLY"] += 1
                else:
                    early.append(trade)
                    next_free_early = trade.exit_index + 1

        if state == "CONFIRMED" and zone_id and zone_id in armed:
            armed_at = armed[zone_id]
            if i - armed_at > CONFIRM_ARM_MAX_BARS:
                armed.pop(zone_id, None)
                continue
            if i >= next_free_confirmed:
                trade = resolve_stop_first(
                    h1,
                    signal_index=i,
                    candidate=candidate,
                    variant="CONFIRMED_STOP_FIRST",
                    require_entry_in_zone=False,
                )
                if trade is None:
                    reject_counts["CONFIRMED"] += 1
                else:
                    confirmed.append(trade)
                    next_free_confirmed = trade.exit_index + 1
                    armed.pop(zone_id, None)

        stale = [key for key, armed_at in armed.items() if i - armed_at > CONFIRM_ARM_MAX_BARS]
        for key in stale:
            armed.pop(key, None)

    variants = {
        "EARLY_STOP_FIRST": {
            "metrics": _metrics(early),
            "by_year": _year_metrics(early, h1),
            "trades": [asdict(trade) for trade in early],
        },
        "CONFIRMED_STOP_FIRST": {
            "metrics": _metrics(confirmed),
            "by_year": _year_metrics(confirmed, h1),
            "trades": [asdict(trade) for trade in confirmed],
        },
    }

    gates: dict[str, Any] = {}
    for name, payload in variants.items():
        metrics = payload["metrics"]
        years = payload["by_year"]
        pf = metrics.get("fixed_price_pf")
        exp = metrics.get("expectancy_price")
        yearly_pfs = [row.get("fixed_price_pf") for row in years.values()]
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
        "bars": {"H1": len(h1), "H4": len(h4)},
        "period": {"start": _ts(h1[0]).isoformat(), "end": _close_at(h1[-1]).isoformat()},
        "causality": {
            "signal_time": "H1_CLOSE",
            "fill_time": "NEXT_H1_OPEN",
            "zone_availability_enforced": True,
            "fractal_availability_enforced": True,
            "historical_outcomes_not_signal_inputs": True,
            "afiq_reference_prices_used_as_runtime_inputs": False,
            "same_bar_conflict": "STOP_FIRST",
            "confirmed_variant_requires_prior_early_arm": True,
        },
        "risk_realism": {
            "primary_metric": "FIXED_PRICE_UNIT_PNL",
            "structural_stop_widened": False,
            "min_risk_formula": "max(0.75, 0.0005*entry, 0.50*zone_width)",
            "historical_costs": "STRESS_TEST_ONLY_NOT_OBSERVED",
            "cost_stress_price_units": list(COST_STRESS_PRICE_UNITS),
        },
        "zones_detected": len(zones),
        "liquidity_fractals": len(fractals),
        "state_counts": state_counts,
        "reject_counts": reject_counts,
        "variants": variants,
        "numeric_gates": gates,
        "promotion_eligible": False,
        "promotion_blockers": [
            "HISTORICAL_SPREAD_AND_COMMISSION_NOT_OBSERVED",
            "CAUSAL_EVENT_BLACKOUT_ARCHIVE_NOT_APPLIED",
            "WALK_FORWARD_AND_LONGER_HISTORY_REQUIRED",
        ],
    }
