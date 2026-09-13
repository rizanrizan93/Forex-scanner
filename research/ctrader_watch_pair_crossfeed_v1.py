from __future__ import annotations

"""Read-only cTrader cross-feed validation for the two strongest remaining FX WATCH pairs.

This module has no order path and cannot grant DEMO/LIVE execution authority. It replays the
frozen public-history champion rules on broker-native H4 trendbars so Dukascopy findings can be
checked against the actual cTrader DEMO feed before any promotion decision.
"""

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_scanner.demo_five_core_router import (
    _closed_rows,
    _ema,
    _true_ranges,
    _wilder_ewm,
)
from fx_scanner.execution.factory import build_ctrader_research_feed
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.models import Bar, ensure_utc

UTC = timezone.utc
CONTRACT = "CTRADER_WATCH_PAIR_CROSSFEED_V1"
EXECUTION_INFLUENCE = False
SYMBOLS = ("GBPAUD", "AUDJPY")
TIMEFRAME = "H4"
TIMEFRAME_SECONDS = 14_400
REQUEST_COUNT = 5_000
LOOKBACK_DAYS = 1_600

WATCH_PAIR_SPECS = {
    "GBPAUD": {
        "strategy_id": "H4_MEAN_REVERT_Z2_TO_SMA20",
        "stress_cost_pips": 4.0,
        "public_recent_expectancy_r": 0.1678,
        "public_recent_profit_factor": 1.315,
    },
    "AUDJPY": {
        "strategy_id": "H4_DONCHIAN40_ADX20",
        "stress_cost_pips": 3.0,
        "public_recent_expectancy_r": 0.0215,
        "public_recent_profit_factor": 1.033,
    },
}


@dataclass(frozen=True, slots=True)
class Trade:
    signal_at: str
    entry_at: str
    exit_at: str
    direction: int
    entry: float
    risk_price: float
    gross_r: float
    exit_reason: str


def _pip_size(symbol: str) -> float:
    return 0.01 if str(symbol).upper().endswith("JPY") else 0.0001


def _rsi_series(closes: list[float], period: int = 14) -> list[float]:
    if not closes:
        return []
    gains = [0.0]
    losses = [0.0]
    for prev, cur in zip(closes[:-1], closes[1:]):
        delta = float(cur) - float(prev)
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = _wilder_ewm(gains, period)
    avg_loss = _wilder_ewm(losses, period)
    out: list[float] = []
    for g, loss in zip(avg_gain, avg_loss):
        if loss <= 0:
            out.append(100.0 if g > 0 else 50.0)
        else:
            rs = g / loss
            out.append(100.0 - (100.0 / (1.0 + rs)))
    return out


def _adx_series(bars: tuple[Bar, ...], period: int = 14) -> list[float]:
    if not bars:
        return []
    tr = _true_ranges(bars)
    plus_dm = [0.0]
    minus_dm = [0.0]
    for prev, cur in zip(bars[:-1], bars[1:]):
        up = float(cur.high) - float(prev.high)
        down = float(prev.low) - float(cur.low)
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    atr = _wilder_ewm(tr, period)
    plus = _wilder_ewm(plus_dm, period)
    minus = _wilder_ewm(minus_dm, period)
    dx: list[float] = []
    for a, p, m in zip(atr, plus, minus):
        if a <= 0:
            dx.append(0.0)
            continue
        pdi = 100.0 * p / a
        mdi = 100.0 * m / a
        denom = pdi + mdi
        dx.append(0.0 if denom <= 0 else 100.0 * abs(pdi - mdi) / denom)
    return _wilder_ewm(dx, period)


def _rolling_sma_z(closes: list[float], window: int = 20) -> tuple[list[float], list[float]]:
    sma = [float("nan")] * len(closes)
    z = [float("nan")] * len(closes)
    for i in range(window - 1, len(closes)):
        sample = closes[i - window + 1 : i + 1]
        mean = sum(sample) / float(window)
        variance = sum((v - mean) ** 2 for v in sample) / float(window)
        std = math.sqrt(variance)
        sma[i] = mean
        z[i] = 0.0 if std <= 0 else (closes[i] - mean) / std
    return sma, z


