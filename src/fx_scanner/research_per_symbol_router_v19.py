from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from statistics import median
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    BreakoutSignal,
    BreakoutVariant,
    DEVELOPMENT_FRACTION,
    FINAL_FREQUENCY_TARGET,
    MAX_HOLD_BARS,
    STOP_BUFFER_ATR,
    _aggregate_h1,
    _daily_regime,
    _frequency,
    _h1_bias,
    _walk_forward,
    extract_signals as extract_trend_breakout,
    simulate,
)
from .research_xau_m15_continuation_tournament import _indicator_series
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "PER_SYMBOL_ROUTER_V19"
ARTIFACT_CONTRACT = "PER_SYMBOL_ROUTER_V19_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False

SYMBOLS = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD",
    "AUDUSD", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
    "AUDJPY", "CADJPY", "EURCHF", "EURAUD", "GBPAUD",
    "XAUUSD", "XTIUSD",
)

FAMILY_TREND_BREAKOUT = "TREND_BREAKOUT"
FAMILY_RANGE_SWEEP = "RANGE_SWEEP_FADE"
FAMILY_EMA_PULLBACK = "EMA_PULLBACK"
FAMILY_SESSION_BREAKOUT = "SESSION_BREAKOUT"
FAMILY_COMPRESSION_BREAKOUT = "COMPRESSION_BREAKOUT"

FAMILIES = (
    FAMILY_TREND_BREAKOUT,
    FAMILY_RANGE_SWEEP,
    FAMILY_EMA_PULLBACK,
    FAMILY_SESSION_BREAKOUT,
    FAMILY_COMPRESSION_BREAKOUT,
)

MIN_DEV_TRADES = 120
DEV_PF_MIN = 1.05
DEV_EXP_MIN = 0.02
DEV_WF_PASS_FRACTION_MIN = 0.50

HOLDOUT_PF_MIN = 1.10
HOLDOUT_EXP_MIN = 0.05
MIN_HOLDOUT_TRADES = 30

ROUTER_FINAL_FREQUENCY_TARGET = {
    "mean_trades_per_day_min": 5.0,
    "days_ge_5_fraction_min": 0.50,
}


@dataclass(frozen=True, slots=True)
class FamilySpec:
    family: str
    target_r: float
    cooldown_bars: int


SPECS = (
    FamilySpec(FAMILY_TREND_BREAKOUT, 2.00, 4),
    FamilySpec(FAMILY_RANGE_SWEEP, 1.00, 3),
    FamilySpec(FAMILY_EMA_PULLBACK, 1.25, 3),
    FamilySpec(FAMILY_SESSION_BREAKOUT, 1.50, 4),
    FamilySpec(FAMILY_COMPRESSION_BREAKOUT, 1.50, 4),
)


def _signal(
    *,
    spec: FamilySpec,
    symbol: str,
    index: int,
    row: Bar,
    direction: str,
    atr: float,
    stop: float,
) -> BreakoutSignal | None:
    risk = float(row.close) - stop if direction == "LONG" else stop - float(row.close)
    if risk < 0.40 * atr:
        return None
    return BreakoutSignal(
        variant_id=f"V19:{spec.family}",
        symbol=symbol,
        signal_index=index,
        direction=direction,
        signal_at=ensure_utc(row.timestamp),
        atr=atr,
        stop=float(stop),
        reward_r=float(spec.target_r),
    )


def _h1_state(
    *,
    signal_close,
    h1: Sequence[Bar],
    h1_closes,
    indicators,
) -> dict[str, Any] | None:
    count = bisect_right(h1_closes, signal_close)
    if count <= 0:
        return None
    i = count - 1
    if i < 60:
        return None
    keys = ("ema20", "ema50", "adx", "plus_di", "minus_di", "atr")
    vals = [indicators[k][i] for k in keys]
    if any(v is None for v in vals):
        return None
    ema20, ema50, adx, plus_di, minus_di, atr = (float(v) for v in vals)
    close = float(h1[i].close)
    trend = None
    if close > ema20 > ema50 and plus_di > minus_di:
        trend = "LONG"
    elif close < ema20 < ema50 and minus_di > plus_di:
        trend = "SHORT"
    return {
        "index": i,
        "trend": trend,
        "adx": adx,
        "atr": atr,
        "ema20": ema20,
        "ema50": ema50,
    }


