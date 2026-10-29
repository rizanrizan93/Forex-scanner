from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from statistics import median
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _indicator_series
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "MULTISYMBOL_M15_BREAKOUT_V18"
ARTIFACT_CONTRACT = "MULTISYMBOL_M15_BREAKOUT_V18_EVIDENCE_1"
EXECUTION_INFLUENCE = False
POLICY_EFFECT = "SHADOW_ONLY"
TIMEFRAME = "M15"
TIMEFRAME_SECONDS = 900
MAX_HOLD_BARS = 16
STOP_BUFFER_ATR = 0.15
MIN_RISK_ATR = 0.50
DEVELOPMENT_FRACTION = 0.75

SYMBOLS = (
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD",
    "AUDUSD", "NZDUSD", "XAUUSD", "XTIUSD",
)

DEVELOPMENT_FREQUENCY_FLOOR = {
    "mean_trades_per_day_min": 3.0,
    "days_ge_5_fraction_min": 0.20,
}
FINAL_FREQUENCY_TARGET = {
    "mean_trades_per_day_min": 5.0,
    "days_ge_5_fraction_min": 0.50,
}


@dataclass(frozen=True, slots=True)
class BreakoutVariant:
    variant_id: str
    lookback_m15: int
    h1_adx_min: float
    require_d1_match: bool
    target_r: float
    body_atr_min: float
    cooldown_bars: int


VARIANTS = (
    BreakoutVariant("V18_L8_ADX10_NOD1_R100", 8, 10.0, False, 1.00, 0.40, 2),
    BreakoutVariant("V18_L8_ADX10_NOD1_R125", 8, 10.0, False, 1.25, 0.45, 2),
    BreakoutVariant("V18_L12_ADX12_NOD1_R150", 12, 12.0, False, 1.50, 0.50, 3),
    BreakoutVariant("V18_L8_ADX12_D1_R125", 8, 12.0, True, 1.25, 0.45, 2),
    BreakoutVariant("V18_L12_ADX12_D1_R150", 12, 12.0, True, 1.50, 0.50, 3),
    BreakoutVariant("V18_L20_ADX15_D1_R200", 20, 15.0, True, 2.00, 0.55, 4),
)


@dataclass(frozen=True, slots=True)
class BreakoutSignal:
    variant_id: str
    symbol: str
    signal_index: int
    direction: str
    signal_at: Any
    atr: float
    stop: float
    reward_r: float


def _aggregate_h1(rows: Sequence[Bar]) -> tuple[Bar, ...]:
    buckets: dict[Any, list[Bar]] = {}
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        key = stamp.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(key, []).append(row)
    out: list[Bar] = []
    for stamp in sorted(buckets):
        group = sorted(buckets[stamp], key=lambda x: ensure_utc(x.timestamp))
        if len(group) != 4:
            continue
        out.append(Bar(
            symbol=group[0].symbol,
            timeframe="H1",
            timestamp=stamp,
            open=float(group[0].open),
            high=max(float(x.high) for x in group),
            low=min(float(x.low) for x in group),
            close=float(group[-1].close),
            tick_count=sum(int(x.tick_count) for x in group),
            spread_avg=sum(float(x.spread_avg) for x in group) / len(group),
            spread_max=max(float(x.spread_max) for x in group),
        ))
    return tuple(out)


def _daily_regime(rows: Sequence[Bar]) -> dict[Any, str | None]:
    grouped: dict[Any, list[Bar]] = {}
    for row in rows:
        grouped.setdefault(ensure_utc(row.timestamp).date(), []).append(row)
    days = sorted(grouped)
    closes = [float(sorted(grouped[d], key=lambda x: ensure_utc(x.timestamp))[-1].close) for d in days]
    ema: list[float | None] = [None] * len(days)
    alpha = 2.0 / 201.0
    running = None
    for i, value in enumerate(closes):
        running = value if running is None else alpha * value + (1.0 - alpha) * running
        if i >= 199:
            ema[i] = float(running)
    mapping: dict[Any, str | None] = {}
    for i in range(len(days) - 1):
        direction = None
        if i >= 199 and i >= 60 and ema[i] is not None:
            ret60 = closes[i] / closes[i - 60] - 1.0
            if closes[i] > float(ema[i]) and ret60 > 0:
                direction = "LONG"
            elif closes[i] < float(ema[i]) and ret60 < 0:
                direction = "SHORT"
        mapping[days[i + 1]] = direction
    return mapping