def _metrics(symbol: str, trades: list[Trade], stress_cost_pips: float) -> dict[str, float | int | None]:
    if not trades:
        return {
            "trades": 0,
            "win_rate": None,
            "expectancy_r": None,
            "profit_factor": None,
            "net_r": 0.0,
            "max_dd_r": 0.0,
        }
    cost_abs = float(stress_cost_pips) * _pip_size(symbol)
    net = [float(t.gross_r) - cost_abs / float(t.risk_price) for t in trades]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    pos = sum(wins)
    neg = -sum(losses)
    pf = pos / neg if neg > 0 else (999.0 if pos > 0 else 0.0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in net:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trades": len(net),
        "win_rate": sum(1 for value in net if value > 0) / len(net),
        "expectancy_r": sum(net) / len(net),
        "profit_factor": pf,
        "net_r": sum(net),
        "max_dd_r": max_dd,
    }


def _gbpaud_mean_revert(bars: tuple[Bar, ...]) -> list[Trade]:
    closes = [float(row.close) for row in bars]
    atr = _wilder_ewm(_true_ranges(bars), 14)
    rsi = _rsi_series(closes, 14)
    adx = _adx_series(bars, 14)
    sma20, z20 = _rolling_sma_z(closes, 20)
    trades: list[Trade] = []
    i = 200
    while i < len(bars) - 1:
        direction = 0
        if z20[i] <= -2.0 and rsi[i] <= 30.0 and adx[i] < 20.0:
            direction = 1
        elif z20[i] >= 2.0 and rsi[i] >= 70.0 and adx[i] < 20.0:
            direction = -1
        if direction == 0 or not math.isfinite(atr[i]) or atr[i] <= 0 or not math.isfinite(sma20[i]):
            i += 1
            continue
        entry_i = i + 1
        entry = float(bars[entry_i].open)
        target = float(sma20[i])
        if (direction > 0 and target <= entry) or (direction < 0 and target >= entry):
            i += 1
            continue
        risk = 1.5 * float(atr[i])
        stop = entry - direction * risk
        last = min(len(bars) - 1, entry_i + 11)
        exit_i = last
        exit_px = float(bars[last].close)
        reason = "TIME"
        for j in range(entry_i, last + 1):
            o = float(bars[j].open)
            hi = float(bars[j].high)
            lo = float(bars[j].low)
            if direction > 0:
                if o <= stop:
                    exit_i, exit_px, reason = j, o, "STOP_GAP"
                    break
                if o >= target:
                    exit_i, exit_px, reason = j, target, "TARGET_GAP"
                    break
                stop_hit, target_hit = lo <= stop, hi >= target
            else:
                if o >= stop:
                    exit_i, exit_px, reason = j, o, "STOP_GAP"
                    break
                if o <= target:
                    exit_i, exit_px, reason = j, target, "TARGET_GAP"
                    break
                stop_hit, target_hit = hi >= stop, lo <= target
            if stop_hit:  # STOP_FIRST if both hit in the same H4 bar.
                exit_i, exit_px, reason = j, stop, "STOP"
                break
            if target_hit:
                exit_i, exit_px, reason = j, target, "TARGET"
                break
        gross_r = direction * (exit_px - entry) / risk
        trades.append(
            Trade(
                ensure_utc(bars[i].timestamp).isoformat(),
                ensure_utc(bars[entry_i].timestamp).isoformat(),
                ensure_utc(bars[exit_i].timestamp).isoformat(),
                direction,
                entry,
                risk,
                gross_r,
                reason,
            )
        )
        i = exit_i + 1
    return trades


def _audjpy_donchian_adx(bars: tuple[Bar, ...]) -> list[Trade]:
    closes = [float(row.close) for row in bars]
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    atr = _wilder_ewm(_true_ranges(bars), 14)
    adx = _adx_series(bars, 14)
    trades: list[Trade] = []
    i = 200
    while i < len(bars) - 1:
        prior = bars[i - 40 : i]
        prior_high = max(float(row.high) for row in prior)
        prior_low = min(float(row.low) for row in prior)
        direction = 0
        if ema50[i] > ema200[i] and adx[i] >= 20.0 and closes[i] > prior_high:
            direction = 1
        elif ema50[i] < ema200[i] and adx[i] >= 20.0 and closes[i] < prior_low:
            direction = -1
        if direction == 0 or not math.isfinite(atr[i]) or atr[i] <= 0:
            i += 1
            continue
        entry_i = i + 1
        entry = float(bars[entry_i].open)
        risk = 1.5 * float(atr[i])
        stop = entry - direction * risk
        target = entry + direction * 3.0 * float(atr[i])
        last = min(len(bars) - 1, entry_i + 23)
        exit_i = last
        reason = "TIME"
        gross_r: float | None = None
        for j in range(entry_i, last + 1):
            hi = float(bars[j].high)
            lo = float(bars[j].low)
            stop_hit = lo <= stop if direction > 0 else hi >= stop
            target_hit = hi >= target if direction > 0 else lo <= target
            if stop_hit:  # Frozen public-history conservative same-bar rule.
                gross_r, reason, exit_i = -1.0, "STOP", j
                break
            if target_hit:
                gross_r, reason, exit_i = 2.0, "TARGET", j
                break
        if gross_r is None:
            gross_r = direction * (float(bars[exit_i].close) - entry) / risk
        trades.append(
            Trade(
                ensure_utc(bars[i].timestamp).isoformat(),
                ensure_utc(bars[entry_i].timestamp).isoformat(),
                ensure_utc(bars[exit_i].timestamp).isoformat(),
                direction,
                entry,
                risk,
                gross_r,
                reason,
            )
        )
        i = exit_i + 1
    return trades


