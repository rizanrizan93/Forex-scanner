from __future__ import annotations

import json
from typing import Any

from .demo_m15_asia_london_research import SYMBOLS, build_report, fetch_monthly_history
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy


def _validation_score(row: dict[str, Any]) -> tuple[float, float, float]:
    stress_validation = row["stress"]["validation"]
    base_validation = row["base"]["validation"]
    return (
        float(stress_validation["average_net_r"]),
        float(base_validation["average_net_r"]),
        float(base_validation["profit_factor"]),
    )


def select_on_validation(report: dict[str, Any]) -> dict[str, Any]:
    ranked = sorted(report["candidates"], key=_validation_score, reverse=True)
    result = dict(report)
    result["schema_version"] = "FOREX_M15_ASIA_LONDON_FROZEN_OOS_V2_VALIDATION_SELECTED"
    result["selection_partition"] = "validation"
    result["oos_used_for_selection"] = False
    result["selection_rule"] = (
        "rank by pooled validation stress average_net_r, then validation base average_net_r, "
        "then validation base profit_factor; OOS is final audit only"
    )
    result["ranking"] = [str(row["candidate"]["name"]) for row in ranked]
    result["candidates"] = ranked
    return result


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

    report = select_on_validation(build_report(history))
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