def _extract_range_sweep(
    rows: Sequence[Bar],
    *,
    spec: FamilySpec,
) -> tuple[BreakoutSignal, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()
    symbol = bars[0].symbol.upper()
    ind = _indicator_series(bars)
    h1 = _aggregate_h1(bars)
    h1_ind = _indicator_series(h1)
    h1_closes = tuple(ensure_utc(x.timestamp) + timedelta(hours=1) for x in h1)
    out = []
    last_i = -10_000
    lookback = 12
    for i in range(220, len(bars) - 2):
        if i - last_i < spec.cooldown_bars:
            continue
        row = bars[i]
        stamp = ensure_utc(row.timestamp)
        atr_raw = ind["atr"][i]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        if atr <= 0:
            continue
        hstate = _h1_state(
            signal_close=stamp + timedelta(minutes=15),
            h1=h1,
            h1_closes=h1_closes,
            indicators=h1_ind,
        )
        # Mean reversion only in weak/ranging H1 conditions.
        if hstate is None or hstate["adx"] > 18.0:
            continue
        prior = bars[i - lookback:i]
        high = max(float(x.high) for x in prior)
        low = min(float(x.low) for x in prior)
        rng = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open))
        if rng <= 0 or body < 0.15 * atr:
            continue
        direction = None
        stop = None
        if (
            float(row.high) > high + 0.05 * atr
            and float(row.close) < high
            and float(row.close) < float(row.open)
            and (float(row.high) - float(row.close)) / rng >= 0.60
        ):
            direction = "SHORT"
            stop = float(row.high) + STOP_BUFFER_ATR * atr
        elif (
            float(row.low) < low - 0.05 * atr
            and float(row.close) > low
            and float(row.close) > float(row.open)
            and (float(row.close) - float(row.low)) / rng >= 0.60
        ):
            direction = "LONG"
            stop = float(row.low) - STOP_BUFFER_ATR * atr
        if direction is None:
            continue
        sig = _signal(
            spec=spec, symbol=symbol, index=i, row=row,
            direction=direction, atr=atr, stop=float(stop),
        )
        if sig is not None:
            out.append(sig)
            last_i = i
    return tuple(out)


