from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from time import sleep
from typing import Any

from fx_scanner.execution.factory import build_ctrader_research_feed
from fx_scanner.execution.policy import load_execution_policy
from fx_scanner.research_xau_d1_tsmom_crossfeed_v1 import BOUNDARY_HOURS_UTC, resample_h1_to_daily
from adaptive_router_market_core_v2 import generate_shadow
from adaptive_router_public_backtest import metrics

UTC = timezone.utc
SYMBOL = "XAUUSD"
TIMEFRAME = "H1"
START_MONTH = date(2023, 1, 1)
END_MONTH = date(2026, 8, 1)
REQUEST_COUNT = 1000


def next_month(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def months() -> tuple[date, ...]:
    out = []
    cur = START_MONTH
    while cur <= END_MONTH:
        out.append(cur)
        cur = next_month(cur)
    return tuple(out)


def fetch_history(feed: Any):
    by_ts = {}
    for month in months():
        nxt = next_month(month)
        start = datetime(month.year, month.month, 1, tzinfo=UTC)
        end = datetime(nxt.year, nxt.month, 1, tzinfo=UTC) - timedelta(milliseconds=1)
        rows = tuple(feed.historical_bars(SYMBOL, TIMEFRAME, from_time=start, to_time=end, count=REQUEST_COUNT))
        for row in rows:
            if start <= row.timestamp <= end:
                by_ts[row.timestamp] = row
        sleep(0.08)
    return tuple(by_ts[k] for k in sorted(by_ts))


def as_rows(history, boundary: int):
    daily = resample_h1_to_daily(history, boundary_hour_utc=boundary)
    rows = []
    for row in daily:
        dt = datetime(row.day.year, row.day.month, row.day.day, boundary, tzinfo=UTC)
        rows.append({"dt": dt, "open": row.open, "high": row.high, "low": row.low, "close": row.close})
    return rows


def stress(trades, cost_r: float):
    out = []
    for t in trades:
        x = dict(t)
        x["cost_r"] = cost_r
        x["net_r"] = round(float(x["gross_r"]) - cost_r, 6)
        out.append(x)
    return out


def period(trades, start: date, end: date):
    return [t for t in trades if start <= datetime.fromisoformat(t["entry_at"]).date() <= end]


def main() -> None:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO" or not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("CTRADER_CROSSFEED_DEMO_ONLY")
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        history = fetch_history(feed)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    boundaries = []
    positive = 0
    for boundary in BOUNDARY_HOURS_UTC:
        rows = as_rows(history, boundary)
        all_shadow = generate_shadow(SYMBOL, rows)
        trades = [t for t in all_shadow if t["setup"] == "EXPANSION_BREAKOUT"]
        base = metrics(trades)
        stressed = metrics(stress(trades, 0.10))
        recent = metrics(period(trades, date(2024, 1, 1), date(2026, 8, 31)))
        recent_stress = metrics(stress(period(trades, date(2024, 1, 1), date(2026, 8, 31)), 0.10))
        if recent_stress.get("trades", 0) >= 12 and (recent_stress.get("expectancy_r") or -9) > 0 and (recent_stress.get("profit_factor") or 0) > 1.0:
            positive += 1
        boundaries.append({
            "boundary_hour_utc": boundary,
            "daily_bars": len(rows),
            "daily_start": None if not rows else rows[0]["dt"].date().isoformat(),
            "daily_end": None if not rows else rows[-1]["dt"].date().isoformat(),
            "full_base": base,
            "full_stress": stressed,
            "confirm_2024_2026_base": recent,
            "confirm_2024_2026_stress": recent_stress,
        })

    primary = boundaries[0]["confirm_2024_2026_stress"]
    passed = bool(
        primary.get("trades", 0) >= 12
        and (primary.get("expectancy_r") or -9) >= 0.05
        and (primary.get("profit_factor") or 0) >= 1.10
        and positive >= 2
    )
    result = {
        "schema_version": "ADAPTIVE_XAU_EXPANSION_CTRADER_CROSSFEED_V1",
        "research_only": True,
        "execution_influence": False,
        "live_execution_enabled": False,
        "candidate": "XAUUSD:D1_EXPANSION_BREAKOUT_MARKET_ADAPTIVE_V3_SURVIVOR",
        "selection_source": "public 2012-2026 adaptive V3 research",
        "confirmation_source": "cTrader DEMO broker H1 history resampled locally",
        "h1_coverage": {"rows": len(history), "start": None if not history else history[0].timestamp.isoformat(), "end": None if not history else history[-1].timestamp.isoformat()},
        "daily_boundary_sensitivity_hours_utc": list(BOUNDARY_HOURS_UTC),
        "crossfeed_pass": passed,
        "positive_boundary_variants": positive,
        "boundaries": boundaries,
    }
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
