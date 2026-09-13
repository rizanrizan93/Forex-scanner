from __future__ import annotations

"""Read-only cTrader cross-feed replay for the remaining public-history WATCH champions.

No order path, execution influence, or promotion authority is present. This is an independent
broker-native check before deciding whether any pair deserves forward shadow collection.
"""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ctrader_watch_pair_crossfeed_v1 import Trade, _adx_series, _metrics
from fx_scanner.demo_five_core_router import _closed_rows, _ema, _true_ranges, _wilder_ewm
from fx_scanner.execution.factory import build_ctrader_research_feed
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.models import Bar, ensure_utc

UTC = timezone.utc
CONTRACT = "CTRADER_REMAINING_WATCH_CROSSFEED_V2"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False

SPECS = {
    "GBPJPY": {
        "strategy_id": "D1_TSMOM_60_200",
        "timeframe": "D1",
        "period": 60,
        "stress_cost_pips": 3.5,
        "public_recent_expectancy_r": 0.0616,
        "public_recent_profit_factor": 1.115,
    },
    "USDCAD": {
        "strategy_id": "H4_DONCHIAN40_ADX20",
        "timeframe": "H4",
        "stress_cost_pips": 2.0,
        "public_recent_expectancy_r": 0.0765,
        "public_recent_profit_factor": 1.121,
    },
    "CADJPY": {
        "strategy_id": "D1_TSMOM_120_200",
        "timeframe": "D1",
        "period": 120,
        "stress_cost_pips": 3.0,
        "public_recent_expectancy_r": 0.0420,
        "public_recent_profit_factor": 1.083,
    },
}


def _d1_tsmom(bars: tuple[Bar, ...], period: int) -> list[Trade]:
    closes = [float(row.close) for row in bars]
    ema200 = _ema(closes, 200)
    atr14 = _wilder_ewm(_true_ranges(bars), 14)
    trades: list[Trade] = []
    i = max(200, period)
    while i < len(bars) - 1:
        momentum = closes[i] / closes[i - period] - 1.0
        direction = 0
        if closes[i] > ema200[i] and momentum > 0:
            direction = 1
        elif closes[i] < ema200[i] and momentum < 0:
            direction = -1
        if direction == 0 or not math.isfinite(atr14[i]) or atr14[i] <= 0:
            i += 1
            continue
        entry_i = i + 1
        entry = float(bars[entry_i].open)
        risk = 2.0 * float(atr14[i])
        stop = entry - direction * risk
        target = entry + direction * 4.0 * float(atr14[i])
        last = min(len(bars) - 1, entry_i + 29)
        exit_i = last
        exit_px = float(bars[last].close)
        gross_r: float | None = None
        reason = "TIME"
        for j in range(entry_i, last + 1):
            hi = float(bars[j].high)
            lo = float(bars[j].low)
            stop_hit = lo <= stop if direction > 0 else hi >= stop
            target_hit = hi >= target if direction > 0 else lo <= target
            if stop_hit:
                gross_r, reason, exit_i = -1.0, "STOP", j
                break
            if target_hit:
                gross_r, reason, exit_i = 2.0, "TARGET", j
                break
        if gross_r is None:
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


def _h4_donchian_adx(bars: tuple[Bar, ...]) -> list[Trade]:
    closes = [float(row.close) for row in bars]
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    atr14 = _wilder_ewm(_true_ranges(bars), 14)
    adx14 = _adx_series(bars, 14)
    trades: list[Trade] = []
    i = 200
    while i < len(bars) - 1:
        prior = bars[i - 40 : i]
        prior_high = max(float(row.high) for row in prior)
        prior_low = min(float(row.low) for row in prior)
        direction = 0
        if ema50[i] > ema200[i] and adx14[i] >= 20.0 and closes[i] > prior_high:
            direction = 1
        elif ema50[i] < ema200[i] and adx14[i] >= 20.0 and closes[i] < prior_low:
            direction = -1
        if direction == 0 or not math.isfinite(atr14[i]) or atr14[i] <= 0:
            i += 1
            continue
        entry_i = i + 1
        entry = float(bars[entry_i].open)
        risk = 1.5 * float(atr14[i])
        stop = entry - direction * risk
        target = entry + direction * 3.0 * float(atr14[i])
        last = min(len(bars) - 1, entry_i + 23)
        exit_i = last
        exit_px = float(bars[last].close)
        gross_r: float | None = None
        reason = "TIME"
        for j in range(entry_i, last + 1):
            hi = float(bars[j].high)
            lo = float(bars[j].low)
            stop_hit = lo <= stop if direction > 0 else hi >= stop
            target_hit = hi >= target if direction > 0 else lo <= target
            if stop_hit:
                gross_r, reason, exit_i = -1.0, "STOP", j
                break
            if target_hit:
                gross_r, reason, exit_i = 2.0, "TARGET", j
                break
        if gross_r is None:
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


