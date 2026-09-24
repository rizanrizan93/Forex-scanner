from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
import os
from statistics import median
from typing import Any, Sequence

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore


SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_v203_volatility_shock_guard"
CONTRACT = "XAU_VOLATILITY_SHOCK_GUARD_V203"

BASELINE_BARS = 48
RECENT_SHOCK_BARS = 6
STABILIZATION_BARS = 3
REQUEST_COUNT = 1000
LOOKBACK_DAYS = 7

RANGE_ELEVATED_RATIO = 1.75
RANGE_SHOCK_RATIO = 2.50
SPREAD_ELEVATED_RATIO = 1.75
SPREAD_SHOCK_RATIO = 2.50

VACUUM_RANGE_RATIO = 1.80
VACUUM_TICK_RATIO = 0.60
VACUUM_BODY_FRACTION = 0.65

RECOVERY_RANGE_RATIO = 1.60
RECOVERY_SPREAD_RATIO = 1.60
RECOVERY_MIN_TICK_RATIO = 0.50


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _closed_m5(rows: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(tuple(rows), key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=5) <= now
    )


def _positive_median(values: Sequence[float]) -> float | None:
    usable = [float(value) for value in values if isfinite(float(value)) and float(value) > 0.0]
    if not usable:
        return None
    return float(median(usable))


def _ratio(value: float, baseline: float | None) -> float | None:
    if baseline is None or baseline <= 0.0:
        return None
    return float(value) / float(baseline)


def _bar_metrics(
    bars: Sequence[Bar],
    *,
    index: int,
    baseline_bars: int = BASELINE_BARS,
) -> dict[str, Any] | None:
    if index < int(baseline_bars):
        return None

    row = bars[index]
    history = tuple(bars[index - int(baseline_bars) : index])
    if len(history) < int(baseline_bars):
        return None

    ranges = [max(0.0, float(item.high) - float(item.low)) for item in history]
    spreads = [
        max(float(item.spread_avg), float(item.spread_max))
        for item in history
        if max(float(item.spread_avg), float(item.spread_max)) > 0.0
    ]
    ticks = [float(item.tick_count) for item in history if int(item.tick_count) > 0]

    baseline_range = _positive_median(ranges)
    baseline_spread = _positive_median(spreads)
    baseline_ticks = _positive_median(ticks)

    current_range = max(0.0, float(row.high) - float(row.low))
    current_body = abs(float(row.close) - float(row.open))
    current_spread = max(float(row.spread_avg), float(row.spread_max))
    current_ticks = float(row.tick_count)

    range_ratio = _ratio(current_range, baseline_range)
    spread_ratio = _ratio(current_spread, baseline_spread)
    tick_ratio = _ratio(current_ticks, baseline_ticks)
    body_fraction = 0.0 if current_range <= 0.0 else current_body / current_range

    range_shock = range_ratio is not None and range_ratio >= RANGE_SHOCK_RATIO
    spread_shock = spread_ratio is not None and spread_ratio >= SPREAD_SHOCK_RATIO
    vacuum_proxy = bool(
        range_ratio is not None
        and tick_ratio is not None
        and range_ratio >= VACUUM_RANGE_RATIO
        and tick_ratio <= VACUUM_TICK_RATIO
        and body_fraction >= VACUUM_BODY_FRACTION
    )

    elevated = bool(
        (range_ratio is not None and range_ratio >= RANGE_ELEVATED_RATIO)
        or (spread_ratio is not None and spread_ratio >= SPREAD_ELEVATED_RATIO)
        or (
            range_ratio is not None
            and tick_ratio is not None
            and range_ratio >= 1.40
            and tick_ratio <= 0.75
            and body_fraction >= 0.60
        )
    )

    reasons: list[str] = []
    if range_shock:
        reasons.append("ABNORMAL_RANGE_EXPANSION")
    if spread_shock:
        reasons.append("SPREAD_SHOCK")
    if vacuum_proxy:
        reasons.append("LIQUIDITY_VACUUM_PROXY")

    return {
        "bar_at": ensure_utc(row.timestamp).isoformat(),
        "bar_close_at": (ensure_utc(row.timestamp) + timedelta(minutes=5)).isoformat(),
        "range_points": current_range,
        "body_points": current_body,
        "body_fraction": body_fraction,
        "spread_observed": current_spread,
        "tick_count": int(row.tick_count),
        "baseline_range_points": baseline_range,
        "baseline_spread": baseline_spread,
        "baseline_tick_count": baseline_ticks,
        "range_ratio": range_ratio,
        "spread_ratio": spread_ratio,
        "tick_ratio": tick_ratio,
        "range_shock": bool(range_shock),
        "spread_shock": bool(spread_shock),
        "liquidity_vacuum_proxy": vacuum_proxy,
        "shock": bool(range_shock or spread_shock or vacuum_proxy),
        "elevated": elevated,
        "shock_reasons": reasons,
    }


