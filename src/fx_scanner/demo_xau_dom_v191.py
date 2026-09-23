from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
import os
import time
from typing import Any, Sequence

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_dom_v191"
CONTRACT = "XAU_CTRADER_DOM_MICROSTRUCTURE_V191"

DEFAULT_SAMPLE_SECONDS = 20
DEFAULT_SAMPLE_INTERVAL_SECONDS = 1.0
DEFAULT_MAX_LEVELS = 10
NEAR_LEVELS = 5
MIN_SNAPSHOTS = 5
DOM_STALE_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class DomFrame:
    observed_at: datetime
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    event_count: int
    quote_count: int


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _sum_top(levels: Sequence[tuple[float, float]], n: int = NEAR_LEVELS) -> float:
    return sum(max(0.0, float(size)) for _price, size in tuple(levels)[:n])


def _imbalance(bid_size: float, ask_size: float) -> float | None:
    total = float(bid_size) + float(ask_size)
    if total <= 0:
        return None
    return (float(bid_size) - float(ask_size)) / total


def _largest_level(levels: Sequence[tuple[float, float]]) -> tuple[float | None, float]:
    selected = tuple(levels)[:NEAR_LEVELS]
    if not selected:
        return None, 0.0
    price, size = max(selected, key=lambda item: float(item[1]))
    return float(price), max(0.0, float(size))


def _median_size(levels: Sequence[tuple[float, float]]) -> float | None:
    sizes = sorted(max(0.0, float(size)) for _price, size in tuple(levels)[:NEAR_LEVELS])
    if not sizes:
        return None
    mid = len(sizes) // 2
    if len(sizes) % 2:
        return sizes[mid]
    return (sizes[mid - 1] + sizes[mid]) / 2.0


def _wall_ratio(levels: Sequence[tuple[float, float]]) -> float | None:
    _price, largest = _largest_level(levels)
    median = _median_size(levels)
    if median is None or median <= 0:
        return None
    return largest / median


def _relative_change(first: float, last: float) -> float | None:
    if first <= 0:
        return None
    return (last - first) / first


def _persistence(
    frames: Sequence[DomFrame],
    *,
    side: str,
    price_tolerance: float,
) -> dict[str, Any]:
    walls: list[tuple[float, float]] = []
    for frame in frames:
        levels = frame.bids if side == "BID" else frame.asks
        price, size = _largest_level(levels)
        if price is not None and size > 0:
            walls.append((price, size))
    if not walls:
        return {
            "dominant_wall_price": None,
            "wall_persistence": None,
            "mean_wall_size": None,
        }

    # Select the wall-price cluster with the most observations. A small price
    # tolerance handles one/two tick movement while still requiring persistence.
    best_price = None
    best_members: list[tuple[float, float]] = []
    for candidate_price, _candidate_size in walls:
        members = [
            item for item in walls
            if abs(float(item[0]) - float(candidate_price)) <= price_tolerance
        ]
        if len(members) > len(best_members):
            best_price = candidate_price
            best_members = members
    return {
        "dominant_wall_price": best_price,
        "wall_persistence": len(best_members) / len(frames),
        "mean_wall_size": (
            None
            if not best_members
            else sum(float(size) for _price, size in best_members) / len(best_members)
        ),
    }


