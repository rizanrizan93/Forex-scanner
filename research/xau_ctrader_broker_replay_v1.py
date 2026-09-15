from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

from fx_scanner.config import load_project_config
from fx_scanner.demo_five_core_router import _ema, _true_ranges, _wilder_ewm
from fx_scanner.execution.factory import build_ctrader_research_feed
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.models import ensure_utc
from fx_scanner.signal_producer import _closed_bars

UTC = timezone.utc
CONTRACT = "XAU_CTRADER_BROKER_REPLAY_V1"
EXECUTION_INFLUENCE = False
SYMBOL = "XAUUSD"
TIMEFRAME = "D1"
REQUEST_COUNT = 1500
MIN_REQUIRED_CLOSED_BARS = 600
START_AT = datetime(2019, 1, 1, tzinfo=UTC)
OOS_START = datetime(2025, 1, 1, tzinfo=UTC)
STOP_ATR = 2.0
TARGET_ATR = 4.0
MAX_HOLD = 30
SEED = 20260912
COSTS = {
    "base_0.17_usd": 0.17,
    "stress_0.25_usd": 0.25,
    "stress_0.35_usd": 0.35,
}


def _simulate(bars):
    rows = tuple(sorted(bars, key=lambda b: ensure_utc(b.timestamp)))
    closes = [float(b.close) for b in rows]
    ema200 = _ema(closes, 200)
    atr14 = _wilder_ewm(_true_ranges(rows), 14)
    trades: list[dict] = []
    i = 199
    n = len(rows)
    while i < n - 1:
        close = closes[i]
        ret60 = close / closes[i - 60] - 1.0
        direction = 0
        if close > ema200[i] and ret60 > 0:
            direction = 1
        elif close < ema200[i] and ret60 < 0:
            direction = -1
        if direction == 0:
            i += 1
            continue

        atr = float(atr14[i])
        if not math.isfinite(atr) or atr <= 0:
            i += 1
            continue
        entry_i = i + 1
        entry = float(rows[entry_i].open)
        risk = STOP_ATR * atr
        stop = entry - direction * risk
        target = entry + direction * TARGET_ATR * atr
        last_i = min(n - 1, entry_i + MAX_HOLD - 1)
        gross_r = None
        exit_reason = "TIME"
        exit_i = last_i
        mfe_r = 0.0
        mae_r = 0.0

        for j in range(entry_i, last_i + 1):
            high = float(rows[j].high)
            low = float(rows[j].low)
            if direction > 0:
                mfe_r = max(mfe_r, (high - entry) / risk)
                mae_r = min(mae_r, (low - entry) / risk)
                stop_hit = low <= stop
                target_hit = high >= target
            else:
                mfe_r = max(mfe_r, (entry - low) / risk)
                mae_r = min(mae_r, (entry - high) / risk)
                stop_hit = high >= stop
                target_hit = low <= target
            # Frozen conservative ambiguity policy: STOP_FIRST.
            if stop_hit:
                gross_r = -1.0
                exit_reason = "STOP"
                exit_i = j
                break
            if target_hit:
                gross_r = TARGET_ATR / STOP_ATR
                exit_reason = "TARGET"
                exit_i = j
                break

        if gross_r is None:
            exit_price = float(rows[exit_i].close)
            gross_r = direction * (exit_price - entry) / risk

        trades.append(
            {
                "signal_time": ensure_utc(rows[i].timestamp).isoformat(),
                "entry_time": ensure_utc(rows[entry_i].timestamp).isoformat(),
                "exit_time": ensure_utc(rows[exit_i].timestamp).isoformat(),
                "direction": direction,
                "entry": entry,
                "stop": stop,
                "target": target,
                "risk_price": risk,
                "gross_r": gross_r,
                "mfe_r": mfe_r,
                "mae_r": mae_r,
                "exit_reason": exit_reason,
            }
        )
        i = exit_i + 1
    return trades


def _net_values(trades, cost_abs: float):
    return [float(t["gross_r"]) - float(cost_abs) / float(t["risk_price"]) for t in trades]


def _bootstrap_ci(values, seed: int):
    if not values:
        return [None, None]
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(5000):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return [means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]]


def _metrics(trades, cost_abs: float, seed: int):
    values = _net_values(trades, cost_abs)
    if not values:
        return {
            "trades": 0,
            "net_r": 0.0,
            "expectancy_r": None,
            "profit_factor": None,
            "win_rate": None,
            "max_dd_r": 0.0,
            "ci95_lo": None,
            "ci95_hi": None,
        }
    positives = sum(v for v in values if v > 0)
    negatives = -sum(v for v in values if v < 0)
    pf = positives / negatives if negatives > 0 else None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    ci_lo, ci_hi = _bootstrap_ci(values, seed)
    return {
        "trades": len(values),
        "net_r": sum(values),
        "expectancy_r": sum(values) / len(values),
        "profit_factor": pf,
        "win_rate": sum(v > 0 for v in values) / len(values),
        "max_dd_r": max_dd,
        "ci95_lo": ci_lo,
        "ci95_hi": ci_hi,
    }