def _stable_bar(metrics: dict[str, Any]) -> bool:
    range_ratio = _finite(metrics.get("range_ratio"))
    spread_ratio = _finite(metrics.get("spread_ratio"))
    tick_ratio = _finite(metrics.get("tick_ratio"))
    if bool(metrics.get("shock")):
        return False
    if range_ratio is None or range_ratio > RECOVERY_RANGE_RATIO:
        return False
    if spread_ratio is not None and spread_ratio > RECOVERY_SPREAD_RATIO:
        return False
    if tick_ratio is not None and tick_ratio < RECOVERY_MIN_TICK_RATIO:
        return False
    return True


def evaluate_volatility_shock_guard(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    baseline_bars: int = BASELINE_BARS,
) -> dict[str, Any]:
    closed = _closed_m5(tuple(bars), as_of=as_of)
    minimum = int(baseline_bars) + 1
    if len(closed) < minimum:
        return {
            "contract": CONTRACT,
            "state": "INSUFFICIENT_DATA",
            "shadow_action": "OBSERVE_ONLY",
            "shadow_aggressive_entry_block_recommended": True,
            "shadow_microstructure_authority_state": "RESET",
            "recommended_micro_authority_multiplier": 0.0,
            "effective_execution_block": False,
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "closed_m5_bars": len(closed),
            "required_closed_m5_bars": minimum,
            "reason": "NOT_ENOUGH_COMPLETED_M5_FOR_CAUSAL_BASELINE",
        }

    metrics: list[dict[str, Any]] = []
    for index in range(int(baseline_bars), len(closed)):
        item = _bar_metrics(closed, index=index, baseline_bars=int(baseline_bars))
        if item is not None:
            metrics.append(item)

    if not metrics:
        return {
            "contract": CONTRACT,
            "state": "INSUFFICIENT_DATA",
            "shadow_action": "OBSERVE_ONLY",
            "shadow_aggressive_entry_block_recommended": True,
            "shadow_microstructure_authority_state": "RESET",
            "recommended_micro_authority_multiplier": 0.0,
            "effective_execution_block": False,
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "closed_m5_bars": len(closed),
            "required_closed_m5_bars": minimum,
            "reason": "NO_EVALUABLE_COMPLETED_M5",
        }

    latest = dict(metrics[-1])
    recent = metrics[-RECENT_SHOCK_BARS:]
    recent_shocks = [item for item in recent if bool(item.get("shock"))]

    stable_run = 0
    for item in reversed(metrics):
        if not _stable_bar(item):
            break
        stable_run += 1

    if bool(latest.get("shock")):
        state = "SHOCK"
        shadow_action = "OBSERVE_ONLY"
        micro_state = "RESET"
        micro_multiplier = 0.0
        shadow_block = True
    elif recent_shocks and stable_run < STABILIZATION_BARS:
        state = "STABILIZING"
        shadow_action = "PREPARE_ONLY"
        micro_state = "REDUCED"
        micro_multiplier = 0.25
        shadow_block = True
    elif bool(latest.get("elevated")):
        state = "ELEVATED"
        shadow_action = "PREPARE_ONLY"
        micro_state = "REDUCED"
        micro_multiplier = 0.50
        shadow_block = True
    else:
        state = "NORMAL"
        shadow_action = "NO_SHADOW_BLOCK"
        micro_state = "FULL_RESEARCH_WEIGHT"
        micro_multiplier = 1.0
        shadow_block = False

    last_shock = recent_shocks[-1] if recent_shocks else None
    return {
        "contract": CONTRACT,
        "state": state,
        "shadow_action": shadow_action,
        "shadow_aggressive_entry_block_recommended": shadow_block,
        "shadow_microstructure_authority_state": micro_state,
        "recommended_micro_authority_multiplier": micro_multiplier,
        "effective_execution_block": False,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "direction_engine_influence": False,
        "closed_m5_bars": len(closed),
        "baseline_bars": int(baseline_bars),
        "recent_shock_bars": RECENT_SHOCK_BARS,
        "stabilization_bars_required": STABILIZATION_BARS,
        "stable_completed_m5_run": stable_run,
        "latest_completed_m5": latest,
        "last_recent_shock": last_shock,
        "recent_completed_m5": list(metrics[-10:]),
        "thresholds": {
            "range_elevated_ratio": RANGE_ELEVATED_RATIO,
            "range_shock_ratio": RANGE_SHOCK_RATIO,
            "spread_elevated_ratio": SPREAD_ELEVATED_RATIO,
            "spread_shock_ratio": SPREAD_SHOCK_RATIO,
            "vacuum_range_ratio": VACUUM_RANGE_RATIO,
            "vacuum_tick_ratio_max": VACUUM_TICK_RATIO,
            "vacuum_body_fraction_min": VACUUM_BODY_FRACTION,
            "recovery_range_ratio_max": RECOVERY_RANGE_RATIO,
            "recovery_spread_ratio_max": RECOVERY_SPREAD_RATIO,
            "recovery_tick_ratio_min": RECOVERY_MIN_TICK_RATIO,
        },
        "data_quality": {
            "spread_signal_available": latest.get("spread_ratio") is not None,
            "liquidity_vacuum_is_proxy_not_dom_depth": True,
            "completed_m5_only": True,
            "current_unfinished_m5_excluded": True,
            "baseline_excludes_evaluation_bar": True,
        },
        "interpretation": (
            "V203 is a direction-agnostic shadow guard. It detects abnormal completed-M5 "
            "range expansion, spread expansion when spread data is available, and a "
            "liquidity-vacuum proxy based on large directional range with unusually low "
            "tick participation. SHOCK/STABILIZING/ELEVATED can recommend OBSERVE/PREPARE "
            "and reduced microstructure weight, but this worker has no execution or "
            "promotion authority and does not modify the direction engine."
        ),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V203_VOLATILITY_SHOCK_GUARD_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V203_VOLATILITY_SHOCK_GUARD_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    feed = build_ctrader_research_feed(policy, (SYMBOL,))
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    bars: tuple[Bar, ...] = ()
    evaluation: dict[str, Any] = {}
    error: str | None = None

    try:
        feed.ensure_connected()
        raw = tuple(
            feed.historical_bars(
                SYMBOL,
                "M5",
                from_time=cutoff,
                to_time=now,
                count=REQUEST_COUNT,
            )
        )
        bars = _closed_m5(raw, as_of=now)
        evaluation = evaluate_volatility_shock_guard(bars, as_of=now)
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
    finally:
        try:
            feed.close()
        except Exception:
            pass

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            **evaluation,
            "environment": "DEMO",
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V203_VOLATILITY_SHOCK_GUARD "
        f"healthy={healthy} state={evaluation.get('state', 'ERROR')} "
        f"shadow_action={evaluation.get('shadow_action', 'OBSERVE_ONLY')} "
        f"bars={evaluation.get('closed_m5_bars', len(bars))} "
        f"error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