def analyze_dom_frames(
    frames: Sequence[DomFrame],
    *,
    price_tolerance: float = 0.20,
) -> dict[str, Any]:
    rows = tuple(frames)
    if len(rows) < MIN_SNAPSHOTS:
        return {
            "state": "INSUFFICIENT_DOM_SAMPLES",
            "sample_count": len(rows),
            "execution_influence": False,
            "execution_authority": False,
        }

    bid_sums = [_sum_top(frame.bids) for frame in rows]
    ask_sums = [_sum_top(frame.asks) for frame in rows]
    imbalances = [
        value
        for value in (
            _imbalance(bid, ask)
            for bid, ask in zip(bid_sums, ask_sums)
        )
        if value is not None
    ]
    if not imbalances:
        return {
            "state": "DOM_EMPTY_OR_ONE_SIDED",
            "sample_count": len(rows),
            "execution_influence": False,
            "execution_authority": False,
        }

    first_imbalance = imbalances[0]
    last_imbalance = imbalances[-1]
    mean_imbalance = sum(imbalances) / len(imbalances)
    bid_change = _relative_change(bid_sums[0], bid_sums[-1])
    ask_change = _relative_change(ask_sums[0], ask_sums[-1])

    bid_persistence = _persistence(
        rows,
        side="BID",
        price_tolerance=price_tolerance,
    )
    ask_persistence = _persistence(
        rows,
        side="ASK",
        price_tolerance=price_tolerance,
    )

    bid_wall_ratio = _wall_ratio(rows[-1].bids)
    ask_wall_ratio = _wall_ratio(rows[-1].asks)

    # Bounded descriptive pressure score. This is deliberately not a win
    # probability and cannot authorize execution.
    score = 50.0
    score += 25.0 * max(-1.0, min(1.0, last_imbalance))
    score += 10.0 * max(-1.0, min(1.0, last_imbalance - first_imbalance))
    if bid_change is not None and ask_change is not None:
        score += 7.5 * max(-1.0, min(1.0, bid_change - ask_change))
    bid_p = _finite(bid_persistence.get("wall_persistence"))
    ask_p = _finite(ask_persistence.get("wall_persistence"))
    if bid_p is not None and ask_p is not None:
        score += 7.5 * max(-1.0, min(1.0, bid_p - ask_p))
    score = max(0.0, min(100.0, score))

    if score >= 62.0 and last_imbalance >= 0.10:
        state = "BID_DOMINANT"
    elif score <= 38.0 and last_imbalance <= -0.10:
        state = "ASK_DOMINANT"
    else:
        state = "BALANCED_OR_CONTESTED"

    best_bid = None if not rows[-1].bids else float(rows[-1].bids[0][0])
    best_ask = None if not rows[-1].asks else float(rows[-1].asks[0][0])
    return {
        "state": state,
        "sample_count": len(rows),
        "window_start": rows[0].observed_at.isoformat(),
        "window_end": rows[-1].observed_at.isoformat(),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "top5_bid_units": bid_sums[-1],
        "top5_ask_units": ask_sums[-1],
        "first_imbalance": first_imbalance,
        "last_imbalance": last_imbalance,
        "mean_imbalance": mean_imbalance,
        "bid_top5_change": bid_change,
        "ask_top5_change": ask_change,
        "bid_wall_ratio": bid_wall_ratio,
        "ask_wall_ratio": ask_wall_ratio,
        "bid_wall": bid_persistence,
        "ask_wall": ask_persistence,
        "dom_pressure_score": score,
        "interpretation": (
            "Broker/venue-specific cTrader Level II liquidity. "
            "Not COMEX-wide order flow and not a directional probability."
        ),
        "execution_influence": False,
        "execution_authority": False,
    }


def _to_frame(snapshot) -> DomFrame:
    return DomFrame(
        observed_at=snapshot.observed_at.astimezone(UTC),
        bids=tuple((float(row.price), float(row.size_units)) for row in snapshot.bids),
        asks=tuple((float(row.price), float(row.size_units)) for row in snapshot.asks),
        event_count=int(snapshot.event_count),
        quote_count=int(snapshot.quote_count),
    )


def _latest_previous(store: SupabaseOperationalStore) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,details")
        .eq("worker_name", WORKER_NAME)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0])