def _subset(trades, *, start=None, direction=None):
    out = []
    for trade in trades:
        entry_time = datetime.fromisoformat(str(trade["entry_time"]).replace("Z", "+00:00"))
        if start is not None and entry_time < start:
            continue
        if direction is not None and int(trade["direction"]) != int(direction):
            continue
        out.append(trade)
    return out


def _annual(trades, cost_abs: float):
    years: dict[int, list[dict]] = {}
    for trade in trades:
        entry_time = datetime.fromisoformat(str(trade["entry_time"]).replace("Z", "+00:00"))
        years.setdefault(entry_time.year, []).append(trade)
    return [
        {
            "year": year,
            **_metrics(group, cost_abs, SEED + year),
            "long_trades": sum(int(t["direction"]) > 0 for t in group),
            "short_trades": sum(int(t["direction"]) < 0 for t in group),
        }
        for year, group in sorted(years.items())
    ]


def main() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_BROKER_REPLAY_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_BROKER_REPLAY_REQUIRE_DEMO")

    cfg = load_project_config(None)
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAUUSD_MISSING_FROM_CONFIG")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    now = datetime.now(tz=UTC)
    try:
        feed.ensure_connected()
        fetched = tuple(
            feed.historical_bars(
                SYMBOL,
                TIMEFRAME,
                from_time=START_AT,
                to_time=now,
                count=REQUEST_COUNT,
            )
        )
    finally:
        try:
            feed.close()
        except Exception:
            pass

    closed = _closed_bars(fetched, as_of=now, timeframe_seconds=86400)
    if len(closed) < MIN_REQUIRED_CLOSED_BARS:
        raise SystemExit(
            f"INSUFFICIENT_CTRADER_D1_REPLAY_HISTORY:{len(closed)}<{MIN_REQUIRED_CLOSED_BARS}"
        )

    timestamps = [ensure_utc(b.timestamp) for b in closed]
    boundary_seconds = sorted({t.hour * 3600 + t.minute * 60 + t.second for t in timestamps})
    trades = _simulate(closed)
    if len(trades) < 20:
        raise SystemExit(f"INSUFFICIENT_REPLAY_TRADES:{len(trades)}<20")

    stress = {}
    oos = _subset(trades, start=OOS_START)
    for idx, (label, cost) in enumerate(COSTS.items()):
        stress[label] = {
            "cost_abs_usd": cost,
            "FULL_AVAILABLE": _metrics(trades, cost, SEED + idx),
            "OOS_2025_PLUS": _metrics(oos, cost, SEED + 100 + idx),
        }

    base_cost = COSTS["base_0.17_usd"]
    result = {
        "contract": CONTRACT,
        "execution_influence": EXECUTION_INFLUENCE,
        "environment": "DEMO",
        "symbol": SYMBOL,
        "strategy": "D1_TSMOM_60_200",
        "source": "FP Markets cTrader Open API historical D1 trendbars",
        "requested_count": REQUEST_COUNT,
        "fetched_bars": len(fetched),
        "closed_bars": len(closed),
        "first_bar_at": timestamps[0].isoformat(),
        "last_closed_bar_at": timestamps[-1].isoformat(),
        "unique_open_seconds_utc": boundary_seconds,
        "observed_boundary_matches_ny17": set(boundary_seconds).issubset({75600, 79200}),
        "frozen_parameters": {
            "trend": "close vs EMA200",
            "momentum": "60D return same sign",
            "entry": "next broker D1 open",
            "stop_atr": STOP_ATR,
            "target_atr": TARGET_ATR,
            "max_hold_d1": MAX_HOLD,
            "same_bar_policy": "STOP_FIRST",
        },
        "base_metrics": {
            "FULL_AVAILABLE": _metrics(trades, base_cost, SEED + 200),
            "OOS_2025_PLUS": _metrics(oos, base_cost, SEED + 201),
            "LONG_FULL": _metrics(_subset(trades, direction=1), base_cost, SEED + 202),
            "SHORT_FULL": _metrics(_subset(trades, direction=-1), base_cost, SEED + 203),
        },
        "cost_stress": stress,
        "annual": _annual(trades, base_cost),
        "trades": trades,
    }

    out = Path("research_output_xau_ctrader_replay_v1")
    out.mkdir(exist_ok=True)
    (out / "xau_ctrader_broker_replay_v1.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    (out / "summary.json").write_text(
        json.dumps({k: v for k, v in result.items() if k != "trades"}, indent=2, default=str),
        encoding="utf-8",
    )

    print("# XAU CTRADER BROKER REPLAY V1")
    print(
        json.dumps(
            {
                "execution_influence": False,
                "fetched_bars": len(fetched),
                "closed_bars": len(closed),
                "first_bar_at": result["first_bar_at"],
                "last_closed_bar_at": result["last_closed_bar_at"],
                "unique_open_seconds_utc": boundary_seconds,
                "base_metrics": result["base_metrics"],
                "cost_stress": stress,
                "annual": result["annual"],
            },
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