def _decision(metrics: dict, bars: tuple[Bar, ...], timeframe: str) -> str:
    minimum_bars = 420 if timeframe == "D1" else 2500
    if len(bars) < minimum_bars:
        return "INSUFFICIENT_BROKER_HISTORY"
    if int(metrics.get("trades") or 0) < 8:
        return "INSUFFICIENT_BROKER_TRADES"
    expectancy = metrics.get("expectancy_r")
    pf = metrics.get("profit_factor")
    if expectancy is not None and pf is not None and float(expectancy) > 0 and float(pf) > 1.0:
        return "BROKER_FEED_SUPPORT"
    return "BROKER_FEED_CONTRADICTS"


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("REMAINING_WATCH_CROSSFEED_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("REMAINING_WATCH_CROSSFEED_REQUIRE_DEMO")

    symbols = tuple(SPECS)
    feed = build_ctrader_research_feed(policy, symbols)
    as_of = datetime.now(tz=UTC)
    output: dict[str, dict] = {}
    try:
        feed.ensure_connected()
        for symbol, spec in SPECS.items():
            timeframe = str(spec["timeframe"])
            if timeframe == "D1":
                raw = tuple(
                    feed.historical_bars(
                        symbol,
                        "D1",
                        from_time=as_of - timedelta(days=1_900),
                        to_time=as_of,
                        count=1_400,
                    )
                )
                bars = _closed_rows(raw, as_of=as_of, timeframe_seconds=86_400)
                trades = _d1_tsmom(bars, int(spec["period"]))
            else:
                raw = tuple(
                    feed.historical_bars(
                        symbol,
                        "H4",
                        from_time=as_of - timedelta(days=1_600),
                        to_time=as_of,
                        count=5_000,
                    )
                )
                bars = _closed_rows(raw, as_of=as_of, timeframe_seconds=14_400)
                trades = _h4_donchian_adx(bars)
            metrics = _metrics(symbol, trades, float(spec["stress_cost_pips"]))
            output[symbol] = {
                "strategy_id": spec["strategy_id"],
                "timeframe": timeframe,
                "bars": len(bars),
                "first_bar_at": ensure_utc(bars[0].timestamp).isoformat() if bars else None,
                "last_bar_at": ensure_utc(bars[-1].timestamp).isoformat() if bars else None,
                "stress_cost_pips": spec["stress_cost_pips"],
                "metrics": metrics,
                "public_recent_reference": {
                    "expectancy_r": spec["public_recent_expectancy_r"],
                    "profit_factor": spec["public_recent_profit_factor"],
                },
                "decision": _decision(metrics, bars, timeframe),
                "trades_tail": [trade.__dict__ if hasattr(trade, "__dict__") else {
                    "signal_at": trade.signal_at,
                    "entry_at": trade.entry_at,
                    "exit_at": trade.exit_at,
                    "direction": trade.direction,
                    "entry": trade.entry,
                    "risk_price": trade.risk_price,
                    "gross_r": trade.gross_r,
                    "exit_reason": trade.exit_reason,
                } for trade in trades[-10:]],
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
        "source": "cTrader Open API broker-native trendbars",
        "same_bar_policy": "STOP_FIRST",
        "observed_at": as_of.isoformat(),
        "pairs": output,
    }
    out = Path("research_output_remaining_watch_crossfeed_v2")
    out.mkdir(exist_ok=True)
    (out / "ctrader_remaining_watch_crossfeed_v2.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True))
    for symbol, row in output.items():
        metrics = row["metrics"]
        print(
            "REMAINING_WATCH_CROSSFEED "
            f"symbol={symbol} strategy={row['strategy_id']} timeframe={row['timeframe']} "
            f"bars={row['bars']} trades={metrics['trades']} exp_r={metrics['expectancy_r']} "
            f"pf={metrics['profit_factor']} net_r={metrics['net_r']} max_dd_r={metrics['max_dd_r']} "
            f"decision={row['decision']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
