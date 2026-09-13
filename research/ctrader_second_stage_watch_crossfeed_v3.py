from __future__ import annotations

"""Read-only cTrader replay for second-stage FX WATCH candidates.

Frozen candidates:
- EURJPY D1_TSMOM_252_CHANDELIER3
- EURAUD D1_DONCHIAN100_CHANDELIER3
- GBPAUD D1_DONCHIAN100_CHANDELIER3

No order path, execution influence, promotion authority, or LIVE unlock exists here.
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
CONTRACT = "CTRADER_SECOND_STAGE_WATCH_CROSSFEED_V3"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False

SPECS = {
    "EURJPY": {
        "strategy_id": "D1_TSMOM_252_CHANDELIER3",
        "kind": "TSMOM",
        "period": 252,
        "stress_cost_pips": 2.5,
        "public_stress_expectancy_r": 0.127432,
        "public_stress_profit_factor": 1.294040,
        "public_recent_expectancy_r": 0.172722,
        "public_recent_profit_factor": 1.478467,
    },
    "EURAUD": {
        "strategy_id": "D1_DONCHIAN100_CHANDELIER3",
        "kind": "DONCHIAN",
        "period": 100,
        "stress_cost_pips": 3.5,
        "public_stress_expectancy_r": 0.022941,
        "public_stress_profit_factor": 1.050539,
        "public_recent_expectancy_r": 0.753329,
        "public_recent_profit_factor": 2.902950,
    },
    "GBPAUD": {
        "strategy_id": "D1_DONCHIAN100_CHANDELIER3",
        "kind": "DONCHIAN",
        "period": 100,
        "stress_cost_pips": 4.0,
        "public_stress_expectancy_r": 0.050617,
        "public_stress_profit_factor": 1.103593,
        "public_recent_expectancy_r": 0.301216,
        "public_recent_profit_factor": 1.658275,
    },
}


def _signals(bars: tuple[Bar, ...], *, kind: str, period: int) -> list[int]:
    closes = [float(row.close) for row in bars]
    ema200 = _ema(closes, 200)
    out = [0] * len(bars)
    start = max(200, period)
    for i in range(start, len(bars)):
        if kind == "TSMOM":
            momentum = closes[i] / closes[i - period] - 1.0
            if closes[i] > ema200[i] and momentum > 0:
                out[i] = 1
            elif closes[i] < ema200[i] and momentum < 0:
                out[i] = -1
        elif kind == "DONCHIAN":
            prior = bars[i - period : i]
            if len(prior) < period:
                continue
            prior_high = max(float(row.high) for row in prior)
            prior_low = min(float(row.low) for row in prior)
            if closes[i] > ema200[i] and closes[i] > prior_high:
                out[i] = 1
            elif closes[i] < ema200[i] and closes[i] < prior_low:
                out[i] = -1
        else:
            raise ValueError(f"unsupported strategy kind: {kind}")
    return out


def _simulate_chandelier(
    symbol: str,
    bars: tuple[Bar, ...],
    *,
    strategy_id: str,
    kind: str,
    period: int,
) -> list[Trade]:
    """Exact second-stage D1 exit architecture: initial 2ATR, trail 3ATR, max hold 120."""
    atr14 = _wilder_ewm(_true_ranges(bars), 14)
    directions = _signals(bars, kind=kind, period=period)
    trades: list[Trade] = []
    i = max(200, period)
    while i < len(bars) - 1:
        direction = int(directions[i])
        if direction == 0:
            i += 1
            continue
        atr0 = float(atr14[i])
        if not math.isfinite(atr0) or atr0 <= 0:
            i += 1
            continue
        entry_i = i + 1
        entry = float(bars[entry_i].open)
        risk = 2.0 * atr0
        stop = entry - direction * risk
        last = min(len(bars) - 1, entry_i + 120 - 1)
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
            current_atr = float(atr14[j])
            if math.isfinite(current_atr) and current_atr > 0:
                candidate = (
                    highest - 3.0 * current_atr
                    if direction > 0
                    else lowest + 3.0 * current_atr
                )
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


def _decision(metrics: dict, bars: tuple[Bar, ...]) -> str:
    if len(bars) < 900:
        return "INSUFFICIENT_BROKER_HISTORY"
    if int(metrics.get("trades") or 0) < 8:
        return "INSUFFICIENT_BROKER_TRADES"
    expectancy = metrics.get("expectancy_r")
    profit_factor = metrics.get("profit_factor")
    if expectancy is not None and profit_factor is not None and float(expectancy) > 0 and float(profit_factor) > 1.0:
        return "BROKER_FEED_SUPPORT"
    return "BROKER_FEED_CONTRADICTS"


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("SECOND_STAGE_WATCH_CROSSFEED_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("SECOND_STAGE_WATCH_CROSSFEED_REQUIRE_DEMO")

    symbols = tuple(SPECS)
    feed = build_ctrader_research_feed(policy, symbols)
    as_of = datetime.now(tz=UTC)
    output: dict[str, dict] = {}
    try:
        feed.ensure_connected()
        for symbol, spec in SPECS.items():
            raw = tuple(
                feed.historical_bars(
                    symbol,
                    "D1",
                    from_time=as_of - timedelta(days=3_700),
                    to_time=as_of,
                    count=2_800,
                )
            )
            bars = _closed_rows(raw, as_of=as_of, timeframe_seconds=86_400)
            trades = _simulate_chandelier(
                symbol,
                bars,
                strategy_id=str(spec["strategy_id"]),
                kind=str(spec["kind"]),
                period=int(spec["period"]),
            )
            metrics = _metrics(symbol, trades, float(spec["stress_cost_pips"]))
            output[symbol] = {
                "strategy_id": spec["strategy_id"],
                "timeframe": "D1",
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
                        "signal_at": trade.signal_at,
                        "entry_at": trade.entry_at,
                        "exit_at": trade.exit_at,
                        "direction": trade.direction,
                        "entry": trade.entry,
                        "risk_price": trade.risk_price,
                        "gross_r": trade.gross_r,
                        "exit_reason": trade.exit_reason,
                    }
                    for trade in trades[-10:]
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
        "exit_contract": "initial_stop_2ATR__chandelier_trail_3ATR__max_hold_120D1",
        "observed_at": as_of.isoformat(),
        "pairs": output,
    }
    out = Path("research_output_second_stage_watch_crossfeed_v3")
    out.mkdir(exist_ok=True)
    (out / "ctrader_second_stage_watch_crossfeed_v3.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True))
    for symbol, row in output.items():
        metrics = row["metrics"]
        print(
            "SECOND_STAGE_WATCH_CROSSFEED "
            f"symbol={symbol} strategy={row['strategy_id']} bars={row['bars']} "
            f"trades={metrics['trades']} exp_r={metrics['expectancy_r']} "
            f"pf={metrics['profit_factor']} net_r={metrics['net_r']} "
            f"max_dd_r={metrics['max_dd_r']} decision={row['decision']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
