from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from time import sleep
from typing import Any

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar
from .research_four_ema_m15_v1 import (
    FROZEN_CANDIDATES,
    reprice_cost,
    replay_candidate,
    split_calendar,
    summarize,
)

UTC = timezone.utc
SYMBOLS = ("EURUSD", "GBPUSD", "AUDUSD", "USDJPY")
TIMEFRAME = "M15"
START_MONTH = date(2024, 1, 1)
END_MONTH = date(2026, 8, 1)
TRAIN_END = date(2024, 12, 31)
VALIDATION_END = date(2025, 12, 31)
OOS_END = date(2026, 8, 31)
BASE_COST_PIPS = 1.2
STRESS_COST_PIPS = 1.5
REQUEST_COUNT = 3500


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


def fetch_history(feed: Any, symbol: str) -> tuple[Bar, ...]:
    by_timestamp: dict[datetime, Bar] = {}
    for month in _months():
        next_month = _next_month(month)
        start = datetime(month.year, month.month, 1, tzinfo=UTC)
        end = datetime(next_month.year, next_month.month, 1, tzinfo=UTC) - timedelta(milliseconds=1)
        fetched = tuple(
            feed.historical_bars(
                symbol,
                TIMEFRAME,
                from_time=start,
                to_time=end,
                count=REQUEST_COUNT,
            )
        )
        # cTrader may return transport padding older than from_time when count is
        # supplied; discard it before any replay sees the data.
        for row in fetched:
            if start <= row.timestamp <= end:
                if row.timeframe != TIMEFRAME:
                    raise ValueError(f"unexpected timeframe for {symbol}: {row.timeframe}")
                by_timestamp[row.timestamp] = row
        sleep(0.08)
    rows = tuple(by_timestamp[key] for key in sorted(by_timestamp))
    if any(b.timestamp <= a.timestamp for a, b in zip(rows, rows[1:])):
        raise ValueError(f"non-increasing history for {symbol}")
    return rows


def _periods(gross, cost_pips: float) -> dict[str, dict[str, object]]:
    priced = reprice_cost(gross, round_trip_cost_pips=cost_pips)
    split = split_calendar(
        priced,
        train_end=TRAIN_END,
        validation_end=VALIDATION_END,
        oos_end=OOS_END,
    )
    return {name: asdict(summarize(rows)) for name, rows in split.items()}


def _screen_pass(row: dict[str, object]) -> bool:
    base = row["base"]
    stress = row["stress"]
    assert isinstance(base, dict) and isinstance(stress, dict)
    train = base["train"]
    validation = stress["validation"]
    oos = stress["oos"]
    assert isinstance(train, dict) and isinstance(validation, dict) and isinstance(oos, dict)
    return bool(
        int(train["trades"]) >= 100
        and int(validation["trades"]) >= 30
        and int(oos["trades"]) >= 30
        and float(validation["win_rate"]) >= 0.50
        and float(validation["profit_factor"]) >= 1.10
        and float(validation["expectancy_r"]) >= 0.05
        and float(oos["win_rate"]) >= 0.50
        and float(oos["profit_factor"]) >= 1.10
        and float(oos["expectancy_r"]) >= 0.05
        and float(oos["max_drawdown_r"]) <= 12.0
    )


def build_report(history: dict[str, tuple[Bar, ...]]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for candidate in FROZEN_CANDIDATES:
        for symbol in SYMBOLS:
            gross = replay_candidate(history[symbol], candidate=candidate)
            record: dict[str, object] = {
                "candidate": candidate.name,
                "symbol": symbol,
                "base": _periods(gross, BASE_COST_PIPS),
                "stress": _periods(gross, STRESS_COST_PIPS),
            }
            record["screen_pass"] = _screen_pass(record)
            rows.append(record)

    ranked = sorted(
        rows,
        key=lambda row: (
            float(row["stress"]["validation"]["expectancy_r"]),
            float(row["stress"]["validation"]["profit_factor"]),
            int(row["stress"]["validation"]["trades"]),
        ),
        reverse=True,
    )
    return {
        "schema_version": "FOREX_FOUR_EMA_M15_RESEARCH_V1",
        "research_only": True,
        "execution_influence": False,
        "live_execution_enabled": False,
        "profile": "SCALP_9_20_34_50",
        "periods": [9, 20, 34, 50],
        "brochure_periods_confirmed": False,
        "selection_partition": "validation",
        "oos_used_for_selection": False,
        "symbols": list(SYMBOLS),
        "period": {
            "train": "2024",
            "validation": "2025",
            "oos": "2026-01..2026-08",
        },
        "cost_pips": {"base": BASE_COST_PIPS, "stress": STRESS_COST_PIPS},
        "screen_contract": {
            "train_trades_min": 100,
            "validation_trades_min": 30,
            "oos_trades_min": 30,
            "stress_win_rate_min": 0.50,
            "stress_profit_factor_min": 1.10,
            "stress_expectancy_r_min": 0.05,
            "oos_max_drawdown_r": 12.0,
            "purpose": "bounded Demo eligibility only; never LIVE authority",
        },
        "screen_pass": [
            f"{row['symbol']}:{row['candidate']}" for row in ranked if row["screen_pass"]
        ],
        "validation_ranking": [f"{row['symbol']}:{row['candidate']}" for row in ranked],
        "rows": ranked,
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("FOUR_EMA_RESEARCH_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("FOUR_EMA_RESEARCH_REQUIRE_DEMO")
    feed = build_ctrader_research_feed(policy, SYMBOLS)
    try:
        feed.ensure_connected()
        history = {symbol: fetch_history(feed, symbol) for symbol in SYMBOLS}
    finally:
        try:
            feed.close()
        except Exception:
            pass
    print(json.dumps(build_report(history), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
