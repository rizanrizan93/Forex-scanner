from __future__ import annotations

"""Broker-native cTrader cross-feed validation for the V3 EURAUD/GBPAUD champions.

Read-only and DEMO-only. No order placement, execution influence, or promotion authority.
"""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ctrader_watch_pair_crossfeed_v1 import Trade, _metrics
from fx_scanner.demo_five_core_router import _closed_rows, _ema, _true_ranges, _wilder_ewm
from fx_scanner.execution.factory import build_ctrader_research_feed
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.models import Bar, ensure_utc

UTC = timezone.utc
CONTRACT = "CTRADER_EURAUD_GBPAUD_V3_CROSSFEED"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False

SPECS = {
    "EURAUD": {
        "strategy_id": "D1_DONCHIAN55_VOLFILTER_CHANDELIER35",
        "stress_cost_pips": 3.5,
        "public_stress_expectancy_r": 0.027144,
        "public_stress_profit_factor": 1.049745,
        "public_recent_expectancy_r": 1.024199,
        "public_recent_profit_factor": 3.00565,
    },
    "GBPAUD": {
        "strategy_id": "D1_TSMOM_180_CHANDELIER4",
        "stress_cost_pips": 4.0,
        "public_stress_expectancy_r": 0.044414,
        "public_stress_profit_factor": 1.077616,
        "public_recent_expectancy_r": 0.005745,
        "public_recent_profit_factor": 1.009635,
    },
}