def _extract_ema_pullback(
    rows: Sequence[Bar],
    *,
    spec: FamilySpec,
) -> tuple[BreakoutSignal, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()
    symbol = bars[0].symbol.upper()
    ind = _indicator_series(bars)
    h1 = _aggregate_h1(bars)
    h1_ind = _indicator_series(h1)
    h1_closes = tuple(ensure_utc(x.timestamp) + timedelta(hours=1) for x in h1)
    d1 = _daily_regime(bars)
    out = []
    last_i = -10_000
    for i in range(220, len(bars) - 2):
        if i - last_i < spec.cooldown_bars:
            continue
        row = bars[i]
        stamp = ensure_utc(row.timestamp)
        vals = [ind[k][i] for k in ("atr", "ema20", "ema50")]
        if any(v is None for v in vals):
            continue
        atr, ema20, ema50 = (float(v) for v in vals)
        if atr <= 0:
            continue
        hstate = _h1_state(
            signal_close=stamp + timedelta(minutes=15),
            h1=h1, h1_closes=h1_closes, indicators=h1_ind,
        )
        if hstate is None or hstate["trend"] is None or hstate["adx"] < 15.0:
            continue
        direction = hstate["trend"]
        # D1 may be neutral, but never directly opposed.
        if d1.get(stamp.date()) not in (None, direction):
            continue
        rng = float(row.high) - float(row.low)
        if rng <= 0:
            continue
        local = bars[max(0, i - 5):i + 1]
        stop = None
        if (
            direction == "LONG"
            and ema20 > ema50
            and float(row.low) <= ema20 + 0.10 * atr
            and float(row.close) > ema20
            and float(row.close) > float(row.open)
            and (float(row.close) - float(row.low)) / rng >= 0.60
        ):
            stop = min(float(x.low) for x in local) - STOP_BUFFER_ATR * atr
        elif (
            direction == "SHORT"
            and ema20 < ema50
            and float(row.high) >= ema20 - 0.10 * atr
            and float(row.close) < ema20
            and float(row.close) < float(row.open)
            and (float(row.high) - float(row.close)) / rng >= 0.60
        ):
            stop = max(float(x.high) for x in local) + STOP_BUFFER_ATR * atr
        if stop is None:
            continue
        sig = _signal(
            spec=spec, symbol=symbol, index=i, row=row,
            direction=direction, atr=atr, stop=float(stop),
        )
        if sig is not None:
            out.append(sig)
            last_i = i
    return tuple(out)


def _asia_ranges(rows: Sequence[Bar]) -> dict[Any, tuple[float, float]]:
    groups: dict[Any, list[Bar]] = {}
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        # Trading date is the date of the London session that follows the Asia range.
        if stamp.hour >= 22:
            key = (stamp + timedelta(days=1)).date()
        elif stamp.hour < 7:
            key = stamp.date()
        else:
            continue
        groups.setdefault(key, []).append(row)
    out = {}
    for day, vals in groups.items():
        if len(vals) < 20:
            continue
        out[day] = (
            max(float(x.high) for x in vals),
            min(float(x.low) for x in vals),
        )
    return out


def _extract_session_breakout(
    rows: Sequence[Bar],
    *,
    spec: FamilySpec,
) -> tuple[BreakoutSignal, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()
    symbol = bars[0].symbol.upper()
    ind = _indicator_series(bars)
    h1 = _aggregate_h1(bars)
    h1_ind = _indicator_series(h1)
    h1_closes = tuple(ensure_utc(x.timestamp) + timedelta(hours=1) for x in h1)
    ranges = _asia_ranges(bars)
    out = []
    used_days = set()
    for i in range(220, len(bars) - 2):
        row = bars[i]
        stamp = ensure_utc(row.timestamp)
        if not (7 <= stamp.hour < 11) or stamp.date() in used_days:
            continue
        ar = ranges.get(stamp.date())
        if ar is None:
            continue
        atr_raw = ind["atr"][i]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        hstate = _h1_state(
            signal_close=stamp + timedelta(minutes=15),
            h1=h1, h1_closes=h1_closes, indicators=h1_ind,
        )
        if hstate is None or hstate["trend"] is None or hstate["adx"] < 12.0:
            continue
        high, low = ar
        rng = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open))
        if rng <= 0 or body < 0.35 * atr:
            continue
        direction = None
        stop = None
        if (
            hstate["trend"] == "LONG"
            and float(row.close) > high + 0.05 * atr
            and (float(row.close) - float(row.low)) / rng >= 0.65
        ):
            direction = "LONG"
            stop = min(float(x.low) for x in bars[max(0, i - 3):i + 1]) - STOP_BUFFER_ATR * atr
        elif (
            hstate["trend"] == "SHORT"
            and float(row.close) < low - 0.05 * atr
            and (float(row.high) - float(row.close)) / rng >= 0.65
        ):
            direction = "SHORT"
            stop = max(float(x.high) for x in bars[max(0, i - 3):i + 1]) + STOP_BUFFER_ATR * atr
        if direction is None:
            continue
        sig = _signal(
            spec=spec, symbol=symbol, index=i, row=row,
            direction=direction, atr=atr, stop=float(stop),
        )
        if sig is not None:
            out.append(sig)
            used_days.add(stamp.date())
    return tuple(out)


