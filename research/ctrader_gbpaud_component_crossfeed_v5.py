from __future__ import annotations

"""Broker-native cTrader validation of the GBPAUD V5 component-divergence champion.

Frozen signal contract:
- D1 GBPAUD above EMA200 + GBPUSD 63-session return > 0 + AUDUSD 63-session return < 0 => long.
- Inverse conditions => short.
- Enter next D1 open.
- Initial stop = 2 * ATR14; Chandelier trailing stop = 3 * ATR14; max hold = 120 D1 bars.
- Conservative stop-first intrabar handling; 4.0 pip stress cost.

Research-only and DEMO-only. This module has no order-placement path, execution influence,
or promotion authority.
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
CONTRACT = "CTRADER_GBPAUD_COMPONENT_CROSSFEED_V5"
EXECUTION_INFLUENCE = False
PROMOTION_AUTHORITY = False
STRATEGY_ID = "D1_COMPONENT_RET63_OPPOSITE_CHANDELIER3"
STRESS_COST_PIPS = 4.0
PUBLIC_STRESS_EXPECTANCY_R = 0.104896
PUBLIC_STRESS_PROFIT_FACTOR = 1.240402
PUBLIC_RECENT_EXPECTANCY_R = 0.059902
PUBLIC_RECENT_PROFIT_FACTOR = 1.119168


def _date_key(bar: Bar) -> str:
    return ensure_utc(bar.timestamp).date().isoformat()


def _align_daily(
    gbpaud: tuple[Bar, ...], gbpusd: tuple[Bar, ...], audusd: tuple[Bar, ...]
) -> tuple[tuple[Bar, ...], tuple[Bar, ...], tuple[Bar, ...]]:
    gbp_map = {_date_key(row): row for row in gbpusd}
    aud_map = {_date_key(row): row for row in audusd}
    cross_rows: list[Bar] = []
    gbp_rows: list[Bar] = []
    aud_rows: list[Bar] = []
    for row in gbpaud:
        key = _date_key(row)
        gbp = gbp_map.get(key)
        aud = aud_map.get(key)
        if gbp is None or aud is None:
            continue
        cross_rows.append(row)
        gbp_rows.append(gbp)
        aud_rows.append(aud)
    return tuple(cross_rows), tuple(gbp_rows), tuple(aud_rows)


def _simulate(
    cross: tuple[Bar, ...], gbp: tuple[Bar, ...], aud: tuple[Bar, ...]
) -> list[Trade]:
    closes = [float(row.close) for row in cross]
    gbp_closes = [float(row.close) for row in gbp]
    aud_closes = [float(row.close) for row in aud]
    ema200 = _ema(closes, 200)
    atr14 = _wilder_ewm(_true_ranges(cross), 14)

    directions = [0] * len(cross)
    for i in range(max(200, 63), len(cross)):
        gbp_prev = gbp_closes[i - 63]
        aud_prev = aud_closes[i - 63]
        if gbp_prev == 0 or aud_prev == 0:
            continue
        gbp_ret63 = gbp_closes[i] / gbp_prev - 1.0
        aud_ret63 = aud_closes[i] / aud_prev - 1.0
        if closes[i] > ema200[i] and gbp_ret63 > 0 and aud_ret63 < 0:
            directions[i] = 1
        elif closes[i] < ema200[i] and gbp_ret63 < 0 and aud_ret63 > 0:
            directions[i] = -1

    trades: list[Trade] = []
    i = 0
    while i < len(cross) - 1:
        direction = int(directions[i])
        atr0 = float(atr14[i]) if i < len(atr14) else math.nan
        if direction == 0 or not math.isfinite(atr0) or atr0 <= 0:
            i += 1
            continue

        entry_i = i + 1
        entry = float(cross[entry_i].open)
        risk = 2.0 * atr0
        stop = entry - direction * risk
        highest = entry
        lowest = entry
        last = min(len(cross) - 1, entry_i + 120 - 1)
        exit_i = last
        exit_px = float(cross[last].close)
        reason = "TIME"

        for j in range(entry_i, last + 1):
            open_ = float(cross[j].open)
            high = float(cross[j].high)
            low = float(cross[j].low)
            close = float(cross[j].close)

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
                candidate = highest - 3.0 * atr if direction > 0 else lowest + 3.0 * atr
                stop = max(stop, candidate) if direction > 0 else min(stop, candidate)
            exit_px = close

        gross_r = direction * (exit_px - entry) / risk
        trades.append(
            Trade(
                ensure_utc(cross[i].timestamp).isoformat(),
                ensure_utc(cross[entry_i].timestamp).isoformat(),
                ensure_utc(cross[exit_i].timestamp).isoformat(),
                direction,
                entry,
                risk,
                gross_r,
                reason,
            )
        )
        i = exit_i + 1
    return trades


def _decision(metrics: dict, aligned_bars: int) -> str:
    if aligned_bars < 2000:
        return "INSUFFICIENT_BROKER_HISTORY"
    if int(metrics.get("trades") or 0) < 30:
        return "INSUFFICIENT_BROKER_TRADES"
    expectancy = metrics.get("expectancy_r")
    profit_factor = metrics.get("profit_factor")
    if expectancy is not None and profit_factor is not None and float(expectancy) > 0 and float(profit_factor) > 1.0:
        return "BROKER_FEED_SUPPORT"
    return "BROKER_FEED_CONTRADICTS"


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("GBPAUD_COMPONENT_CROSSFEED_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("GBPAUD_COMPONENT_CROSSFEED_REQUIRE_DEMO")

    symbols = ("GBPAUD", "GBPUSD", "AUDUSD")
    feed = build_ctrader_research_feed(policy, symbols)
    as_of = datetime.now(tz=UTC)
    fetched: dict[str, tuple[Bar, ...]] = {}
    try:
        feed.ensure_connected()
        for symbol in symbols:
            raw = tuple(
                feed.historical_bars(
                    symbol,
                    "D1",
                    from_time=as_of - timedelta(days=4_500),
                    to_time=as_of,
                    count=3_200,
                )
            )
            fetched[symbol] = _closed_rows(raw, as_of=as_of, timeframe_seconds=86_400)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    cross, gbp, aud = _align_daily(fetched["GBPAUD"], fetched["GBPUSD"], fetched["AUDUSD"])
    trades = _simulate(cross, gbp, aud)
    metrics = _metrics("GBPAUD", trades, STRESS_COST_PIPS)
    result = {
        "contract": CONTRACT,
        "environment": "DEMO",
        "execution_influence": EXECUTION_INFLUENCE,
        "promotion_authority": PROMOTION_AUTHORITY,
        "strategy_id": STRATEGY_ID,
        "source": "cTrader Open API broker-native D1 trendbars",
        "component_symbols": list(symbols),
        "same_bar_policy": "STOP_FIRST",
        "stress_cost_pips": STRESS_COST_PIPS,
        "observed_at": as_of.isoformat(),
        "raw_bar_counts": {symbol: len(rows) for symbol, rows in fetched.items()},
        "aligned_bars": len(cross),
        "first_aligned_bar_at": ensure_utc(cross[0].timestamp).isoformat() if cross else None,
        "last_aligned_bar_at": ensure_utc(cross[-1].timestamp).isoformat() if cross else None,
        "public_reference": {
            "stress_expectancy_r": PUBLIC_STRESS_EXPECTANCY_R,
            "stress_profit_factor": PUBLIC_STRESS_PROFIT_FACTOR,
            "recent_expectancy_r": PUBLIC_RECENT_EXPECTANCY_R,
            "recent_profit_factor": PUBLIC_RECENT_PROFIT_FACTOR,
        },
        "metrics": metrics,
        "decision": _decision(metrics, len(cross)),
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

    out = Path("research_output_gbpaud_component_crossfeed_v5")
    out.mkdir(exist_ok=True)
    (out / "ctrader_gbpaud_component_crossfeed_v5.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print("RESULT_JSON=" + json.dumps(result, sort_keys=True))
    print(
        "GBPAUD_COMPONENT_CROSSFEED "
        f"aligned_bars={len(cross)} trades={metrics['trades']} "
        f"exp_r={metrics['expectancy_r']} pf={metrics['profit_factor']} "
        f"net_r={metrics['net_r']} max_dd_r={metrics['max_dd_r']} "
        f"decision={result['decision']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