def _rolling_median(values: list[float], window: int) -> list[float]:
    out = [math.nan] * len(values)
    for i in range(window - 1, len(values)):
        sample = [v for v in values[i - window + 1 : i + 1] if math.isfinite(v)]
        if sample:
            sample.sort()
            n = len(sample)
            out[i] = sample[n // 2] if n % 2 else (sample[n // 2 - 1] + sample[n // 2]) / 2.0
    return out


def _simulate_chandelier(
    bars: tuple[Bar, ...],
    directions: list[int],
    atr14: list[float],
    *,
    initial_stop_atr: float,
    trail_atr: float,
    max_hold: int,
) -> list[Trade]:
    trades: list[Trade] = []
    i = 0
    while i < len(bars) - 1:
        direction = int(directions[i])
        atr0 = float(atr14[i]) if i < len(atr14) else math.nan
        if direction == 0 or not math.isfinite(atr0) or atr0 <= 0:
            i += 1
            continue

        entry_i = i + 1
        entry = float(bars[entry_i].open)
        risk = initial_stop_atr * atr0
        stop = entry - direction * risk
        last = min(len(bars) - 1, entry_i + max_hold - 1)
        highest = entry
        lowest = entry
        exit_i = last
        exit_px = float(bars[last].close)
        reason = "TIME"

        for j in range(entry_i, last + 1):
            open_ = float(bars[j].open)
            high = float(bars[j].high)
            low = float(bars[j].low)
            close = float(bars[j].close)

            if direction > 0:
                if open_ <= stop:
                    exit_i, exit_px, reason = j, open_, "STOP_GAP"
                    break
                if low <= stop:
                    exit_i, exit_px, reason = j, stop, "STOP"
                    break
            else:
                if open_ >= stop:
                    exit_i, exit_px, reason = j, open_, "STOP_GAP"
                    break
                if high >= stop:
                    exit_i, exit_px, reason = j, stop, "STOP"
                    break

            highest = max(highest, high)
            lowest = min(lowest, low)
            atr = float(atr14[j]) if j < len(atr14) else math.nan
            if math.isfinite(atr) and atr > 0:
                candidate = highest - trail_atr * atr if direction > 0 else lowest + trail_atr * atr
                stop = max(stop, candidate) if direction > 0 else min(stop, candidate)
            exit_px = close

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


def _euraud_donchian55_volfilter(bars: tuple[Bar, ...]) -> list[Trade]:
    closes = [float(row.close) for row in bars]
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    atr14 = _wilder_ewm(_true_ranges(bars), 14)
    atr_pct = [a / c if math.isfinite(a) and c != 0 else math.nan for a, c in zip(atr14, closes)]
    atr_med126 = _rolling_median(atr_pct, 126)
    directions = [0] * len(bars)
    for i in range(max(200, 126, 55), len(bars)):
        prior = bars[i - 55 : i]
        prior_high = max(float(row.high) for row in prior)
        prior_low = min(float(row.low) for row in prior)
        vol_ok = math.isfinite(atr_pct[i]) and math.isfinite(atr_med126[i]) and atr_pct[i] >= atr_med126[i]
        if ema50[i] > ema200[i] and vol_ok and closes[i] > prior_high:
            directions[i] = 1
        elif ema50[i] < ema200[i] and vol_ok and closes[i] < prior_low:
            directions[i] = -1
    return _simulate_chandelier(
        bars,
        directions,
        atr14,
        initial_stop_atr=2.0,
        trail_atr=3.5,
        max_hold=120,
    )


def _gbpaud_tsmom180(bars: tuple[Bar, ...]) -> list[Trade]:
    closes = [float(row.close) for row in bars]
    ema200 = _ema(closes, 200)
    atr14 = _wilder_ewm(_true_ranges(bars), 14)
    directions = [0] * len(bars)
    for i in range(200, len(bars)):
        if i < 180 or closes[i - 180] == 0:
            continue
        ret180 = closes[i] / closes[i - 180] - 1.0
        if closes[i] > ema200[i] and ret180 > 0:
            directions[i] = 1
        elif closes[i] < ema200[i] and ret180 < 0:
            directions[i] = -1
    return _simulate_chandelier(
        bars,
        directions,
        atr14,
        initial_stop_atr=2.0,
        trail_atr=4.0,
        max_hold=160,
    )


def _decision(metrics: dict, bars: tuple[Bar, ...]) -> str:
    if len(bars) < 2000:
        return "INSUFFICIENT_BROKER_HISTORY"
    if int(metrics.get("trades") or 0) < 20:
        return "INSUFFICIENT_BROKER_TRADES"
    expectancy = metrics.get("expectancy_r")
    pf = metrics.get("profit_factor")
    if expectancy is not None and pf is not None and float(expectancy) > 0 and float(pf) > 1.0:
        return "BROKER_FEED_SUPPORT"
    return "BROKER_FEED_CONTRADICTS"


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("EURAUD_GBPAUD_V3_CROSSFEED_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("EURAUD_GBPAUD_V3_CROSSFEED_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, tuple(SPECS))
    as_of = datetime.now(tz=UTC)
    output: dict[str, dict] = {}
    try:
        feed.ensure_connected()
        for symbol, spec in SPECS.items():
            raw = tuple(
                feed.historical_bars(
                    symbol,
                    "D1",
                    from_time=as_of - timedelta(days=4_500),
                    to_time=as_of,
                    count=3_200,
                )
            )
            bars = _closed_rows(raw, as_of=as_of, timeframe_seconds=86_400)
            trades = (
                _euraud_donchian55_volfilter(bars)
                if symbol == "EURAUD"
                else _gbpaud_tsmom180(bars)
            )
            metrics = _metrics(symbol, trades, float(spec["stress_cost_pips"]))
            output[symbol] = {
                "strategy_id": spec["strategy_id"],
                "bars": len(bars),
                "first_bar_at": ensure_utc(bars[0].timestamp).isoformat() if bars else None,
                "last_bar_at": ensure_utc(bars[-1].timestamp).isoformat() if bars else None,
                "stress_cost_pips": spec["stress_cost_pips"],
                "metrics": metrics,
                "public_reference": {
                    "stress_expectancy_r": spec["public_stress_expectancy_r"],
                    "stress_profit_factor": spec["public_stress_profit_factor"],
                    "recent_expectancy_r": spec["public_recent_expectancy_r"],
                    "recent_profit_factor": spec["public_recent_profit_factor"],
                },
                "decision": _decision(metrics, bars),
                "trades_tail": [
                    {
                        "signal_at": t.signal_at,
                        "entry_at": t.entry_at,
                        "exit_at": t.exit_at,
                        "direction": t.direction,
                        "entry": t.entry,
                        "risk_price": t.risk_price,
                        "gross_r": t.gross_r,
                        "exit_reason": t.exit_reason,
                    }
                    for t in trades[-10:]
                ],
            }
    finally:
        try:
            feed.close()
        except Exception:
            pass

    result = {
        "contract": CONTRACT,
        "environment": "DEMO",
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_authority": PROMOTION_AUTHORITY,
        "source": "cTrader Open API broker-native D1 trendbars",
        "same_bar_policy": "STOP_FIRST",
        "observed_at": as_of.isoformat(),
        "pairs": output,
    }
    out = Path("research_output_euraud_gbpaud_v3_crossfeed")
    out.mkdir(exist_ok=True)
    (out / "ctrader_euraud_gbpaud_v3_crossfeed.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True))
    for symbol, row in output.items():
        m = row["metrics"]
        print(
            "EURAUD_GBPAUD_V3_CROSSFEED "
            f"symbol={symbol} strategy={row['strategy_id']} bars={row['bars']} "
            f"trades={m['trades']} exp_r={m['expectancy_r']} pf={m['profit_factor']} "
            f"net_r={m['net_r']} max_dd_r={m['max_dd_r']} decision={row['decision']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
