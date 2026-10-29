from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite, log, sqrt
from statistics import median, pstdev
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "FX_CROSS_SECTIONAL_STRENGTH_H1_V28"
ARTIFACT_CONTRACT = "FX_CROSS_SECTIONAL_STRENGTH_H1_V28_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
DIAGNOSTIC_ONLY = True

FX_SYMBOLS = (
    "EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD",
    "EURJPY","GBPJPY","EURGBP","AUDJPY","CADJPY","EURCHF","EURAUD","GBPAUD",
)
PAIR_META = {
    "EURUSD": ("EUR","USD"), "GBPUSD": ("GBP","USD"),
    "USDJPY": ("USD","JPY"), "USDCHF": ("USD","CHF"),
    "USDCAD": ("USD","CAD"), "AUDUSD": ("AUD","USD"),
    "NZDUSD": ("NZD","USD"), "EURJPY": ("EUR","JPY"),
    "GBPJPY": ("GBP","JPY"), "EURGBP": ("EUR","GBP"),
    "AUDJPY": ("AUD","JPY"), "CADJPY": ("CAD","JPY"),
    "EURCHF": ("EUR","CHF"), "EURAUD": ("EUR","AUD"),
    "GBPAUD": ("GBP","AUD"),
}
DEVELOPMENT_FRACTION = 0.70
VOL_LOOKBACK = 48
ATR_PERIOD = 14
EMA_PERIOD = 50
MIN_PAIR_COVERAGE = 0.75
MAX_ACCOUNT_POSITIONS = 10
FREQUENCY_TARGET = 5.0


@dataclass(frozen=True, slots=True)
class StrengthVariant:
    variant_id: str
    momentum_hours: int
    edge_min: float
    top_k_per_hour: int
    require_ema50: bool
    stop_atr: float
    target_r: float
    max_hold_hours: int
    cooldown_hours: int


VARIANTS = (
    StrengthVariant("V28_H12_E25_K3_R125", 12, 25.0, 3, False, 1.25, 1.25, 8, 3),
    StrengthVariant("V28_H12_E35_K2_EMA_R150", 12, 35.0, 2, True, 1.50, 1.50, 12, 4),
    StrengthVariant("V28_H24_E25_K3_R150", 24, 25.0, 3, False, 1.50, 1.50, 12, 4),
    StrengthVariant("V28_H24_E35_K2_EMA_R175", 24, 35.0, 2, True, 1.50, 1.75, 16, 6),
    StrengthVariant("V28_H48_E25_K3_EMA_R150", 48, 25.0, 3, True, 1.75, 1.50, 16, 6),
    StrengthVariant("V28_H48_E40_K2_EMA_R200", 48, 40.0, 2, True, 2.00, 2.00, 24, 8),
)


@dataclass(frozen=True, slots=True)
class StrengthSignal:
    variant_id: str
    symbol: str
    direction: str
    signal_index: int
    signal_at: Any
    edge: float
    atr: float