def _extract_compression_breakout(
    rows: Sequence[Bar],
    *,
    spec: FamilySpec,
) -> tuple[BreakoutSignal, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()
    symbol = bars[0].symbol.upper()
    ind = _indicator_series(bars)
    h1 = _aggregate_h1(bars)
    h1_ind = _indicator_series(h1)
    h1_closes = tuple(ensure_utc(x.timestamp) + timedelta(hours=1) for x in h1)
    out = []
    last_i = -10_000
    for i in range(260, len(bars) - 2):
        if i - last_i < spec.cooldown_bars:
            continue
        row = bars[i]
        stamp = ensure_utc(row.timestamp)
        atr_raw = ind["atr"][i]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        atr_hist = [float(v) for v in ind["atr"][i - 80:i] if v is not None]
        if len(atr_hist) < 60:
            continue
        # Require the previous bar to be in the lower half of its recent ATR regime.
        prev_atr = ind["atr"][i - 1]
        if prev_atr is None or float(prev_atr) > median(atr_hist):
            continue
        hstate = _h1_state(
            signal_close=stamp + timedelta(minutes=15),
            h1=h1, h1_closes=h1_closes, indicators=h1_ind,
        )
        if hstate is None or hstate["trend"] is None:
            continue
        prior = bars[i - 12:i]
        upper = max(float(x.high) for x in prior)
        lower = min(float(x.low) for x in prior)
        rng = float(row.high) - float(row.low)
        body = abs(float(row.close) - float(row.open))
        if rng <= 0 or body < 0.50 * atr:
            continue
        direction = None
        stop = None
        if (
            hstate["trend"] == "LONG"
            and float(row.close) > upper
            and (float(row.close) - float(row.low)) / rng >= 0.68
        ):
            direction = "LONG"
            stop = min(float(x.low) for x in bars[i - 5:i + 1]) - STOP_BUFFER_ATR * atr
        elif (
            hstate["trend"] == "SHORT"
            and float(row.close) < lower
            and (float(row.high) - float(row.close)) / rng >= 0.68
        ):
            direction = "SHORT"
            stop = max(float(x.high) for x in bars[i - 5:i + 1]) + STOP_BUFFER_ATR * atr
        if direction is None:
            continue
        sig = _signal(
            spec=spec, symbol=symbol, index=i, row=row,
            direction=direction, atr=atr, stop=float(stop),
        )
        if sig is not None:
            out.append(sig)
            last_i = i
    return tuple(out)


def extract_family(
    rows: Sequence[Bar],
    *,
    spec: FamilySpec,
) -> tuple[BreakoutSignal, ...]:
    if spec.family == FAMILY_TREND_BREAKOUT:
        variant = BreakoutVariant(
            variant_id=f"V19:{FAMILY_TREND_BREAKOUT}",
            lookback_m15=20,
            h1_adx_min=15.0,
            require_d1_match=True,
            target_r=spec.target_r,
            body_atr_min=0.55,
            cooldown_bars=spec.cooldown_bars,
        )
        return extract_trend_breakout(rows, variant=variant)
    if spec.family == FAMILY_RANGE_SWEEP:
        return _extract_range_sweep(rows, spec=spec)
    if spec.family == FAMILY_EMA_PULLBACK:
        return _extract_ema_pullback(rows, spec=spec)
    if spec.family == FAMILY_SESSION_BREAKOUT:
        return _extract_session_breakout(rows, spec=spec)
    if spec.family == FAMILY_COMPRESSION_BREAKOUT:
        return _extract_compression_breakout(rows, spec=spec)
    raise ValueError(f"V19_UNKNOWN_FAMILY:{spec.family}")


def _candidate_pass(metrics, wf: Mapping[str, Any]) -> bool:
    return bool(
        metrics.completed_trades >= MIN_DEV_TRADES
        and metrics.profit_factor is not None
        and metrics.profit_factor >= DEV_PF_MIN
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= DEV_EXP_MIN
        and float(wf["pass_fraction"]) >= DEV_WF_PASS_FRACTION_MIN
    )


def _holdout_pass(metrics) -> bool:
    return bool(
        metrics.completed_trades >= MIN_HOLDOUT_TRADES
        and metrics.profit_factor is not None
        and metrics.profit_factor >= HOLDOUT_PF_MIN
        and metrics.expectancy_r is not None
        and metrics.expectancy_r >= HOLDOUT_EXP_MIN
    )


def _select_family(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [r for r in rows if r["development_passed"]]
    eligible.sort(
        key=lambda r: (
            float(r["walk_forward"]["pass_fraction"]),
            float(r["development_stressed"]["expectancy_r"]),
            float(r["development_stressed"]["profit_factor"]),
            int(r["development_stressed"]["completed_trades"]),
        ),
        reverse=True,
    )
    return eligible[0] if eligible else None


def evaluate(
    datasets: Mapping[str, tuple[Sequence[Bar], float, M15ResearchCosts, M15ResearchCosts]],
    *,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    symbol_results = {}
    selected_holdout_base = []
    selected_holdout_stress = []
    selected_dev_base = []
    selected_dev_stress = []
    dev_dates = set()
    hold_dates = set()

    for symbol, (bars, pip_size, base_costs, stress_costs) in datasets.items():
        values = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
        split = max(5_000, min(len(values) - 1, int(len(values) * DEVELOPMENT_FRACTION)))
        dev_dates.update(ensure_utc(x.timestamp).date() for x in values[220:split])
        hold_dates.update(ensure_utc(x.timestamp).date() for x in values[split:])

        candidates = []
        trade_sets = {}
        for spec in SPECS:
            signals = extract_family(values, spec=spec)
            base = simulate(values, signals=signals, costs=base_costs, pip_size=pip_size)
            stress = simulate(values, signals=signals, costs=stress_costs, pip_size=pip_size)
            dev_base = tuple(t for t in base if t.signal_index < split and t.exit_index < split)
            dev_stress = tuple(t for t in stress if t.signal_index < split and t.exit_index < split)
            hold_base = tuple(t for t in base if t.signal_index >= split)
            hold_stress = tuple(t for t in stress if t.signal_index >= split)
            dm = compute_metrics(dev_base)
            dms = compute_metrics(dev_stress)
            hm = compute_metrics(hold_base)
            hms = compute_metrics(hold_stress)
            wf = _walk_forward(dev_base, validation_cfg)
            row = {
                "spec": asdict(spec),
                "signals": len(signals),
                "development_base": dm.payload(),
                "development_stressed": dms.payload(),
                "walk_forward": wf,
                "development_passed": _candidate_pass(dms, wf),
                # Holdout is reported for audit only; it is never used in selection.
                "holdout_base": hm.payload(),
                "holdout_stressed": hms.payload(),
                "holdout_passed": _holdout_pass(hms),
            }
            candidates.append(row)
            trade_sets[spec.family] = (dev_base, dev_stress, hold_base, hold_stress)

        selected = _select_family(candidates)
        selected_payload = None
        if selected is not None:
            family = selected["spec"]["family"]
            db, ds, hb, hs = trade_sets[family]
            selected_dev_base.extend(db)
            selected_dev_stress.extend(ds)
            selected_holdout_base.extend(hb)
            selected_holdout_stress.extend(hs)
            selected_payload = {
                "family": family,
                "development_stressed": selected["development_stressed"],
                "walk_forward": selected["walk_forward"],
                "holdout_stressed": selected["holdout_stressed"],
                "holdout_passed": selected["holdout_passed"],
            }

        symbol_results[symbol] = {
            "history_bars": len(values),
            "split_index": split,
            "candidates": candidates,
            "selected": selected_payload,
        }

    dev_m = compute_metrics(selected_dev_stress)
    hold_m = compute_metrics(selected_holdout_stress)
    dev_f = _frequency(selected_dev_base, dev_dates)
    hold_f = _frequency(selected_holdout_base, hold_dates)
    selected_symbols = [s for s, row in symbol_results.items() if row["selected"] is not None]
    holdout_positive_symbols = [
        s for s, row in symbol_results.items()
        if row["selected"] is not None and row["selected"]["holdout_passed"]
    ]

    aggregate_quality = bool(
        hold_m.completed_trades >= 100
        and hold_m.profit_factor is not None
        and hold_m.profit_factor >= HOLDOUT_PF_MIN
        and hold_m.expectancy_r is not None
        and hold_m.expectancy_r >= HOLDOUT_EXP_MIN
    )
    aggregate_frequency = bool(
        hold_f["mean_trades_per_day"] >= ROUTER_FINAL_FREQUENCY_TARGET["mean_trades_per_day_min"]
        and hold_f["days_ge_5_fraction"] >= ROUTER_FINAL_FREQUENCY_TARGET["days_ge_5_fraction_min"]
    )
    breadth_pass = bool(
        len(selected_symbols) >= 5
        and len(holdout_positive_symbols) / max(1, len(selected_symbols)) >= 0.60
    )
    forward_demo_eligible = bool(aggregate_quality and aggregate_frequency and breadth_pass)

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "promotion_eligible": False,
        "forward_demo_eligible": forward_demo_eligible,
        "symbols": list(datasets),
        "families": list(FAMILIES),
        "selection_contract": {
            "development_only": True,
            "min_dev_trades": MIN_DEV_TRADES,
            "dev_pf_min": DEV_PF_MIN,
            "dev_expectancy_r_min": DEV_EXP_MIN,
            "dev_wf_pass_fraction_min": DEV_WF_PASS_FRACTION_MIN,
            "holdout_pf_min": HOLDOUT_PF_MIN,
            "holdout_expectancy_r_min": HOLDOUT_EXP_MIN,
            "holdout_min_trades": MIN_HOLDOUT_TRADES,
        },
        "symbol_results": symbol_results,
        "selected_symbols": selected_symbols,
        "holdout_positive_symbols": holdout_positive_symbols,
        "aggregate_development_stressed": dev_m.payload(),
        "aggregate_development_frequency": dev_f,
        "aggregate_holdout_stressed": hold_m.payload(),
        "aggregate_holdout_frequency": hold_f,
        "aggregate_quality_pass": aggregate_quality,
        "aggregate_frequency_pass": aggregate_frequency,
        "breadth_pass": breadth_pass,
        "final_frequency_target": ROUTER_FINAL_FREQUENCY_TARGET,
        "note": (
            "Each symbol chooses one strategy family using development data only. "
            "The untouched holdout is opened after selection. Passing V19 grants only "
            "forward-DEMO challenger status and never order authority."
        ),
    }
