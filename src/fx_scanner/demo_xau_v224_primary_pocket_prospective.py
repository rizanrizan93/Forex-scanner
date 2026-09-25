from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from math import isfinite
import os
from statistics import median
from typing import Any, Sequence

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .research_xau_zone_path_v174 import wilson_lower_bound
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_v224_primary_pocket_prospective"
CONTRACT = "XAU_M5_PRIMARY_POCKET_PROSPECTIVE_V224"
SOURCE_WORKER = "ctrader_demo_xau_v223_m5_pocket_cluster_selector"
FORECAST_EVENT = "DEMO_XAU_M5_PRIMARY_FORECAST_V224"
OUTCOME_EVENT = "DEMO_XAU_M5_PRIMARY_OUTCOME_V224"
FORECAST_CODE = "XAU_M5_PRIMARY_FORECAST_V224"
OUTCOME_CODE = "XAU_M5_PRIMARY_OUTCOME_V224"
ACCOUNT_ID = "OBSERVABILITY"

LOOKBACK_DAYS = 14
REQUEST_COUNT = 4000
TOUCH_HORIZON_HOURS = 4
REACTION_HORIZON_BARS = 24
ATR_RUNGS = (0.25, 0.50, 0.75, 1.00)
MAX_EVENT_ROWS = 4000


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _latest_heartbeat(
    store: SupabaseOperationalStore,
    worker_name: str,
) -> dict[str, Any]:
    response = (
        store.client.table("runtime_heartbeats")
        .select("observed_at,healthy,details")
        .eq("worker_name", worker_name)
        .order("observed_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = list(response.data or [])
    return {} if not rows else dict(rows[0])


def _stable_signal_key(
    *,
    direction: str,
    first_mapped_at: str,
) -> str:
    # Identity is the physical micro-wave, not the current H1 parent.
    # Parent maps can legitimately change while the selected M5 pocket family
    # remains the same; using parent_zone_id would double-count one forecast.
    raw = "|".join((CONTRACT, direction, first_mapped_at))
    return "V224:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _micro_wave_key(
    payload: dict[str, Any],
    *,
    fallback: str = "",
) -> str:
    direction = str(payload.get("direction") or "").upper()
    cluster = dict(payload.get("cluster") or {})
    first_mapped_at = str(cluster.get("first_mapped_at") or "")
    if direction in {"LONG", "SHORT"} and first_mapped_at:
        return _stable_signal_key(
            direction=direction,
            first_mapped_at=first_mapped_at,
        )
    return str(fallback or payload.get("signal_key") or "")


def _forecast_candidate(source_heartbeat: dict[str, Any]) -> dict[str, Any]:
    if not bool(source_heartbeat.get("healthy")):
        return {}
    forecast_at = _dt(source_heartbeat.get("observed_at"))
    details = dict(source_heartbeat.get("details") or {})
    evaluation = dict(details.get("evaluation") or {})
    primary = dict(evaluation.get("primary_cluster") or {})
    parent = dict(evaluation.get("parent_context") or {})
    if forecast_at is None or not primary:
        return {}

    direction = str(primary.get("direction") or evaluation.get("direction") or "").upper()
    role = str(primary.get("role") or "")
    union = dict(primary.get("union_zone") or {})
    core = dict(primary.get("consensus_core") or {})
    selected = core if core else union

    low = _f(selected.get("low"))
    high = _f(selected.get("high"))
    price = _f(primary.get("price_reference") or evaluation.get("price_reference"))
    atr = _f(parent.get("atr_points"))
    first_mapped_at = str(primary.get("first_mapped_at") or "")
    parent_zone_id = str(parent.get("zone_id") or "NO_PARENT_ZONE")

    if (
        direction not in {"LONG", "SHORT"}
        or role != "ACTIVE_WATCH_CLUSTER"
        or low is None
        or high is None
        or high < low
        or price is None
        or atr is None
        or atr <= 0
        or not first_mapped_at
        or int(primary.get("post_map_touch_member_count") or 0) > 0
    ):
        return {}

    # Strict prospective enrollment: price must still be outside the selected
    # pocket on the approach side. Inside-zone or already-passed geometry is
    # not a clean first-touch forecast.
    if direction == "SHORT":
        clean_pre_touch = price < low
        proximal = low
        parent_distal = _f(parent.get("high"))
    else:
        clean_pre_touch = price > high
        proximal = high
        parent_distal = _f(parent.get("low"))
    if not clean_pre_touch:
        return {}

    signal_key = _stable_signal_key(
        direction=direction,
        first_mapped_at=first_mapped_at,
    )
    return {
        "contract": CONTRACT,
        "signal_key": signal_key,
        "forecast_at": forecast_at.isoformat(),
        "forecast_timing": "PRIMARY_CLUSTER_PRE_TOUCH_NO_LEAKAGE",
        "direction": direction,
        "selected_zone": {
            "low": low,
            "high": high,
            "source": "CONSENSUS_CORE" if core else "UNION_ZONE",
            "proximal": proximal,
        },
        "cluster": {
            "cluster_id": primary.get("cluster_id"),
            "role": role,
            "first_mapped_at": first_mapped_at,
            "latest_mapped_at": primary.get("latest_mapped_at"),
            "count": primary.get("count"),
            "selector_score_research": primary.get("selector_score_research"),
            "mean_quality_research": primary.get("mean_quality_research"),
            "max_quality_research": primary.get("max_quality_research"),
            "distance_atr": primary.get("distance_atr"),
            "member_signal_keys": [
                dict(item).get("signal_key")
                for item in list(primary.get("members") or [])
                if dict(item).get("signal_key")
            ],
        },
        "parent": {
            "zone_id": parent_zone_id,
            "timeframe": parent.get("timeframe"),
            "low": parent.get("low"),
            "high": parent.get("high"),
            "distal": parent_distal,
            "atr_points": atr,
            "freshness": parent.get("freshness"),
            "research_score": parent.get("research_score"),
        },
        "price_at_forecast": price,
        "source_code_version": details.get("code_version"),
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _ceil_next_m5(value: datetime) -> datetime:
    ts = ensure_utc(value)
    minute = (ts.minute // 5) * 5
    floor = ts.replace(minute=minute, second=0, microsecond=0)
    return floor if ts == floor else floor + timedelta(minutes=5)


def _closed_m5(rows: Sequence[Bar], *, as_of: datetime) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(tuple(rows), key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=5) <= now
    )


def _invalidated(row: Bar, *, direction: str, distal: float | None) -> bool:
    if distal is None:
        return False
    if direction == "LONG":
        return float(row.close) < distal
    return float(row.close) > distal


def _touches(row: Bar, *, low: float, high: float) -> bool:
    return float(row.low) <= high and float(row.high) >= low


def _threshold_price(
    *,
    direction: str,
    proximal: float,
    atr: float,
    multiple: float,
) -> float:
    distance = atr * multiple
    return proximal + distance if direction == "LONG" else proximal - distance


def evaluate_primary_outcome(
    bars: Sequence[Bar],
    *,
    forecast: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    forecast_at = _dt(forecast.get("forecast_at"))
    zone = dict(forecast.get("selected_zone") or {})
    parent = dict(forecast.get("parent") or {})
    direction = str(forecast.get("direction") or "").upper()
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    proximal = _f(zone.get("proximal"))
    atr = _f(parent.get("atr_points"))
    distal = _f(parent.get("distal"))

    if (
        forecast_at is None
        or direction not in {"LONG", "SHORT"}
        or low is None
        or high is None
        or proximal is None
        or atr is None
        or atr <= 0
    ):
        raise ValueError("V224_FORECAST_GEOMETRY_INVALID")

    start = _ceil_next_m5(forecast_at)
    touch_deadline = forecast_at + timedelta(hours=TOUCH_HORIZON_HOURS)
    closed = _closed_m5(bars, as_of=now)
    eligible = [
        row
        for row in closed
        if start <= ensure_utc(row.timestamp) <= min(ensure_utc(now), touch_deadline)
    ]

    touch_index: int | None = None
    for index, row in enumerate(eligible):
        if _touches(row, low=low, high=high):
            touch_index = index
            break

    if touch_index is None:
        return {
            "status": "NO_TOUCH" if ensure_utc(now) >= touch_deadline else "PENDING_TOUCH",
            "touch_at": None,
            "outcome_at": touch_deadline.isoformat() if ensure_utc(now) >= touch_deadline else None,
            "rungs": {},
            "invalidated": False,
        }

    touch_row = eligible[touch_index]
    touch_at = ensure_utc(touch_row.timestamp)
    if _invalidated(touch_row, direction=direction, distal=distal):
        return {
            "status": "INVALIDATED_ON_TOUCH_BAR",
            "touch_at": touch_at.isoformat(),
            "outcome_at": touch_at.isoformat(),
            "rungs": {},
            "invalidated": True,
        }

    levels = {
        f"{multiple:.2f}": _threshold_price(
            direction=direction,
            proximal=proximal,
            atr=atr,
            multiple=multiple,
        )
        for multiple in ATR_RUNGS
    }
    hits: dict[str, dict[str, Any]] = {
        key: {"hit": False, "first_hit_at": None, "minutes_from_touch": None, "price": price}
        for key, price in levels.items()
    }

    future_all = [
        row for row in closed
        if ensure_utc(row.timestamp) > touch_at
    ]
    future = future_all[:REACTION_HORIZON_BARS]
    for offset, row in enumerate(future, start=1):
        ts = ensure_utc(row.timestamp)
        # Conservative precedence: invalidation wins over a target/rung on the
        # same completed M5 bar.
        if _invalidated(row, direction=direction, distal=distal):
            return {
                "status": "INVALIDATED_AFTER_TOUCH",
                "touch_at": touch_at.isoformat(),
                "outcome_at": ts.isoformat(),
                "bars_after_touch": offset,
                "rungs": hits,
                "invalidated": True,
            }

        for key, price in levels.items():
            if hits[key]["hit"]:
                continue
            crossed = (
                float(row.high) >= price
                if direction == "LONG"
                else float(row.low) <= price
            )
            if crossed:
                hits[key] = {
                    "hit": True,
                    "first_hit_at": ts.isoformat(),
                    "minutes_from_touch": (ts - touch_at).total_seconds() / 60.0,
                    "price": price,
                }

    if len(future) < REACTION_HORIZON_BARS:
        return {
            "status": "PENDING_REACTION",
            "touch_at": touch_at.isoformat(),
            "outcome_at": None,
            "rungs": hits,
            "invalidated": False,
        }

    outcome_at = ensure_utc(future[-1].timestamp)
    return {
        "status": "REACTION_WINDOW_COMPLETE",
        "touch_at": touch_at.isoformat(),
        "outcome_at": outcome_at.isoformat(),
        "bars_after_touch": REACTION_HORIZON_BARS,
        "rungs": hits,
        "invalidated": False,
    }


def _events(store: SupabaseOperationalStore) -> list[dict[str, Any]]:
    cutoff = datetime.now(tz=UTC) - timedelta(days=LOOKBACK_DAYS)
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,event_type,signal_key,payload")
        .eq("backend", "CTRADER")
        .eq("account_id", ACCOUNT_ID)
        .in_("event_type", [FORECAST_EVENT, OUTCOME_EVENT])
        .gte("observed_at", cutoff.isoformat())
        .order("observed_at", desc=False)
        .limit(MAX_EVENT_ROWS)
        .execute()
    )
    return [dict(row) for row in list(response.data or [])]


def _index_events(
    rows: Sequence[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    forecasts: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = dict(row.get("payload") or {})
        key = _micro_wave_key(
            payload,
            fallback=str(row.get("signal_key") or ""),
        )
        if not key:
            continue
        if str(row.get("event_type") or "") == FORECAST_EVENT and key not in forecasts:
            forecasts[key] = payload
        elif str(row.get("event_type") or "") == OUTCOME_EVENT:
            outcomes[key] = payload
    return forecasts, outcomes


def _outcome_payload(
    forecast: dict[str, Any],
    outcome: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract": CONTRACT,
        "signal_key": forecast.get("signal_key"),
        "forecast_at": forecast.get("forecast_at"),
        "direction": forecast.get("direction"),
        "selected_zone": dict(forecast.get("selected_zone") or {}),
        "cluster": dict(forecast.get("cluster") or {}),
        "parent": dict(forecast.get("parent") or {}),
        **outcome,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _rung_summary(
    outcomes: Sequence[dict[str, Any]],
    *,
    key: str,
) -> dict[str, Any]:
    touched_resolved = [
        row for row in outcomes
        if row.get("touch_at")
        and str(row.get("status") or "") not in {"PENDING_REACTION"}
    ]
    hits = sum(bool(dict(row.get("rungs") or {}).get(key, {}).get("hit")) for row in touched_resolved)
    n = len(touched_resolved)
    return {
        "n": n,
        "hits": hits,
        "rate": None if n == 0 else hits / n,
        "wilson_lower_95": None if n == 0 else wilson_lower_bound(hits, n),
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    forecasts, outcomes_map = _index_events(rows)
    outcomes = list(outcomes_map.values())
    no_touch = [row for row in outcomes if str(row.get("status") or "") == "NO_TOUCH"]
    touched_resolved = [
        row for row in outcomes
        if row.get("touch_at")
        and str(row.get("status") or "") != "PENDING_REACTION"
    ]
    pending = max(0, len(forecasts) - len(outcomes_map))

    forecast_to_touch = []
    touch_to_050 = []
    for row in touched_resolved:
        forecast_at = _dt(row.get("forecast_at"))
        touch_at = _dt(row.get("touch_at"))
        if forecast_at is not None and touch_at is not None:
            forecast_to_touch.append((touch_at - forecast_at).total_seconds() / 60.0)
        rung = dict(dict(row.get("rungs") or {}).get("0.50") or {})
        minutes = _f(rung.get("minutes_from_touch"))
        if minutes is not None:
            touch_to_050.append(minutes)

    resolved_n = len(touched_resolved)
    return {
        "contract": CONTRACT,
        "forecasts": len(forecasts),
        "resolved_after_touch": resolved_n,
        "no_touch": len(no_touch),
        "pending": pending,
        "hit_025": _rung_summary(outcomes, key="0.25"),
        "hit_050": _rung_summary(outcomes, key="0.50"),
        "hit_075": _rung_summary(outcomes, key="0.75"),
        "hit_100": _rung_summary(outcomes, key="1.00"),
        "median_forecast_to_touch_minutes": None if not forecast_to_touch else median(forecast_to_touch),
        "median_touch_to_050_minutes": None if not touch_to_050 else median(touch_to_050),
        "sample_state": (
            "COLLECTING" if resolved_n < 30
            else "EARLY" if resolved_n < 100
            else "MATURE"
        ),
        "latest_outcomes": outcomes[-20:],
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "V224 measures only V223 PRIMARY clusters enrolled while price was still outside "
            "the pocket on the correct approach side. Same-touch-bar reaction evidence is "
            "excluded; later completed M5 invalidation wins over a rung on the same bar. "
            "No execution or promotion authority."
        ),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V224_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V224_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    error: str | None = None
    forecast_written = 0
    outcome_written = 0
    candidate: dict[str, Any] = {}
    summary: dict[str, Any] = {}

    try:
        source = _latest_heartbeat(store, SOURCE_WORKER)
        candidate = _forecast_candidate(source)
        rows = _events(store)
        forecasts, outcomes = _index_events(rows)

        if candidate:
            key = str(candidate.get("signal_key") or "")
            if key and key not in forecasts:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=ACCOUNT_ID,
                    signal_key=key,
                    event_type=FORECAST_EVENT,
                    accepted=None,
                    code=FORECAST_CODE,
                    message="PRIMARY_CLUSTER_PRE_TOUCH_NO_LEAKAGE",
                    payload=candidate,
                )
                forecasts[key] = candidate
                forecast_written += 1

        unresolved = [
            payload for key, payload in forecasts.items()
            if key not in outcomes
        ]
        if unresolved:
            cutoff = now - timedelta(days=LOOKBACK_DAYS)
            feed = build_ctrader_research_feed(policy, (SYMBOL,))
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
            finally:
                try:
                    feed.close()
                except Exception:
                    pass

            for forecast in unresolved:
                outcome = evaluate_primary_outcome(
                    bars,
                    forecast=forecast,
                    now=now,
                )
                if str(outcome.get("status") or "") in {"PENDING_TOUCH", "PENDING_REACTION"}:
                    continue
                payload = _outcome_payload(forecast, outcome)
                key = str(forecast.get("signal_key") or "")
                store.record_order_event(
                    backend="CTRADER",
                    account_id=ACCOUNT_ID,
                    signal_key=key,
                    event_type=OUTCOME_EVENT,
                    accepted=None,
                    code=OUTCOME_CODE,
                    message=str(outcome.get("status") or "OUTCOME"),
                    payload=payload,
                )
                outcomes[key] = payload
                outcome_written += 1

        summary = summarize(_events(store))
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"

    healthy = error is None
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details={
            "contract": CONTRACT,
            "environment": "DEMO",
            "candidate_considered": bool(candidate),
            "forecast_written": forecast_written,
            "outcome_written": outcome_written,
            "summary": summary,
            "touch_horizon_hours": TOUCH_HORIZON_HOURS,
            "reaction_horizon_bars": REACTION_HORIZON_BARS,
            "policy_effect": "SHADOW_ONLY",
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
            "error": error,
            "code_version": os.getenv("GITHUB_SHA", "LOCAL"),
            "observed_at": now.isoformat(),
        },
    )
    print(
        "CTRADER_DEMO_XAU_V224_PRIMARY_POCKET_PROSPECTIVE "
        f"healthy={healthy} forecast_written={forecast_written} "
        f"outcome_written={outcome_written} resolved={summary.get('resolved_after_touch',0)} "
        f"error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