def _h1_bias(*, signal_close, h1, h1_closes, indicators, adx_min: float) -> str | None:
    count = bisect_right(h1_closes, signal_close)
    if count <= 0:
        return None
    i = count - 1
    if i < 60:
        return None
    values = (
        indicators["ema20"][i], indicators["ema50"][i], indicators["adx"][i],
        indicators["plus_di"][i], indicators["minus_di"][i],
    )
    if any(v is None for v in values):
        return None
    ema20, ema50, adx, plus_di, minus_di = (float(v) for v in values)
    if adx < adx_min:
        return None
    close = float(h1[i].close)
    long_ok = close > ema20 > ema50 and plus_di > minus_di
    short_ok = close < ema20 < ema50 and minus_di > plus_di
    if long_ok == short_ok:
        return None
    return "LONG" if long_ok else "SHORT"


def extract_signals(rows: Sequence[Bar], *, variant: BreakoutVariant) -> tuple[BreakoutSignal, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    if not bars:
        return ()
    symbol = bars[0].symbol.upper()
    indicators = _indicator_series(bars)
    h1 = _aggregate_h1(bars)
    h1_ind = _indicator_series(h1)
    h1_closes = tuple(ensure_utc(x.timestamp) + timedelta(hours=1) for x in h1)
    d1 = _daily_regime(bars)

    out: list[BreakoutSignal] = []
    last_i = -10_000
    warmup = max(220, variant.lookback_m15 + 5)
    for i in range(warmup, len(bars) - 2):
        if i - last_i < variant.cooldown_bars:
            continue
        row = bars[i]
        stamp = ensure_utc(row.timestamp)
        if stamp.hour == 21:
            continue
        atr_raw = indicators["atr"][i]
        if atr_raw is None:
            continue
        atr = float(atr_raw)
        if atr <= 0:
            continue
        body = abs(float(row.close) - float(row.open))
        rng = float(row.high) - float(row.low)
        if rng <= 0 or body < variant.body_atr_min * atr:
            continue

        h1_bias = _h1_bias(
            signal_close=stamp + timedelta(minutes=15),
            h1=h1,
            h1_closes=h1_closes,
            indicators=h1_ind,
            adx_min=variant.h1_adx_min,
        )
        if h1_bias is None:
            continue
        if variant.require_d1_match and d1.get(stamp.date()) != h1_bias:
            continue

        prior = bars[i - variant.lookback_m15:i]
        upper = max(float(x.high) for x in prior)
        lower = min(float(x.low) for x in prior)
        local = bars[max(0, i - 5):i + 1]

        direction = None
        stop = None
        if (
            h1_bias == "LONG"
            and float(row.close) > upper
            and (float(row.close) - float(row.low)) / rng >= 0.68
        ):
            direction = "LONG"
            stop = min(float(x.low) for x in local) - STOP_BUFFER_ATR * atr
        elif (
            h1_bias == "SHORT"
            and float(row.close) < lower
            and (float(row.high) - float(row.close)) / rng >= 0.68
        ):
            direction = "SHORT"
            stop = max(float(x.high) for x in local) + STOP_BUFFER_ATR * atr
        if direction is None or stop is None:
            continue

        risk = float(row.close) - stop if direction == "LONG" else stop - float(row.close)
        if not isfinite(risk) or risk < MIN_RISK_ATR * atr:
            continue
        out.append(BreakoutSignal(
            variant_id=variant.variant_id,
            symbol=symbol,
            signal_index=i,
            direction=direction,
            signal_at=stamp,
            atr=atr,
            stop=float(stop),
            reward_r=float(variant.target_r),
        ))
        last_i = i
    return tuple(out)


def _cost_r(*, risk_pips: float, bars_held: int, costs: M15ResearchCosts) -> float:
    elapsed_days = max(0, bars_held) * TIMEFRAME_SECONDS / 86400.0
    total = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return total / risk_pips


def simulate(
    rows: Sequence[Bar],
    *,
    signals: Sequence[BreakoutSignal],
    costs: M15ResearchCosts,
    pip_size: float,
) -> tuple[TournamentTrade, ...]:
    bars = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    out: list[TournamentTrade] = []
    for sig in signals:
        entry_i = sig.signal_index + 1
        if entry_i >= len(bars):
            continue
        entry = float(bars[entry_i].open)
        risk = entry - sig.stop if sig.direction == "LONG" else sig.stop - entry
        if not isfinite(risk) or risk <= 0:
            continue
        target = entry + sig.reward_r * risk if sig.direction == "LONG" else entry - sig.reward_r * risk
        risk_pips = risk / float(pip_size)
        if risk_pips <= 0:
            continue
        last_i = min(len(bars) - 1, entry_i + MAX_HOLD_BARS)
        trade = None
        for j in range(entry_i, last_i + 1):
            bar = bars[j]
            if sig.direction == "LONG":
                stop_hit = float(bar.low) <= sig.stop
                target_hit = float(bar.high) >= target
            else:
                stop_hit = float(bar.high) >= sig.stop
                target_hit = float(bar.low) <= target
            raw_target = target_hit
            if j == entry_i:
                target_hit = False
            held = j - entry_i
            cost = _cost_r(risk_pips=risk_pips, bars_held=held, costs=costs)
            if stop_hit:
                gross = -1.0
                trade = TournamentTrade(
                    sig.variant_id, sig.symbol, sig.direction, sig.signal_at,
                    ensure_utc(bars[entry_i].timestamp), ensure_utc(bar.timestamp),
                    sig.signal_index, j, entry, sig.stop, sig.atr, sig.stop, target,
                    gross, cost, gross - cost, held,
                    "STOP_FIRST_AMBIGUOUS" if raw_target else "STOP_HIT",
                )
                break
            if target_hit:
                gross = sig.reward_r
                trade = TournamentTrade(
                    sig.variant_id, sig.symbol, sig.direction, sig.signal_at,
                    ensure_utc(bars[entry_i].timestamp), ensure_utc(bar.timestamp),
                    sig.signal_index, j, entry, target, sig.atr, sig.stop, target,
                    gross, cost, gross - cost, held, "TARGET_HIT",
                )
                break
        if trade is None:
            if last_i < entry_i + MAX_HOLD_BARS:
                continue
            bar = bars[last_i]
            exit_price = float(bar.close)
            gross = (
                (exit_price - entry) / risk
                if sig.direction == "LONG"
                else (entry - exit_price) / risk
            )
            cost = _cost_r(risk_pips=risk_pips, bars_held=MAX_HOLD_BARS, costs=costs)
            trade = TournamentTrade(
                sig.variant_id, sig.symbol, sig.direction, sig.signal_at,
                ensure_utc(bars[entry_i].timestamp), ensure_utc(bar.timestamp),
                sig.signal_index, last_i, entry, exit_price, sig.atr, sig.stop, target,
                gross, cost, gross - cost, MAX_HOLD_BARS, "TIME_EXIT",
            )
        out.append(trade)
    return tuple(out)


def _quality(metrics) -> bool:
    return bool(
        metrics.completed_trades >= 100
        and metrics.profit_factor is not None and metrics.profit_factor >= 1.10
        and metrics.expectancy_r is not None and metrics.expectancy_r >= 0.05
    )


def _positive(metrics) -> bool:
    return bool(
        metrics.completed_trades >= 20
        and metrics.profit_factor is not None and metrics.profit_factor > 1.0
        and metrics.expectancy_r is not None and metrics.expectancy_r > 0.0
    )


def _walk_forward(trades, cfg: Mapping[str, Any]) -> dict[str, Any]:
    values = tuple(sorted(trades, key=lambda x: (x.exit_at, x.symbol)))
    n = len(values)
    wf = cfg["walk_forward"]
    train = max(int(wf["minimum_train_trades"]), int(n * float(wf["train_fraction"])))
    test = max(int(wf["minimum_test_trades"]), int(n * float(wf["test_fraction"])))
    step = max(1, int(n * float(wf["step_fraction"])))
    folds = []
    start = 0
    while start + train + test <= n:
        m = compute_metrics(values[start + train:start + train + test])
        passed = bool(
            m.completed_trades >= int(wf["minimum_test_trades"])
            and m.profit_factor is not None and m.profit_factor >= 1.10
            and m.expectancy_r is not None and m.expectancy_r >= 0.05
        )
        folds.append({"metrics": m.payload(), "passed": passed})
        start += step
    fraction = sum(int(x["passed"]) for x in folds) / len(folds) if folds else 0.0
    return {
        "folds": folds,
        "pass_fraction": fraction,
        "passed": bool(folds and fraction >= float(wf["minimum_pass_fraction"])),
    }


def _frequency(trades, dates: Sequence[Any]) -> dict[str, Any]:
    ds = sorted(set(dates))
    counts = {d: 0 for d in ds}
    for trade in trades:
        d = ensure_utc(trade.entry_at).date()
        if d in counts:
            counts[d] += 1
    vals = list(counts.values())
    if not vals:
        return {
            "trading_days": 0, "trades": 0, "mean_trades_per_day": 0.0,
            "median_trades_per_day": 0.0, "days_ge_5_fraction": 0.0,
            "days_ge_5": 0, "zero_trade_days": 0, "max_trades_in_day": 0,
        }
    return {
        "trading_days": len(vals),
        "trades": int(sum(vals)),
        "mean_trades_per_day": float(sum(vals) / len(vals)),
        "median_trades_per_day": float(median(vals)),
        "days_ge_5_fraction": float(sum(v >= 5 for v in vals) / len(vals)),
        "days_ge_5": int(sum(v >= 5 for v in vals)),
        "zero_trade_days": int(sum(v == 0 for v in vals)),
        "max_trades_in_day": int(max(vals)),
    }


def _frequency_pass(freq, gate) -> bool:
    return bool(
        freq["mean_trades_per_day"] >= gate["mean_trades_per_day_min"]
        and freq["days_ge_5_fraction"] >= gate["days_ge_5_fraction_min"]
    )


def evaluate(
    datasets: Mapping[str, tuple[Sequence[Bar], float, M15ResearchCosts, M15ResearchCosts]],
    *,
    validation_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rows_out = []
    for variant in VARIANTS:
        dev_base = []
        dev_stress = []
        hold_base = []
        hold_stress = []
        dev_dates = set()
        hold_dates = set()
        per_symbol_dev = {}
        per_symbol_hold = {}

        for symbol, (bars, pip_size, costs, stress_costs) in datasets.items():
            values = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
            split = max(5000, min(len(values) - 1, int(len(values) * DEVELOPMENT_FRACTION)))
            signals = extract_signals(values, variant=variant)
            base = simulate(values, signals=signals, costs=costs, pip_size=pip_size)
            stress = simulate(values, signals=signals, costs=stress_costs, pip_size=pip_size)
            db = tuple(t for t in base if t.signal_index < split and t.exit_index < split)
            ds = tuple(t for t in stress if t.signal_index < split and t.exit_index < split)
            hb = tuple(t for t in base if t.signal_index >= split)
            hs = tuple(t for t in stress if t.signal_index >= split)
            dev_base.extend(db); dev_stress.extend(ds); hold_base.extend(hb); hold_stress.extend(hs)
            dev_dates.update(ensure_utc(x.timestamp).date() for x in values[220:split])
            hold_dates.update(ensure_utc(x.timestamp).date() for x in values[split:])
            per_symbol_dev[symbol] = compute_metrics(ds).payload()
            per_symbol_hold[symbol] = compute_metrics(hs).payload()

        dm = compute_metrics(dev_base)
        dms = compute_metrics(dev_stress)
        hm = compute_metrics(hold_base)
        hms = compute_metrics(hold_stress)
        wf = _walk_forward(dev_base, validation_cfg)
        df = _frequency(dev_base, dev_dates)
        hf = _frequency(hold_base, hold_dates)
        positive_dev = sum(_positive(compute_metrics([t for t in dev_stress if t.symbol == s])) for s in datasets)
        positive_hold = sum(_positive(compute_metrics([t for t in hold_stress if t.symbol == s])) for s in datasets)
        symbol_count = len(datasets)

        dev_pass = bool(
            dm.completed_trades >= 500
            and _quality(dms)
            and wf["passed"]
            and positive_dev / symbol_count >= 0.55
            and _frequency_pass(df, DEVELOPMENT_FREQUENCY_FLOOR)
        )
        hold_quality = bool(
            _quality(hms)
            and positive_hold / symbol_count >= 0.55
        )
        hold_frequency = _frequency_pass(hf, FINAL_FREQUENCY_TARGET)

        rows_out.append({
            "variant": asdict(variant),
            "development_base": dm.payload(),
            "development_stressed": dms.payload(),
            "development_frequency": df,
            "development_positive_symbols": positive_dev,
            "development_symbol_count": symbol_count,
            "development_by_symbol_stressed": per_symbol_dev,
            "walk_forward": wf,
            "development_passed": dev_pass,
            "holdout_base": hm.payload(),
            "holdout_stressed": hms.payload(),
            "holdout_frequency": hf,
            "holdout_positive_symbols": positive_hold,
            "holdout_by_symbol_stressed": per_symbol_hold,
            "holdout_quality_pass": hold_quality,
            "holdout_frequency_pass": hold_frequency,
            "holdout_passed": bool(dev_pass and hold_quality and hold_frequency),
        })

    eligible = [x for x in rows_out if x["development_passed"]]
    eligible.sort(key=lambda x: (
        x["walk_forward"]["pass_fraction"],
        x["development_frequency"]["days_ge_5_fraction"],
        x["development_stressed"]["expectancy_r"] or -999.0,
        x["development_stressed"]["profit_factor"] or -999.0,
    ), reverse=True)
    selected = eligible[0] if eligible else None
    promotion_eligible = bool(selected and selected["holdout_passed"])

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "symbols": list(datasets),
        "development_frequency_floor": DEVELOPMENT_FREQUENCY_FLOOR,
        "final_frequency_target": FINAL_FREQUENCY_TARGET,
        "variants": rows_out,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "selected_holdout": None if selected is None else {
            "stressed": selected["holdout_stressed"],
            "frequency": selected["holdout_frequency"],
            "positive_symbols": selected["holdout_positive_symbols"],
            "passed": selected["holdout_passed"],
        },
        "promotion_eligible": promotion_eligible,
        "note": (
            "V18 measures the five-trades/day objective account-wide across Tier-A FX/metal instruments. "
            "It does not force five XAUUSD orders and does not grant execution authority."
        ),
    }