def _decision(symbol: str, bars: tuple[Bar, ...], trades: list[Trade], metrics: dict) -> str:
    if len(bars) < 2_500:
        return "INSUFFICIENT_BROKER_HISTORY"
    if int(metrics["trades"] or 0) < 8:
        return "INSUFFICIENT_BROKER_TRADES"
    expectancy = metrics.get("expectancy_r")
    pf = metrics.get("profit_factor")
    if expectancy is not None and pf is not None and float(expectancy) > 0 and float(pf) > 1.0:
        return "BROKER_FEED_SUPPORT"
    return "BROKER_FEED_CONTRADICTS"


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("WATCH_PAIR_CROSSFEED_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("WATCH_PAIR_CROSSFEED_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, SYMBOLS)
    as_of = datetime.now(tz=UTC)
    output: dict[str, dict] = {}
    try:
        feed.ensure_connected()
        for symbol in SYMBOLS:
            start = as_of - timedelta(days=LOOKBACK_DAYS)
            raw = tuple(
                feed.historical_bars(
                    symbol,
                    TIMEFRAME,
                    from_time=start,
                    to_time=as_of,
                    count=REQUEST_COUNT,
                )
            )
            bars = _closed_rows(raw, as_of=as_of, timeframe_seconds=TIMEFRAME_SECONDS)
            trades = _gbpaud_mean_revert(bars) if symbol == "GBPAUD" else _audjpy_donchian_adx(bars)
            spec = WATCH_PAIR_SPECS[symbol]
            metrics = _metrics(symbol, trades, float(spec["stress_cost_pips"]))
            output[symbol] = {
                "strategy_id": spec["strategy_id"],
                "bars": len(bars),
                "first_bar_at": ensure_utc(bars[0].timestamp).isoformat() if bars else None,
                "last_bar_at": ensure_utc(bars[-1].timestamp).isoformat() if bars else None,
                "stress_cost_pips": spec["stress_cost_pips"],
                "metrics": metrics,
                "public_recent_reference": {
                    "expectancy_r": spec["public_recent_expectancy_r"],
                    "profit_factor": spec["public_recent_profit_factor"],
                },
                "decision": _decision(symbol, bars, trades, metrics),
                "trades_tail": [asdict(row) for row in trades[-10:]],
            }
    finally:
        try:
            feed.close()
        except Exception:
            pass

    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "environment": "DEMO",
        "source": "cTrader Open API broker-native H4 trendbars",
        "same_bar_policy": "STOP_FIRST",
        "observed_at": as_of.isoformat(),
        "request_count": REQUEST_COUNT,
        "lookback_days": LOOKBACK_DAYS,
        "pairs": output,
        "promotion_authority": False,
    }
    out = Path("research_output_watch_pair_crossfeed_v1")
    out.mkdir(exist_ok=True)
    (out / "ctrader_watch_pair_crossfeed_v1.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True))
    for symbol, row in output.items():
        metrics = row["metrics"]
        print(
            "WATCH_PAIR_CROSSFEED "
            f"symbol={symbol} strategy={row['strategy_id']} bars={row['bars']} "
            f"trades={metrics['trades']} exp_r={metrics['expectancy_r']} "
            f"pf={metrics['profit_factor']} net_r={metrics['net_r']} "
            f"max_dd_r={metrics['max_dd_r']} decision={row['decision']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
