from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Any, Callable

from .config import ProjectConfig, load_project_config
from .demo_five_core_candidate_producer import (
    FIVE_CORE_SYMBOLS,
    _history_window_seconds,
    _subset_cfg,
    _with_history_requirements,
)
from .demo_five_core_forward_evidence import (
    XAU_D1_RESEARCH_BOUNDARY_SECONDS_UTC,
    bar_boundary_snapshot,
)
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .signal_producer import _closed_bars
from .storage.supabase_operational import SupabaseOperationalStore

UTC = timezone.utc
WORKER_NAME = "ctrader_demo_five_core_history_probe"
PROBE_TIMEFRAMES = ("D1", "H4")
REQUEST_DELAY_SECONDS = 0.25


def probe_history(
    feed: Any,
    cfg: ProjectConfig,
    *,
    as_of: datetime,
    sleeper: Callable[[float], None] = sleep,
) -> tuple[
    dict[str, dict[str, int]],
    dict[str, str],
    dict[str, dict[str, dict[str, Any]]],
]:
    """Read-only slow-history sufficiency and bar-boundary probe.

    This intentionally does not call feed.quote(), does not construct signals,
    and has no execution/order dependency. It verifies the same bounded cTrader
    D1/H4 request used by the Five-Core router and records the actual UTC bar-open
    boundary so broker candles can be compared with the research contract.
    """
    counts: dict[str, dict[str, int]] = {}
    failures: dict[str, str] = {}
    boundaries: dict[str, dict[str, dict[str, Any]]] = {}
    minimum = cfg.strategy["mtf"]["minimum_bars"]

    for symbol in FIVE_CORE_SYMBOLS:
        counts[symbol] = {}
        boundaries[symbol] = {}
        for timeframe in PROBE_TIMEFRAMES:
            required = int(minimum[timeframe])
            request_count = required + 12
            timeframe_seconds = int(cfg.timeframes[timeframe])
            start = as_of - timedelta(
                seconds=_history_window_seconds(
                    timeframe,
                    request_count,
                    timeframe_seconds,
                )
            )
            try:
                fetched = tuple(
                    feed.historical_bars(
                        symbol,
                        timeframe,
                        from_time=start,
                        to_time=as_of,
                        count=request_count,
                    )
                )
                closed = _closed_bars(
                    fetched,
                    as_of=as_of,
                    timeframe_seconds=timeframe_seconds,
                )
                counts[symbol][timeframe] = len(closed)
                expected = (
                    XAU_D1_RESEARCH_BOUNDARY_SECONDS_UTC
                    if symbol == "XAUUSD" and timeframe == "D1"
                    else None
                )
                boundaries[symbol][timeframe] = bar_boundary_snapshot(
                    closed,
                    expected_open_seconds_utc=expected,
                )
                if len(closed) < required:
                    failures[f"{symbol}:{timeframe}"] = (
                        f"INSUFFICIENT_CLOSED_BARS:{len(closed)}<{required}"
                    )
            except Exception as exc:
                counts[symbol][timeframe] = 0
                boundaries[symbol][timeframe] = bar_boundary_snapshot(
                    (),
                    expected_open_seconds_utc=(
                        XAU_D1_RESEARCH_BOUNDARY_SECONDS_UTC
                        if symbol == "XAUUSD" and timeframe == "D1"
                        else None
                    ),
                )
                failures[f"{symbol}:{timeframe}"] = f"{type(exc).__name__}:{exc}"
            sleeper(REQUEST_DELAY_SECONDS)

    return counts, dict(sorted(failures.items())), boundaries


def run() -> int:
    cfg = _with_history_requirements(_subset_cfg(load_project_config(None), FIVE_CORE_SYMBOLS))
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("FIVE_CORE_HISTORY_PROBE_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("FIVE_CORE_HISTORY_PROBE_REQUIRE_DEMO")

    feed = build_ctrader_research_feed(policy, FIVE_CORE_SYMBOLS)
    store = SupabaseOperationalStore.from_env()
    as_of = datetime.now(tz=UTC)
    counts: dict[str, dict[str, int]] = {}
    failures: dict[str, str] = {}
    boundaries: dict[str, dict[str, dict[str, Any]]] = {}
    try:
        feed.ensure_connected()
        counts, failures, boundaries = probe_history(feed, cfg, as_of=as_of)
    except Exception as exc:
        failures["CONNECTION"] = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = not failures
    xau_boundary = boundaries.get("XAUUSD", {}).get("D1", {})
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "mode": "READ_ONLY_HISTORY_PROBE_V2_BOUNDARY_AUDIT",
            "environment": "DEMO",
            "execution_influence": False,
            "quote_dependency": False,
            "universe": list(FIVE_CORE_SYMBOLS),
            "timeframes": list(PROBE_TIMEFRAMES),
            "minimum_bars": {
                timeframe: int(cfg.strategy["mtf"]["minimum_bars"][timeframe])
                for timeframe in PROBE_TIMEFRAMES
            },
            "closed_bar_counts": counts,
            "bar_boundaries": boundaries,
            "research_d1_boundary_assumption": {
                "source": "FIVE_CORE_TOURNAMENT_V1 pandas resample('1D') on UTC H1",
                "expected_open_seconds_utc": XAU_D1_RESEARCH_BOUNDARY_SECONDS_UTC,
            },
            "xau_d1_boundary_matches_research": xau_boundary.get("matches_expected_boundary"),
            "failures": failures,
        },
    )

    summary = " ".join(
        f"{symbol}:D1={counts.get(symbol, {}).get('D1', 0)}:H4={counts.get(symbol, {}).get('H4', 0)}"
        for symbol in FIVE_CORE_SYMBOLS
    )
    print(
        "CTRADER_DEMO_FIVE_CORE_HISTORY_PROBE "
        f"healthy={healthy} {summary} failures={len(failures)} "
        f"xau_d1_open_seconds={xau_boundary.get('unique_open_seconds_utc')} "
        f"research_boundary_match={xau_boundary.get('matches_expected_boundary')}"
    )
    if failures:
        for key, value in sorted(failures.items()):
            print(f"HISTORY_PROBE_FAILURE {key} {value}")
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
