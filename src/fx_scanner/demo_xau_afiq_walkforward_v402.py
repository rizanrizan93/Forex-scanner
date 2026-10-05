from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .demo_xau_afiq_risk_replay_v397 import _fetch_history, _json_safe
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .xau_afiq_local_confirm_entry_v401 import run_replay

UTC = timezone.utc
SYMBOL = "XAUUSD"
WARMUP_DAYS = 60


def _year_window(year: int, now: datetime) -> tuple[datetime, datetime, datetime]:
    score_start = datetime(year, 1, 1, tzinfo=UTC)
    nominal_end = datetime(year + 1, 1, 1, tzinfo=UTC)
    score_end = min(nominal_end, now)
    fetch_start = score_start - timedelta(days=WARMUP_DAYS)
    return fetch_start, score_start, score_end


def run() -> int:
    year = int(os.getenv("V402_YEAR", "0"))
    if year < 2012 or year > datetime.now(tz=UTC).year:
        raise SystemExit("V402_INVALID_YEAR")

    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V402_REPLAY_DEMO_CREDENTIALS_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V402_REPLAY_REQUIRE_DEMO")

    now = datetime.now(tz=UTC)
    fetch_start, score_start, score_end = _year_window(year, now)
    if score_end <= score_start:
        raise SystemExit("V402_YEAR_NOT_STARTED")

    feed = build_ctrader_research_feed(policy, [SYMBOL])
    try:
        feed.ensure_connected()
        h1 = _fetch_history(feed, "H1", fetch_start, score_end)
        h4 = _fetch_history(feed, "H4", fetch_start, score_end)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    result = run_replay(h1, h4)
    variants: dict[str, object] = {}
    for name, payload_raw in dict(result.get("variants") or {}).items():
        payload = dict(payload_raw or {})
        trades = [
            dict(trade)
            for trade in payload.get("trades") or []
            if str(trade.get("entry_at") or "").startswith(f"{year:04d}-")
        ]
        metrics = dict(payload.get("by_year") or {}).get(str(year), {})
        variants[name] = {"metrics": metrics, "trades": trades}

    report = {
        "contract": "XAU_RIZAN_AFIQ_WALKFORWARD_YEAR_V402",
        "source_contract": result.get("contract"),
        "target_year": year,
        "fetch_period": {"start": fetch_start.isoformat(), "end": score_end.isoformat()},
        "score_period": {"start": score_start.isoformat(), "end": score_end.isoformat()},
        "warmup_days": WARMUP_DAYS,
        "bars": result.get("bars"),
        "variants": variants,
        "note": "Per-year causal replay with 60-day pre-year warmup; only entries inside target calendar year are scored.",
    }
    safe = _json_safe(report)
    output = Path(os.getenv("V402_OUTPUT_PATH", f"v402_{year}.json"))
    output.write_text(json.dumps(safe, indent=2, sort_keys=True), encoding="utf-8")
    summary = {name: dict(payload).get("metrics", {}) for name, payload in safe["variants"].items()}
    print("V402_YEAR_SUMMARY " + json.dumps({"year": year, "variants": summary}, sort_keys=True))
    print(f"V402_OUTPUT {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
