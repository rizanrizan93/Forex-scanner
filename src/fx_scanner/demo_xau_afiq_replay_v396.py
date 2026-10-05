from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import ensure_utc
from .xau_afiq_replay_v396 import run_replay

UTC = timezone.utc
SYMBOL = "XAUUSD"
DEFAULT_START = "2025-01-01T00:00:00+00:00"
OUTPUT_PATH = "v396_replay.json"


def _dt(value: str | None, *, fallback: datetime) -> datetime:
    if not value:
        return fallback
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return ensure_utc(parsed)


def _fetch_history(feed: Any, timeframe: str, start: datetime, end: datetime) -> tuple[Any, ...]:
    timeframe = timeframe.upper()
    if timeframe == "H1":
        chunk = timedelta(days=21)
        count = 700
    elif timeframe == "H4":
        chunk = timedelta(days=84)
        count = 700
    else:
        raise ValueError(timeframe)
    by_ts: dict[datetime, Any] = {}
    cursor = start
    while cursor < end:
        right = min(end, cursor + chunk)
        rows = tuple(
            feed.historical_bars(
                SYMBOL,
                timeframe,
                from_time=cursor,
                to_time=right,
                count=count,
            )
        )
        for bar in rows:
            ts = ensure_utc(bar.timestamp)
            if start <= ts < end:
                by_ts[ts] = bar
        cursor = right
        sleep(0.15)
    return tuple(by_ts[key] for key in sorted(by_ts))


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V396_REPLAY_DEMO_CREDENTIALS_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V396_REPLAY_REQUIRE_DEMO")

    now = datetime.now(tz=UTC)
    start = _dt(os.getenv("V396_START", DEFAULT_START), fallback=now - timedelta(days=365))
    end = _dt(os.getenv("V396_END"), fallback=now)
    if end <= start:
        raise SystemExit("V396_REPLAY_INVALID_PERIOD")

    # Add causal warm-up history. Trades in the first 120 H1 bars are suppressed
    # by the replay core, but this buffer also lets H4/H1 zones exist near the
    # requested research start without borrowing future information.
    fetch_start = start - timedelta(days=90)
    feed = build_ctrader_research_feed(policy, [SYMBOL])
    try:
        feed.ensure_connected()
        h1 = _fetch_history(feed, "H1", fetch_start, end)
        h4 = _fetch_history(feed, "H4", fetch_start, end)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    result = run_replay(h1, h4)
    result["requested_period"] = {"start": start.isoformat(), "end": end.isoformat()}
    result["fetch_warmup_start"] = fetch_start.isoformat()
    result["note"] = (
        "V396 is a gross, causal research replay. It does not change the DEMO or LIVE executor. "
        "Historical transaction costs and the scheduled-event archive are not yet applied."
    )

    safe = _json_safe(result)
    output = Path(os.getenv("V396_OUTPUT_PATH", OUTPUT_PATH))
    output.write_text(json.dumps(safe, indent=2, sort_keys=True), encoding="utf-8")
    metrics = safe.get("metrics", {})
    print(
        "V396_REPLAY_SUMMARY "
        f"period={safe['period']['start']}..{safe['period']['end']} "
        f"h1={safe['bars']['H1']} h4={safe['bars']['H4']} "
        f"trades={metrics.get('trades')} win_rate={metrics.get('win_rate')} "
        f"gross_pf={metrics.get('gross_profit_factor')} expectancy_r={metrics.get('expectancy_r')} "
        f"max_dd_r={metrics.get('max_drawdown_r')} net_r={metrics.get('net_r')} "
        f"output={output}"
    )
    print("V396_BY_YEAR " + json.dumps(safe.get("by_year", {}), sort_keys=True))
    print("V396_NUMERIC_GATES " + json.dumps(safe.get("numeric_gates", {}), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
