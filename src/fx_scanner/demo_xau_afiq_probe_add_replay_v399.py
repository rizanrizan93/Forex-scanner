from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .demo_xau_afiq_risk_replay_v397 import _dt, _fetch_history, _json_safe
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .xau_afiq_probe_add_replay_v399 import run_replay

UTC = timezone.utc
SYMBOL = "XAUUSD"
DEFAULT_START = "2025-01-01T00:00:00+00:00"
OUTPUT_PATH = "v399_replay.json"


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("V399_REPLAY_DEMO_CREDENTIALS_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("V399_REPLAY_REQUIRE_DEMO")

    now = datetime.now(tz=UTC)
    start = _dt(os.getenv("V399_START", DEFAULT_START), fallback=now - timedelta(days=365))
    end = _dt(os.getenv("V399_END"), fallback=now)
    if end <= start:
        raise SystemExit("V399_REPLAY_INVALID_PERIOD")

    feed = build_ctrader_research_feed(policy, [SYMBOL])
    try:
        feed.ensure_connected()
        h1 = _fetch_history(feed, "H1", start, end)
        h4 = _fetch_history(feed, "H4", start, end)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    result = run_replay(h1, h4)
    result["requested_period"] = {"start": start.isoformat(), "end": end.isoformat()}
    result["warmup"] = "FIRST_120_H1_BARS_NO_SIGNALS"
    result["note"] = (
        "V399 tests one-quarter anticipatory probe plus three-quarter add only after a frozen H1 reclaim. "
        "Unvalidated probes are cut at the next H1 open after the configured window. Research only."
    )
    safe = _json_safe(result)
    output = Path(os.getenv("V399_OUTPUT_PATH", OUTPUT_PATH))
    output.write_text(json.dumps(safe, indent=2, sort_keys=True), encoding="utf-8")
    summary = {name: payload.get("metrics", {}) for name, payload in safe.get("variants", {}).items()}
    print("V399_REPLAY_SUMMARY " + json.dumps(summary, sort_keys=True))
    print("V399_NUMERIC_GATES " + json.dumps(safe.get("numeric_gates", {}), sort_keys=True))
    print(f"V399_OUTPUT {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