def _ema(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    if len(values) < period:
        return tuple(None for _ in values)
    seed = sum(float(x) for x in values[:period]) / period
    out: list[float | None] = [None] * (period - 1) + [seed]
    alpha = 2.0 / (period + 1.0)
    prev = seed
    for value in values[period:]:
        prev = alpha * float(value) + (1.0 - alpha) * prev
        out.append(prev)
    return tuple(out)


def _atr_series(rows: Sequence[Bar], period: int = ATR_PERIOD) -> tuple[float | None, ...]:
    if len(rows) < period + 1:
        return tuple(None for _ in rows)
    tr = [0.0]
    for i in range(1, len(rows)):
        prev = float(rows[i - 1].close)
        tr.append(max(
            float(rows[i].high) - float(rows[i].low),
            abs(float(rows[i].high) - prev),
            abs(float(rows[i].low) - prev),
        ))
    out: list[float | None] = [None] * len(rows)
    running = sum(tr[1:period + 1]) / period
    out[period] = running
    for i in range(period + 1, len(rows)):
        running = ((running * (period - 1)) + tr[i]) / period
        out[i] = running
    return tuple(out)


def _normalized_momentum(
    rows: Sequence[Bar],
    lookback: int,
) -> tuple[float | None, ...]:
    closes = [float(x.close) for x in rows]
    hourly = [0.0] * len(rows)
    for i in range(1, len(rows)):
        if closes[i] > 0 and closes[i - 1] > 0:
            hourly[i] = log(closes[i] / closes[i - 1])
    out: list[float | None] = [None] * len(rows)
    warm = max(lookback, VOL_LOOKBACK) + 1
    for i in range(warm, len(rows)):
        sample = hourly[i - VOL_LOOKBACK + 1:i + 1]
        vol = pstdev(sample)
        if not isfinite(vol) or vol <= 1e-12:
            continue
        total = log(closes[i] / closes[i - lookback])
        z = total / (vol * sqrt(float(lookback)))
        z = max(-3.0, min(3.0, z))
        out[i] = z / 3.0 * 100.0
    return tuple(out)


def _strength_snapshot(
    pair_scores: Mapping[str, float],
) -> dict[str, tuple[float, float]]:
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    expected: dict[str, int] = {}
    for symbol, (base, quote) in PAIR_META.items():
        expected[base] = expected.get(base, 0) + 1
        expected[quote] = expected.get(quote, 0) + 1
        raw = pair_scores.get(symbol)
        if raw is None:
            continue
        for ccy, value in ((base, raw), (quote, -raw)):
            sums[ccy] = sums.get(ccy, 0.0) + float(value)
            counts[ccy] = counts.get(ccy, 0) + 1
    out = {}
    for ccy, total in sums.items():
        coverage = counts[ccy] / expected[ccy]
        out[ccy] = (total / counts[ccy], coverage)
    return out


def extract_signals(
    datasets: Mapping[str, Sequence[Bar]],
    *,
    variant: StrengthVariant,
) -> tuple[StrengthSignal, ...]:
    rows = {
        symbol: tuple(sorted(values, key=lambda x: ensure_utc(x.timestamp)))
        for symbol, values in datasets.items()
        if symbol in PAIR_META
    }
    if len(rows) < 10:
        return ()

    index_by_time: dict[str, dict[Any, int]] = {}
    momentum: dict[str, tuple[float | None, ...]] = {}
    atrs: dict[str, tuple[float | None, ...]] = {}
    emas: dict[str, tuple[float | None, ...]] = {}

    timeline = set()
    for symbol, values in rows.items():
        index_by_time[symbol] = {
            ensure_utc(row.timestamp): i for i, row in enumerate(values)
        }
        timeline.update(index_by_time[symbol])
        momentum[symbol] = _normalized_momentum(values, variant.momentum_hours)
        atrs[symbol] = _atr_series(values)
        emas[symbol] = _ema([float(x.close) for x in values], EMA_PERIOD)

    last_signal_time: dict[str, Any] = {}
    output: list[StrengthSignal] = []

    for stamp in sorted(timeline):
        pair_scores = {}
        current_indexes = {}
        for symbol in rows:
            i = index_by_time[symbol].get(stamp)
            if i is None:
                continue
            current_indexes[symbol] = i
            value = momentum[symbol][i]
            if value is not None:
                pair_scores[symbol] = float(value)
        if len(pair_scores) < 12:
            continue

        strengths = _strength_snapshot(pair_scores)
        candidates = []
        for symbol, i in current_indexes.items():
            base, quote = PAIR_META[symbol]
            b = strengths.get(base)
            q = strengths.get(quote)
            if b is None or q is None:
                continue
            if min(b[1], q[1]) < MIN_PAIR_COVERAGE:
                continue
            edge = max(-100.0, min(100.0, (b[0] - q[0]) / 2.0))
            if abs(edge) < variant.edge_min:
                continue

            atr = atrs[symbol][i]
            if atr is None or not isfinite(float(atr)) or float(atr) <= 0:
                continue
            direction = "LONG" if edge > 0 else "SHORT"

            if variant.require_ema50:
                ema = emas[symbol][i]
                prior_i = i - 6
                prior_ema = emas[symbol][prior_i] if prior_i >= 0 else None
                if ema is None or prior_ema is None:
                    continue
                close = float(rows[symbol][i].close)
                slope = float(ema) - float(prior_ema)
                if direction == "LONG" and not (close > float(ema) and slope > 0):
                    continue
                if direction == "SHORT" and not (close < float(ema) and slope < 0):
                    continue

            last = last_signal_time.get(symbol)
            if last is not None:
                if (stamp - last) < timedelta(hours=variant.cooldown_hours):
                    continue
            candidates.append((abs(edge), symbol, direction, i, edge, float(atr)))

        candidates.sort(key=lambda x: (-x[0], x[1]))
        used_ccy = set()
        chosen = 0
        for _, symbol, direction, i, edge, atr in candidates:
            base, quote = PAIR_META[symbol]
            if base in used_ccy or quote in used_ccy:
                continue
            output.append(StrengthSignal(
                variant_id=variant.variant_id,
                symbol=symbol,
                direction=direction,
                signal_index=i,
                signal_at=stamp,
                edge=float(edge),
                atr=atr,
            ))
            used_ccy.update((base, quote))
            last_signal_time[symbol] = stamp
            chosen += 1
            if chosen >= variant.top_k_per_hour:
                break

    return tuple(output)


def _trade_cost_r(
    *,
    risk_price: float,
    bars_held: int,
    pip_size: float,
    costs: M15ResearchCosts,
) -> float:
    elapsed_days = max(0, bars_held) / 24.0
    pips = (
        float(costs.spread_pips) * float(costs.spread_multiplier)
        + float(costs.slippage_pips) * float(costs.slippage_multiplier)
        + float(costs.commission_pips_round_trip)
        + float(costs.swap_pips_per_day) * elapsed_days
    )
    return pips / (risk_price / pip_size)


def simulate_symbol(
    rows: Sequence[Bar],
    *,
    signals: Sequence[StrengthSignal],
    variant: StrengthVariant,
    pip_size: float,
    costs: M15ResearchCosts,
) -> tuple[TournamentTrade, ...]:
    values = tuple(sorted(rows, key=lambda x: ensure_utc(x.timestamp)))
    output = []
    next_free = 0
    for signal in signals:
        i = int(signal.signal_index)
        entry_i = i + 1
        if entry_i < next_free or entry_i >= len(values):
            continue
        entry = float(values[entry_i].open)
        risk = float(variant.stop_atr) * float(signal.atr)
        if risk <= 0:
            continue
        stop = entry - risk if signal.direction == "LONG" else entry + risk
        target = (
            entry + variant.target_r * risk
            if signal.direction == "LONG"
            else entry - variant.target_r * risk
        )
        last_i = min(len(values) - 1, entry_i + variant.max_hold_hours)
        exit_i = last_i
        exit_price = float(values[last_i].close)
        gross_r = None
        reason = "TIME_EXIT"
        for j in range(entry_i, last_i + 1):
            bar = values[j]
            if signal.direction == "LONG":
                stop_hit = float(bar.low) <= stop
                target_hit = float(bar.high) >= target
            else:
                stop_hit = float(bar.high) >= stop
                target_hit = float(bar.low) <= target
            if stop_hit:
                exit_i = j
                exit_price = stop
                gross_r = -1.0
                reason = "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP_HIT"
                break
            if target_hit:
                exit_i = j
                exit_price = target
                gross_r = variant.target_r
                reason = "TARGET_HIT"
                break
        if gross_r is None:
            gross_r = (
                (exit_price - entry) / risk
                if signal.direction == "LONG"
                else (entry - exit_price) / risk
            )
        held = exit_i - entry_i
        cost = _trade_cost_r(
            risk_price=risk,
            bars_held=held,
            pip_size=pip_size,
            costs=costs,
        )
        output.append(TournamentTrade(
            strategy_id=variant.variant_id,
            symbol=signal.symbol,
            direction=signal.direction,
            signal_at=signal.signal_at,
            entry_at=ensure_utc(values[entry_i].timestamp),
            exit_at=ensure_utc(values[exit_i].timestamp),
            signal_index=i,
            exit_index=exit_i,
            entry_price=entry,
            exit_price=exit_price,
            atr_at_signal=signal.atr,
            stop_loss=stop,
            take_profit=target,
            gross_r=float(gross_r),
            cost_r=float(cost),
            net_r=float(gross_r - cost),
            bars_held=held,
            exit_reason=reason,
        ))
        next_free = exit_i + 1
    return tuple(output)


def _cap_account(trades: Sequence[TournamentTrade]) -> tuple[TournamentTrade, ...]:
    accepted = []
    active: list[TournamentTrade] = []
    for trade in sorted(trades, key=lambda x: (ensure_utc(x.entry_at), x.symbol)):
        entry_at = ensure_utc(trade.entry_at)
        active = [x for x in active if ensure_utc(x.exit_at) > entry_at]
        if len(active) >= MAX_ACCOUNT_POSITIONS:
            continue
        accepted.append(trade)
        active.append(trade)
    return tuple(accepted)


def _frequency(trades: Sequence[TournamentTrade], dates: Sequence[Any]) -> dict[str, Any]:
    counts = {d: 0 for d in sorted(set(dates))}
    for trade in trades:
        d = ensure_utc(trade.entry_at).date()
        if d in counts:
            counts[d] += 1
    vals = list(counts.values())
    if not vals:
        return {"trading_days":0,"trades":0,"mean_trades_per_day":0.0,
                "median_trades_per_day":0.0,"days_ge_5_fraction":0.0,
                "zero_trade_days":0,"max_trades_in_day":0}
    return {
        "trading_days": len(vals),
        "trades": sum(vals),
        "mean_trades_per_day": sum(vals) / len(vals),
        "median_trades_per_day": median(vals),
        "days_ge_5_fraction": sum(v >= 5 for v in vals) / len(vals),
        "zero_trade_days": sum(v == 0 for v in vals),
        "max_trades_in_day": max(vals),
    }


def _stability(trades: Sequence[TournamentTrade]) -> dict[str, Any]:
    values = tuple(sorted(trades, key=lambda x: ensure_utc(x.entry_at)))
    if len(values) < 150:
        return {"folds": [], "positive_fraction": 0.0}
    folds = []
    for k in range(3):
        lo = int(len(values) * k / 3)
        hi = int(len(values) * (k + 1) / 3)
        metrics = compute_metrics(values[lo:hi])
        passed = bool(
            metrics.completed_trades >= 40
            and metrics.profit_factor is not None
            and metrics.profit_factor > 1.0
            and metrics.expectancy_r is not None
            and metrics.expectancy_r > 0.0
        )
        folds.append({"fold":k+1,"passed":passed,"metrics":metrics.payload()})
    return {
        "folds": folds,
        "positive_fraction": sum(x["passed"] for x in folds) / len(folds),
    }


def evaluate_v28(
    datasets: Mapping[str, Sequence[Bar]],
    *,
    pip_sizes: Mapping[str, float],
    base_costs: Mapping[str, M15ResearchCosts],
    stressed_costs: Mapping[str, M15ResearchCosts],
) -> dict[str, Any]:
    all_times = sorted({
        ensure_utc(row.timestamp)
        for values in datasets.values()
        for row in values
    })
    split_time = all_times[int(len(all_times) * DEVELOPMENT_FRACTION)]
    dev_dates = sorted({x.date() for x in all_times if x < split_time})
    hold_dates = sorted({x.date() for x in all_times if x >= split_time})

    evaluations = []
    for variant in VARIANTS:
        signals = extract_signals(datasets, variant=variant)
        by_symbol: dict[str, list[StrengthSignal]] = {}
        for signal in signals:
            by_symbol.setdefault(signal.symbol, []).append(signal)

        base_all = []
        stress_all = []
        for symbol, sigs in by_symbol.items():
            base_all.extend(simulate_symbol(
                datasets[symbol], signals=sigs, variant=variant,
                pip_size=pip_sizes[symbol], costs=base_costs[symbol],
            ))
            stress_all.extend(simulate_symbol(
                datasets[symbol], signals=sigs, variant=variant,
                pip_size=pip_sizes[symbol], costs=stressed_costs[symbol],
            ))

        base_all = _cap_account(base_all)
        stress_all = _cap_account(stress_all)
        dev_base = tuple(t for t in base_all if ensure_utc(t.entry_at) < split_time and ensure_utc(t.exit_at) < split_time)
        dev_stress = tuple(t for t in stress_all if ensure_utc(t.entry_at) < split_time and ensure_utc(t.exit_at) < split_time)
        hold_base = tuple(t for t in base_all if ensure_utc(t.entry_at) >= split_time)
        hold_stress = tuple(t for t in stress_all if ensure_utc(t.entry_at) >= split_time)

        dm = compute_metrics(dev_base)
        dms = compute_metrics(dev_stress)
        hm = compute_metrics(hold_base)
        hms = compute_metrics(hold_stress)
        stability = _stability(dev_stress)
        dev_freq = _frequency(dev_base, dev_dates)
        hold_freq = _frequency(hold_base, hold_dates)
        development_passed = bool(
            dms.completed_trades >= 500
            and dms.profit_factor is not None and dms.profit_factor >= 1.05
            and dms.expectancy_r is not None and dms.expectancy_r >= 0.02
            and stability["positive_fraction"] >= 2/3
        )
        evaluations.append({
            "variant": asdict(variant),
            "signals": len(signals),
            "development_base": dm.payload(),
            "development_stressed": dms.payload(),
            "development_frequency": dev_freq,
            "stability": stability,
            "development_passed": development_passed,
            "holdout_base": hm.payload(),
            "holdout_stressed": hms.payload(),
            "holdout_frequency": hold_freq,
        })

    eligible = [x for x in evaluations if x["development_passed"]]
    eligible.sort(key=lambda x: (
        float(x["stability"]["positive_fraction"]),
        float(x["development_stressed"]["expectancy_r"]),
        float(x["development_stressed"]["profit_factor"]),
        float(x["development_frequency"]["mean_trades_per_day"]),
    ), reverse=True)
    selected = eligible[0] if eligible else None

    holdout_pass = False
    if selected is not None:
        h = selected["holdout_stressed"]
        f = selected["holdout_frequency"]
        holdout_pass = bool(
            h["completed_trades"] >= 200
            and h["profit_factor"] is not None and h["profit_factor"] >= 1.10
            and h["expectancy_r"] is not None and h["expectancy_r"] >= 0.05
            and f["mean_trades_per_day"] >= FREQUENCY_TARGET
            and f["days_ge_5_fraction"] >= 0.50
        )

    return {
        "research_version": RESEARCH_VERSION,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "promotion_eligible": False,
        "xau_untouched": True,
        "symbols": sorted(datasets),
        "split_time": str(split_time),
        "variants": evaluations,
        "selected_variant": None if selected is None else selected["variant"]["variant_id"],
        "holdout_pass": holdout_pass,
        "forward_shadow_candidate": bool(holdout_pass),
        "frequency_target_mean_trades_per_day": FREQUENCY_TARGET,
        "note": (
            "Independent non-XAU alpha lane. Cross-sectional currency-strength momentum "
            "uses only completed H1 data. XAU D1+M15 authority and parameters are untouched."
        ),
    }
