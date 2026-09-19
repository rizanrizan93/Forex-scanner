from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import (
    TournamentMetrics,
    TournamentTrade,
    compute_metrics,
    walk_forward,
)
from .models import Bar, ensure_utc
from .research_xau_d1_tsmom_crossfeed_v1 import _ema, resample_h1_to_daily
from .research_xau_m15_continuation_tournament import (
    DEVELOPMENT_FRACTION,
    FINAL_OOS_EXPECTANCY_R_MIN,
    FINAL_OOS_PROFIT_FACTOR_MIN,
    FINAL_OOS_WIN_RATE_MIN,
    MIN_HOLDOUT_TRADES,
    _indicator_series,
    _metrics_pass,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "XAU_ASIA_CROSS_SESSION_V12"
ARTIFACT_CONTRACT = "XAU_ASIA_CROSS_SESSION_V12_EVIDENCE_1"
SYMBOL = "XAUUSD"
PIP_SIZE = 0.01
H1_SECONDS = 3600
STOP_ATR = 1.50
ASIA_ENTRY_HOUR = 22
ASIA_EXIT_HOUR = 7
US_OPEN_HOUR = 12
US_LAST_BAR_HOUR = 20
MIN_DEVELOPMENT_TRADES = 130


@dataclass(frozen=True, slots=True)
class CrossSessionVariant:
    variant_id: str
    rule: str
    selection_eligible: bool = True


VARIANTS = (
    CrossSessionVariant("XAU_V12_US_SIGN_SYMMETRIC_CONTROL", "US_SIGN_SYMMETRIC", False),
    CrossSessionVariant("XAU_V12_D1_MATCH_US_MOM", "D1_MATCH_US_MOM"),
    CrossSessionVariant("XAU_V12_D1_REGIME_US_FADE", "D1_REGIME_US_FADE"),
    CrossSessionVariant("XAU_V12_D1_LONG_ANY_ASIA", "D1_LONG_ANY"),
    CrossSessionVariant("XAU_V12_D1_LONG_US_NEG_FADE", "D1_LONG_US_NEG"),
    CrossSessionVariant("XAU_V12_D1_LONG_US_POS_MOM", "D1_LONG_US_POS"),
    CrossSessionVariant("XAU_V12_D1_SHORT_US_POS_FADE", "D1_SHORT_US_POS"),
    CrossSessionVariant("XAU_V12_D1_SHORT_US_NEG_MOM", "D1_SHORT_US_NEG"),
)


def _validate_h1(bars: Sequence[Bar]) -> tuple[Bar, ...]:
    rows = tuple(sorted(bars, key=lambda row: ensure_utc(row.timestamp)))
    if not rows:
        raise ValueError("XAU_V12_H1_EMPTY")
    if any(row.symbol.upper() != SYMBOL or row.timeframe.upper() != "H1" for row in rows):
        raise ValueError("XAU_V12_REQUIRES_XAUUSD_H1")
    return rows


def _d1_bias_context(rows: Sequence[Bar]):
    daily = resample_h1_to_daily(tuple(rows), boundary_hour_utc=0)
    days = [row.day for row in daily]
    ema200 = _ema([float(row.close) for row in daily], 200)
    return daily, days, ema200


def _d1_bias(daily, days, ema200, entry_day) -> str | None:
    idx = bisect_left(days, entry_day) - 1
    if idx < 199 or idx < 60:
        return None
    ema = ema200[idx]
    if ema is None:
        return None
    close = float(daily[idx].close)
    prior = float(daily[idx - 60].close)
    if prior <= 0:
        return None
    ret60 = close / prior - 1.0
    if close > float(ema) and ret60 > 0:
        return "LONG"
    if close < float(ema) and ret60 < 0:
        return "SHORT"
    return None


def _session_maps(rows: Sequence[Bar]):
    by_stamp = {ensure_utc(row.timestamp): row for row in rows}
    by_day: dict[Any, dict[int, Bar]] = {}
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        by_day.setdefault(stamp.date(), {})[stamp.hour] = row
    return by_stamp, by_day


def _direction(rule: str, *, d1_bias: str | None, us_return: float) -> str | None:
    us_sign = "LONG" if us_return > 0 else "SHORT" if us_return < 0 else None
    if rule == "US_SIGN_SYMMETRIC":
        return us_sign
    if rule == "D1_MATCH_US_MOM":
        return d1_bias if d1_bias is not None and d1_bias == us_sign else None
    if rule == "D1_REGIME_US_FADE":
        if d1_bias == "LONG" and us_return < 0:
            return "LONG"
        if d1_bias == "SHORT" and us_return > 0:
            return "SHORT"
        return None
    if rule == "D1_LONG_ANY":
        return "LONG" if d1_bias == "LONG" else None
    if rule == "D1_LONG_US_NEG":
        return "LONG" if d1_bias == "LONG" and us_return < 0 else None
    if rule == "D1_LONG_US_POS":
        return "LONG" if d1_bias == "LONG" and us_return > 0 else None
    if rule == "D1_SHORT_US_POS":
        return "SHORT" if d1_bias == "SHORT" and us_return > 0 else None
    if rule == "D1_SHORT_US_NEG":
        return "SHORT" if d1_bias == "SHORT" and us_return < 0 else None
    raise ValueError(f"XAU_V12_RULE_INVALID:{rule}")


def _cost_r(*, risk_pips: float, bars_held: int, costs: M15ResearchCosts) -> float:
    elapsed_days = max(0, bars_held) * H1_SECONDS / 86400.0
    total_pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total_pips / risk_pips


def simulate_variant(
    bars: Sequence[Bar],
    *,
    variant: CrossSessionVariant,
    costs: M15ResearchCosts,
) -> tuple[TournamentTrade, ...]:
    rows = _validate_h1(bars)
    indicators = _indicator_series(rows)
    daily, daily_days, daily_ema200 = _d1_bias_context(rows)
    _, by_day = _session_maps(rows)
    index_by_stamp = {ensure_utc(row.timestamp): i for i, row in enumerate(rows)}
    output: list[TournamentTrade] = []

    for day in sorted(by_day):
        hours = by_day[day]
        if ASIA_ENTRY_HOUR not in hours or US_OPEN_HOUR not in hours or US_LAST_BAR_HOUR not in hours:
            continue
        entry_bar = hours[ASIA_ENTRY_HOUR]
        entry_stamp = ensure_utc(entry_bar.timestamp)
        entry_index = index_by_stamp[entry_stamp]
        if entry_index < 220:
            continue

        us_open = float(hours[US_OPEN_HOUR].open)
        us_close = float(hours[US_LAST_BAR_HOUR].close)
        if us_open <= 0:
            continue
        us_return = us_close / us_open - 1.0
        d1_bias = _d1_bias(daily, daily_days, daily_ema200, day)
        direction = _direction(variant.rule, d1_bias=d1_bias, us_return=us_return)
        if direction is None:
            continue

        atr_raw = indicators["atr"][entry_index - 1]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        risk = STOP_ATR * atr
        if not isfinite(risk) or risk <= 0:
            continue
        entry = float(entry_bar.open)
        stop = entry - risk if direction == "LONG" else entry + risk
        risk_pips = risk / PIP_SIZE

        # Asia session is 22:00-07:00 UTC. Exit at the close of the 06:00 bar.
        last_index = None
        for idx in range(entry_index, min(len(rows), entry_index + 12)):
            stamp = ensure_utc(rows[idx].timestamp)
            if stamp.date() > day and stamp.hour == 6:
                last_index = idx
                break
        if last_index is None:
            continue

        trade = None
        inspected = 0
        for idx in range(entry_index, last_index + 1):
            row = rows[idx]
            inspected += 1
            stop_hit = float(row.low) <= stop if direction == "LONG" else float(row.high) >= stop
            cost_r = _cost_r(risk_pips=risk_pips, bars_held=inspected, costs=costs)
            if stop_hit:
                gross_r = -1.0
                trade = TournamentTrade(
                    variant.variant_id,
                    SYMBOL,
                    direction,
                    ensure_utc(hours[US_LAST_BAR_HOUR].timestamp),
                    entry_stamp,
                    ensure_utc(row.timestamp),
                    entry_index - 1,
                    idx,
                    entry,
                    stop,
                    atr,
                    stop,
                    float("nan"),
                    gross_r,
                    cost_r,
                    gross_r - cost_r,
                    inspected,
                    "STOP_HIT",
                )
                break

        if trade is None:
            exit_row = rows[last_index]
            exit_price = float(exit_row.close)
            gross_r = (
                (exit_price - entry) / risk
                if direction == "LONG"
                else (entry - exit_price) / risk
            )
            cost_r = _cost_r(
                risk_pips=risk_pips,
                bars_held=last_index - entry_index + 1,
                costs=costs,
            )
            trade = TournamentTrade(
                variant.variant_id,
                SYMBOL,
                direction,
                ensure_utc(hours[US_LAST_BAR_HOUR].timestamp),
                entry_stamp,
                ensure_utc(exit_row.timestamp),
                entry_index - 1,
                last_index,
                entry,
                exit_price,
                atr,
                stop,
                float("nan"),
                gross_r,
                cost_r,
                gross_r - cost_r,
                last_index - entry_index + 1,
                "ASIA_CLOSE",
            )
        output.append(trade)
    return tuple(output)


def _coverage(rows: Sequence[Bar], trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    days = sorted({ensure_utc(row.timestamp).date() for row in rows})
    trade_days = sorted({ensure_utc(t.entry_at).date() for t in trades})
    return {
        "bar_days": len(days),
        "days_with_trade": len(trade_days),
        "signal_day_coverage": len(trade_days) / len(days) if days else 0.0,
        "trades": len(trades),
    }


def _final_oos_pass(metrics: TournamentMetrics) -> bool:
    return bool(
        metrics.completed_trades >= MIN_HOLDOUT_TRADES
        and metrics.win_rate is not None
        and metrics.win_rate >= FINAL_OOS_WIN_RATE_MIN
        and metrics.profit_factor is not None
        and metrics.profit_factor >= FINAL_OOS_PROFIT_FACTOR_MIN
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= FINAL_OOS_EXPECTANCY_R_MIN
    )


def evaluate_asia_cross_session_v12(
    bars: Sequence[Bar],
    *,
    costs: M15ResearchCosts,
    stressed_costs: M15ResearchCosts,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _validate_h1(bars)
    split_index = max(5000, min(len(rows) - 1, int(len(rows) * DEVELOPMENT_FRACTION)))
    dev_rows = rows[:split_index]
    holdout_rows = rows[split_index:]
    evaluations = []
    base_sets = {}
    stress_sets = {}

    for variant in VARIANTS:
        base = simulate_variant(rows, variant=variant, costs=costs)
        stress = simulate_variant(rows, variant=variant, costs=stressed_costs)
        base_sets[variant.variant_id] = base
        stress_sets[variant.variant_id] = stress
        dev = tuple(t for t in base if t.signal_index < split_index and t.exit_index < split_index)
        dev_stress = tuple(t for t in stress if t.signal_index < split_index and t.exit_index < split_index)
        metrics = compute_metrics(dev)
        stress_metrics = compute_metrics(dev_stress)
        folds, pass_fraction, wf_passed = walk_forward(dev, validation_cfg["walk_forward"])
        stress_passed = _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
        development_passed = bool(
            metrics.completed_trades >= MIN_DEVELOPMENT_TRADES
            and wf_passed
            and stress_passed
        )
        evaluations.append({
            "variant": asdict(variant),
            "development": metrics.payload(),
            "stressed_development": stress_metrics.payload(),
            "walk_forward": {
                "folds": [
                    {
                        "fold": fold.fold,
                        "train_trades": fold.train_trades,
                        "test_trades": fold.test_trades,
                        "passed": fold.passed,
                        "test_metrics": fold.test_metrics.payload(),
                    }
                    for fold in folds
                ],
                "pass_fraction": pass_fraction,
                "passed": wf_passed,
            },
            "stress_passed": stress_passed,
            "development_passed": development_passed,
            "development_coverage": _coverage(dev_rows, dev),
        })

    eligible = [
        row for row in evaluations
        if row["development_passed"] and bool(row["variant"]["selection_eligible"])
    ]
    eligible.sort(
        key=lambda row: (
            float(row["walk_forward"]["pass_fraction"]),
            float(row["stressed_development"].get("expectancy_r") or -999.0),
            float(row["stressed_development"].get("profit_factor") or -999.0),
        ),
        reverse=True,
    )
    selected = eligible[0] if eligible else None
    holdout = None
    promotion_eligible = False

    if selected is not None:
        variant_id = str(selected["variant"]["variant_id"])
        base = tuple(
            t for t in base_sets[variant_id]
            if t.signal_index >= split_index and t.exit_index < len(rows)
        )
        stress = tuple(
            t for t in stress_sets[variant_id]
            if t.signal_index >= split_index and t.exit_index < len(rows)
        )
        base_metrics = compute_metrics(base)
        stress_metrics = compute_metrics(stress)
        promotion_eligible = bool(
            _final_oos_pass(base_metrics)
            and _metrics_pass(stress_metrics, validation_cfg["stress_acceptance"])
        )
        holdout = {
            "variant_id": variant_id,
            "base": base_metrics.payload(),
            "stressed": stress_metrics.payload(),
            "coverage": _coverage(holdout_rows, base),
            "passed": promotion_eligible,
        }

    return {
        "research_version": RESEARCH_VERSION,
        "symbol": SYMBOL,
        "input_timeframe": "H1",
        "h1_bars": len(rows),
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout": holdout,
        "promotion_eligible": promotion_eligible,
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "selection_note": (
            "V12 freezes cross-session Asia rules before holdout access. "
            "D1 TSMOM regime is inherited unchanged from prior independent evidence."
        ),
    }
