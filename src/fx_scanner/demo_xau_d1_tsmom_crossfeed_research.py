from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from time import sleep
from typing import Any

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar
from .research_xau_d1_tsmom_crossfeed_v1 import (
    BASE_COST_USD,
    BOUNDARY_HOURS_UTC,
    STRESS_COST_USD,
    crossfeed_pass,
    filter_entry_period,
    replay_exact_rule,
    resample_h1_to_daily,
    summarize,
)

UTC = timezone.utc
SYMBOL = "XAUUSD"
TIMEFRAME = "H1"
START_MONTH = date(2023, 1, 1)
END_MONTH = date(2026, 8, 1)
CONFIRM_START = date(2024, 1, 1)
CONFIRM_END = date(2026, 8, 31)
REQUEST_COUNT = 1000


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _months() -> tuple[date, ...]:
    rows: list[date] = []
    current = START_MONTH
    while current <= END_MONTH:
        rows.append(current)
        current = _next_month(current)
    return tuple(rows)


def fetch_history(feed: Any) -> tuple[Bar, ...]:
    by_timestamp: dict[datetime, Bar] = {}
    for month in _months():
        next_month = _next_month(month)
        start = datetime(month.year, month.month, 1, tzinfo=UTC)
        end = datetime(next_month.year, next_month.month, 1, tzinfo=UTC) - timedelta(milliseconds=1)
        fetched = tuple(
            feed.historical_bars(
                SYMBOL,
                TIMEFRAME,
                from_time=start,
                to_time=end,
                count=REQUEST_COUNT,
            )
        )
        for row in fetched:
            if start <= row.timestamp <= end:
                if row.timeframe != TIMEFRAME:
                    raise ValueError(f"unexpected timeframe: {row.timeframe}")
                by_timestamp[row.timestamp] = row
        sleep(0.08)
    rows = tuple(by_timestamp[key] for key in sorted(by_timestamp))
    if any(b.timestamp <= a.timestamp for a, b in zip(rows, rows[1:])):
        raise ValueError("non-increasing XAUUSD H1 history")
    return rows


def _period_payload(trades, start: date, end: date) -> dict[str, object]:
    selected = filter_entry_period(trades, start=start, end=end)
    return {
        "base": asdict(summarize(selected, cost_usd=BASE_COST_USD)),
        "stress": asdict(summarize(selected, cost_usd=STRESS_COST_USD)),
    }


def build_report(history: tuple[Bar, ...]) -> dict[str, object]:
    boundary_rows: list[dict[str, object]] = []
    sensitivity_summaries = []
    primary_summary = None
    for boundary in BOUNDARY_HOURS_UTC:
        daily = resample_h1_to_daily(history, boundary_hour_utc=boundary)
        trades = replay_exact_rule(daily)
        confirm = filter_entry_period(trades, start=CONFIRM_START, end=CONFIRM_END)
        confirm_stress = summarize(confirm, cost_usd=STRESS_COST_USD)
        sensitivity_summaries.append(confirm_stress)
        if boundary == 0:
            primary_summary = confirm_stress
        boundary_rows.append(
            {
                "boundary_hour_utc": boundary,
                "daily_bars": len(daily),
                "daily_start": None if not daily else str(daily[0].day),
                "daily_end": None if not daily else str(daily[-1].day),
                "confirm_2024_2026": _period_payload(trades, CONFIRM_START, CONFIRM_END),
                "era_2024": _period_payload(trades, date(2024, 1, 1), date(2024, 12, 31)),
                "era_2025_2026": _period_payload(trades, date(2025, 1, 1), CONFIRM_END),
            }
        )

    if primary_summary is None:
        raise RuntimeError("primary UTC boundary summary missing")
    passed = crossfeed_pass(primary_summary, tuple(sensitivity_summaries))
    return {
        "schema_version": "FOREX_XAU_D1_TSMOM_CROSSFEED_V1",
        "research_only": True,
        "execution_influence": False,
        "live_execution_enabled": False,
        "candidate": "XAUUSD:D1_TSMOM_60_200",
        "candidate_selected_before_crossfeed": True,
        "selection_source": "Dukascopy PR179 five-core tournament",
        "confirmation_source": "cTrader DEMO broker H1 history resampled locally",
        "exact_rule": {
            "long": "D1 close > EMA200 and 60D return > 0",
            "short": "D1 close < EMA200 and 60D return < 0",
            "entry": "next D1 open",
            "stop": "2.0 ATR14",
            "target": "4.0 ATR14 (2R)",
            "max_hold_bars": 30,
            "same_bar_policy": "STOP_FIRST",
            "overlap": "one position at a time; next scan starts after exit",
        },
        "cost_usd_round_trip": {"base": BASE_COST_USD, "stress": STRESS_COST_USD},
        "confirmation_period": "2024-01-01..2026-08-31",
        "daily_boundary_sensitivity_hours_utc": list(BOUNDARY_HOURS_UTC),
        "crossfeed_gate": {
            "primary_boundary": "00:00 UTC",
            "stress_trades_min": 25,
            "stress_expectancy_r_min": 0.05,
            "stress_profit_factor_min": 1.10,
            "stress_max_drawdown_r": 20.0,
            "bootstrap_positive_fraction_100_min": 0.70,
            "positive_boundary_variants_min": 2,
            "purpose": "eligible for bounded Demo observer only; never LIVE authority",
        },
        "crossfeed_pass": passed,
        "h1_coverage": {
            "rows": len(history),
            "start": None if not history else history[0].timestamp.isoformat(),
            "end": None if not history else history[-1].timestamp.isoformat(),
        },
        "boundaries": boundary_rows,
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_TSMOM_CROSSFEED_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_TSMOM_CROSSFEED_REQUIRE_DEMO")
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    try:
        feed.ensure_connected()
        history = fetch_history(feed)
    finally:
        try:
            feed.close()
        except Exception:
            pass
    print(json.dumps(build_report(history), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
