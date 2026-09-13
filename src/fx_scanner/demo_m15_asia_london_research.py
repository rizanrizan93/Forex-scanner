from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from time import sleep
from typing import Any, Iterable

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar
from .research_m15_asia_london_v2 import (
    FROZEN_CANDIDATES,
    AsiaLondonTrade,
    replay_candidate,
    reprice_cost,
    split_by_calendar,
    summarize,
)

UTC = timezone.utc
SYMBOLS = ("AUDUSD", "USDJPY")
TIMEFRAME = "M15"
START_MONTH = date(2024, 1, 1)
END_MONTH = date(2026, 8, 1)
TRAIN_END = date(2024, 12, 31)
VALIDATION_END = date(2025, 12, 31)
OOS_END = date(2026, 8, 31)
BASE_COST_PIPS = 1.2
STRESS_COST_PIPS = 1.5
REQUEST_COUNT = 3500
REQUEST_DELAY_SECONDS = 0.15


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def month_starts(start: date, end: date) -> tuple[date, ...]:
    if start.day != 1 or end.day != 1:
        raise ValueError("month boundaries must use day=1")
    if end < start:
        raise ValueError("end month must not precede start month")
    rows: list[date] = []
    current = start
    while current <= end:
        rows.append(current)
        current = _next_month(current)
    return tuple(rows)


def fetch_monthly_history(
    feed: Any,
    symbol: str,
    *,
    start_month: date = START_MONTH,
    end_month: date = END_MONTH,
    sleeper=sleep,
) -> tuple[Bar, ...]:
    by_timestamp: dict[datetime, Bar] = {}
    for month in month_starts(start_month, end_month):
        next_month = _next_month(month)
        start = datetime(month.year, month.month, 1, tzinfo=UTC)
        # Exclude the next month boundary if cTrader treats toTimestamp as inclusive.
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
        in_window = tuple(row for row in fetched if start <= row.timestamp <= end)
        # cTrader may return older bars than fromTimestamp when count is supplied.
        # Those bars are transport padding only. Filtering here is fail-safe: no
        # out-of-window observation can enter the replay or any calendar partition.
        for row in in_window:
            if row.timeframe != TIMEFRAME:
                raise ValueError(f"unexpected timeframe for {symbol}: {row.timeframe}")
            by_timestamp[row.timestamp] = row
        sleeper(REQUEST_DELAY_SECONDS)
    rows = tuple(by_timestamp[key] for key in sorted(by_timestamp))
    if any(second.timestamp <= first.timestamp for first, second in zip(rows, rows[1:])):
        raise ValueError(f"broker history is not strictly increasing for {symbol}")
    return rows


def _summary_dict(trades: Iterable[AsiaLondonTrade]) -> dict[str, object]:
    return asdict(summarize(trades))


def _partition_report(
    gross_trades: tuple[AsiaLondonTrade, ...],
    *,
    cost_pips: float,
) -> dict[str, object]:
    priced = reprice_cost(gross_trades, round_trip_cost_pips=cost_pips)
    split = split_by_calendar(
        priced,
        train_end=TRAIN_END,
        validation_end=VALIDATION_END,
        oos_end=OOS_END,
    )
    return {name: _summary_dict(rows) for name, rows in split.items()}


def build_report(history_by_symbol: dict[str, tuple[Bar, ...]]) -> dict[str, object]:
    if set(history_by_symbol) != set(SYMBOLS):
        raise ValueError("history must contain exactly AUDUSD and USDJPY")

    candidates: list[dict[str, object]] = []
    for candidate in FROZEN_CANDIDATES:
        gross_by_symbol = {
            symbol: replay_candidate(
                rows,
                candidate=candidate,
                round_trip_cost_pips=0.0,
            )
            for symbol, rows in sorted(history_by_symbol.items())
        }
        pooled_gross = tuple(
            sorted(
                (trade for rows in gross_by_symbol.values() for trade in rows),
                key=lambda row: row.entry_time,
            )
        )
        base = _partition_report(pooled_gross, cost_pips=BASE_COST_PIPS)
        stress = _partition_report(pooled_gross, cost_pips=STRESS_COST_PIPS)
        by_symbol = {}
        for symbol, rows in sorted(gross_by_symbol.items()):
            by_symbol[symbol] = {
                "base": _partition_report(rows, cost_pips=BASE_COST_PIPS),
                "stress": _partition_report(rows, cost_pips=STRESS_COST_PIPS),
            }
        candidates.append(
            {
                "candidate": asdict(candidate),
                "base": base,
                "stress": stress,
                "by_symbol": by_symbol,
            }
        )

    def score(row: dict[str, object]) -> tuple[float, float, float]:
        stress = row["stress"]
        base = row["base"]
        assert isinstance(stress, dict) and isinstance(base, dict)
        stress_oos = stress["oos"]
        base_oos = base["oos"]
        assert isinstance(stress_oos, dict) and isinstance(base_oos, dict)
        return (
            float(stress_oos["average_net_r"]),
            float(base_oos["average_net_r"]),
            float(base_oos["profit_factor"]),
        )

    ranked = sorted(candidates, key=score, reverse=True)
    return {
        "schema_version": "FOREX_M15_ASIA_LONDON_FROZEN_OOS_V2",
        "research_only": True,
        "broker": "CTRADER_DEMO_READ_ONLY_HISTORY",
        "execution_influence": False,
        "live_execution_enabled": False,
        "symbols": list(SYMBOLS),
        "timeframe": TIMEFRAME,
        "period": {
            "start": START_MONTH.isoformat(),
            "train_end": TRAIN_END.isoformat(),
            "validation_end": VALIDATION_END.isoformat(),
            "oos_end": OOS_END.isoformat(),
        },
        "cost_pips": {"base": BASE_COST_PIPS, "stress": STRESS_COST_PIPS},
        "selection_rule": (
            "rank by pooled OOS stress average_net_r, then pooled OOS base average_net_r, "
            "then pooled OOS base profit_factor"
        ),
        "ranking": [str(row["candidate"]["name"]) for row in ranked],
        "candidates": ranked,
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("M15_ASIA_LONDON_RESEARCH_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("M15_ASIA_LONDON_RESEARCH_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, SYMBOLS)
    try:
        feed.ensure_connected()
        history = {symbol: fetch_monthly_history(feed, symbol) for symbol in SYMBOLS}
    finally:
        try:
            feed.close()
        except Exception:
            pass

    report = build_report(history)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
