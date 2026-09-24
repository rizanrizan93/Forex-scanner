from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

WORKER_NAME = "ctrader_xau_history_probe_v193"
CONTRACT = "XAU_CTRADER_HISTORY_PROBE_V193_1"
SYMBOL = "XAUUSD"

PROBES = (
    datetime(2012, 6, 15, 12, 0, tzinfo=UTC),
    datetime(2016, 6, 15, 12, 0, tzinfo=UTC),
    datetime(2020, 6, 15, 12, 0, tzinfo=UTC),
    datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
)


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V193_HISTORY_PROBE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V193_HISTORY_PROBE_REQUIRE_DEMO")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_V193_HISTORY_PROBE_SYMBOL_NOT_CONFIGURED")

    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    results: list[dict[str, Any]] = []
    try:
        feed.ensure_connected()
        for anchor in PROBES:
            start = anchor - timedelta(days=3)
            end = anchor + timedelta(days=3)
            row: dict[str, Any] = {
                "anchor": anchor.isoformat(),
                "from": start.isoformat(),
                "to": end.isoformat(),
                "timeframe": "M5",
            }
            try:
                bars = tuple(
                    feed.historical_bars(
                        SYMBOL,
                        "M5",
                        from_time=start,
                        to_time=end,
                        count=2500,
                    )
                )
                row.update(
                    {
                        "ok": True,
                        "count": len(bars),
                        "first": None if not bars else bars[0].timestamp.isoformat(),
                        "last": None if not bars else bars[-1].timestamp.isoformat(),
                        "first_close": None if not bars else float(bars[0].close),
                        "last_close": None if not bars else float(bars[-1].close),
                    }
                )
            except Exception as exc:
                row.update(
                    {
                        "ok": False,
                        "count": 0,
                        "error": f"{type(exc).__name__}:{exc}",
                    }
                )
            results.append(row)
    finally:
        try:
            feed.close()
        except Exception:
            pass

    pass_count = sum(bool(row.get("ok")) and int(row.get("count") or 0) > 0 for row in results)
    oldest_ok_year = min(
        (
            int(str(row["anchor"])[:4])
            for row in results
            if bool(row.get("ok")) and int(row.get("count") or 0) > 0
        ),
        default=None,
    )
    all_required = pass_count == len(PROBES)
    details = {
        "contract": CONTRACT,
        "symbol": SYMBOL,
        "observed_at": datetime.now(tz=UTC).isoformat(),
        "probe_results": results,
        "pass_count": pass_count,
        "probe_count": len(PROBES),
        "oldest_ok_year": oldest_ok_year,
        "decision": (
            "CTRADER_M5_HISTORY_2012_PLUS_AVAILABLE"
            if all_required and oldest_ok_year is not None and oldest_ok_year <= 2012
            else "CTRADER_HISTORY_INSUFFICIENT_FOR_FULL_BACKFILL"
        ),
        "policy_effect": "RESEARCH_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }
    healthy = details["decision"] == "CTRADER_M5_HISTORY_2012_PLUS_AVAILABLE"
    SupabaseOperationalStore.from_env().write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details=details,
    )
    print(
        "XAU_CTRADER_HISTORY_PROBE_V193 "
        f"pass={pass_count}/{len(PROBES)} oldest_ok_year={oldest_ok_year} "
        f"decision={details['decision']} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