def _cross_run_change(
    current: dict[str, Any],
    previous_row: dict[str, Any],
) -> dict[str, Any]:
    previous = dict(previous_row.get("details") or {})
    previous_analysis = dict(previous.get("analysis") or {})
    previous_score = _finite(previous_analysis.get("dom_pressure_score"))
    current_score = _finite(current.get("dom_pressure_score"))
    previous_imbalance = _finite(previous_analysis.get("last_imbalance"))
    current_imbalance = _finite(current.get("last_imbalance"))
    return {
        "previous_observed_at": previous_row.get("observed_at"),
        "previous_state": previous_analysis.get("state"),
        "pressure_score_change": (
            None
            if previous_score is None or current_score is None
            else current_score - previous_score
        ),
        "imbalance_change": (
            None
            if previous_imbalance is None or current_imbalance is None
            else current_imbalance - previous_imbalance
        ),
    }


def run() -> int:
    cfg = load_project_config(None)
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_DOM_V191_DEMO_ONLY")
    if SYMBOL not in cfg.pair_map:
        raise SystemExit("XAU_DOM_V191_SYMBOL_NOT_CONFIGURED")

    sample_seconds = max(
        5,
        min(45, int(os.getenv("XAU_DOM_V191_SAMPLE_SECONDS", str(DEFAULT_SAMPLE_SECONDS)))),
    )
    sample_interval = max(
        0.5,
        min(
            5.0,
            float(
                os.getenv(
                    "XAU_DOM_V191_SAMPLE_INTERVAL_SECONDS",
                    str(DEFAULT_SAMPLE_INTERVAL_SECONDS),
                )
            ),
        ),
    )
    max_levels = max(
        5,
        min(25, int(os.getenv("XAU_DOM_V191_MAX_LEVELS", str(DEFAULT_MAX_LEVELS)))),
    )

    store = SupabaseOperationalStore.from_env()
    previous = _latest_previous(store)
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    frames: list[DomFrame] = []
    error: str | None = None
    subscribed = False

    try:
        feed.ensure_connected()
        feed.clear_depth_snapshot(SYMBOL)
        feed.subscribe_depth((SYMBOL,))
        subscribed = True
        deadline = time.monotonic() + sample_seconds
        last_event_count = -1

        while time.monotonic() < deadline:
            try:
                snapshot = feed.depth_snapshot(SYMBOL, max_levels=max_levels)
                age = (datetime.now(tz=UTC) - snapshot.observed_at).total_seconds()
                if -1.0 <= age <= DOM_STALE_SECONDS:
                    if int(snapshot.event_count) != last_event_count:
                        frames.append(_to_frame(snapshot))
                        last_event_count = int(snapshot.event_count)
            except Exception:
                pass
            feed.heartbeat()
            time.sleep(sample_interval)

        analysis = analyze_dom_frames(frames)
        analysis["cross_run"] = _cross_run_change(analysis, previous)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        analysis = {
            "state": "ERROR",
            "execution_influence": False,
            "execution_authority": False,
        }
    finally:
        if subscribed:
            try:
                feed.unsubscribe_depth((SYMBOL,))
            except Exception:
                pass
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None and analysis.get("state") not in {
        "ERROR",
        "INSUFFICIENT_DOM_SAMPLES",
        "DOM_EMPTY_OR_ONE_SIDED",
    }
    details = {
        "contract": CONTRACT,
        "environment": "DEMO",
        "symbol": SYMBOL,
        "sample_seconds": sample_seconds,
        "sample_interval_seconds": sample_interval,
        "max_levels": max_levels,
        "frames_collected": len(frames),
        "analysis": analysis,
        "source": "CTRADER_OPEN_API_LEVEL_II",
        "source_scope": "BROKER_VENUE_LIQUIDITY_NOT_COMEX_CONSOLIDATED_BOOK",
        "policy_effect": "SHADOW_CONTEXT_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "live_execution_enabled": False,
        "error": error,
        "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
    }
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details=details,
    )
    print(
        "CTRADER_DEMO_XAU_DOM_V191 "
        f"healthy={int(healthy)} frames={len(frames)} "
        f"state={analysis.get('state')} "
        f"score={analysis.get('dom_pressure_score')} "
        f"execution_authority=0"
    )
    return 0 if error is None else 2


if __name__ == "__main__":
    raise SystemExit(run())
