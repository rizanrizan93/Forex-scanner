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
WORKER_NAME = "ctrader_demo_xau_v227_depth_map_prospective"
CONTRACT = "XAU_RIZAN_DEPTH_MAP_PROSPECTIVE_V227"
RESEARCH_VERSION = "XAU_RIZAN_DEPTH_MAP_PROSPECTIVE_V227_1"
SOURCE_WORKER = "ctrader_demo_xau_v226_rizan_depth_map"
REQUIRED_PRIOR = "XAU_ZONE_REVERSAL_DEPTH_V225_2"

FORECAST_EVENT = "DEMO_XAU_DEPTH_MAP_FORECAST_V227"
OUTCOME_EVENT = "DEMO_XAU_DEPTH_MAP_OUTCOME_V227"
FORECAST_CODE = "XAU_DEPTH_MAP_FORECAST_V227"
OUTCOME_CODE = "XAU_DEPTH_MAP_OUTCOME_V227"
ACCOUNT_ID = "OBSERVABILITY"

LOOKBACK_DAYS = 45
TOUCH_HORIZON_HOURS = 24 * 30
REACTION_HORIZON_HOURS = 16
REACTION_RUNGS = (("025", 0.25), ("050", 0.50), ("075", 0.75), ("100", 1.00))
REQUEST_COUNT = 50000
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


def _latest_heartbeat(store: SupabaseOperationalStore, worker_name: str) -> dict[str, Any]:
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


def _stable_signal_key(*, direction: str, zone_id: str) -> str:
    raw = "|".join((CONTRACT, direction, zone_id))
    return "V227:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _inside(value: float | None, geometry: dict[str, Any]) -> bool | None:
    low = _f(geometry.get("low"))
    high = _f(geometry.get("high"))
    if value is None or low is None or high is None:
        return None
    return low <= value <= high


def _layer_snapshot(direction_map: dict[str, Any], name: str) -> dict[str, Any]:
    layer = dict(direction_map.get(name) or {})
    if not layer:
        return {}
    zone = dict(layer.get("zone") or {})
    if name == "h4":
        locator = dict(layer.get("hotspot") or {})
        quantiles = dict(layer.get("quantiles") or {})
        nested = {}
    else:
        nested = dict(layer.get("nested_locator") or {})
        locator = dict(nested.get("envelope") or layer.get("hotspot") or {})
        quantiles = dict(layer.get("quantiles") or {})
    return {
        "zone": zone,
        "locator": locator,
        "quantiles": quantiles,
        "nested_locator": nested,
        "applicability": dict(layer.get("applicability") or {}),
        "historical_profile": dict(layer.get("historical_profile") or {}),
    }


def _forecast_candidate(
    source_heartbeat: dict[str, Any],
    *,
    direction: str,
) -> dict[str, Any]:
    if not bool(source_heartbeat.get("healthy")):
        return {}
    details = dict(source_heartbeat.get("details") or {})
    evaluation = dict(details.get("evaluation") or {})
    if str(evaluation.get("state") or "") != "RIZAN_DEPTH_MAP_AVAILABLE":
        return {}

    prior = dict(evaluation.get("historical_prior") or {})
    if str(prior.get("research_version") or "") != REQUIRED_PRIOR:
        return {}

    forecast_at = _dt(source_heartbeat.get("observed_at"))
    price = _f(evaluation.get("price_reference"))
    side = str(direction or "").upper()
    direction_map = dict(evaluation.get(side.lower()) or {})
    h4 = _layer_snapshot(direction_map, "h4")
    h4_zone = dict(h4.get("zone") or {})
    app = dict(h4.get("applicability") or {})

    low = _f(h4_zone.get("low"))
    high = _f(h4_zone.get("high"))
    proximal = _f(h4_zone.get("proximal"))
    distal = _f(h4_zone.get("distal"))
    atr = _f(h4_zone.get("atr_points"))
    zone_id = str(h4_zone.get("zone_id") or "")
    available_at = _dt(h4_zone.get("available_at"))
    touch_count = int(dict(h4_zone.get("lifecycle") or {}).get("touch_count") or 0)
    freshness = str(dict(h4_zone.get("lifecycle") or {}).get("freshness") or "").upper()

    if (
        forecast_at is None
        or price is None
        or side not in {"LONG", "SHORT"}
        or low is None
        or high is None
        or high <= low
        or proximal is None
        or distal is None
        or atr is None
        or atr <= 0
        or not zone_id
        or available_at is None
        or available_at > forecast_at
        or touch_count != 0
        or freshness != "FRESH"
        or str(app.get("state") or "") != "HIGH_FIRST_TOUCH_PRIOR"
    ):
        return {}

    clean_approach = price > high if side == "LONG" else price < low
    if not clean_approach:
        return {}

    h1 = _layer_snapshot(direction_map, "h1")
    m15 = _layer_snapshot(direction_map, "m15")
    signal_key = _stable_signal_key(direction=side, zone_id=zone_id)

    return {
        "contract": CONTRACT,
        "research_version": RESEARCH_VERSION,
        "signal_key": signal_key,
        "forecast_at": forecast_at.isoformat(),
        "forecast_timing": "FRESH_H4_PRE_TOUCH_CORRECT_SIDE",
        "direction": side,
        "price_at_forecast": price,
        "h4": h4,
        "h1": h1,
        "m15": m15,
        "parent": {
            "zone_id": zone_id,
            "low": low,
            "high": high,
            "proximal": proximal,
            "distal": distal,
            "atr_points": atr,
            "available_at": available_at.isoformat(),
        },
        "source": {
            "v226_code_version": details.get("code_version"),
            "v225_research_version": prior.get("research_version"),
            "v225_year_count": prior.get("year_count"),
            "v225_episode_count": prior.get("episode_count"),
        },
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _closed_m1(rows: Sequence[Bar], *, now: datetime) -> tuple[Bar, ...]:
    cutoff = ensure_utc(now)
    return tuple(
        row
        for row in sorted(tuple(rows), key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=1) <= cutoff
    )


def _touches(row: Bar, *, low: float, high: float) -> bool:
    return float(row.low) <= high and float(row.high) >= low


def _invalidated(row: Bar, *, direction: str, distal: float) -> bool:
    return float(row.close) < distal if direction == "LONG" else float(row.close) > distal


def _reaction_target(*, direction: str, proximal: float, atr: float) -> float:
    move = 0.50 * atr
    return proximal + move if direction == "LONG" else proximal - move


def _reaction_targets(*, direction: str, proximal: float, atr: float) -> dict[str, float]:
    sign = 1.0 if direction == "LONG" else -1.0
    return {
        key: proximal + sign * multiple * atr
        for key, multiple in REACTION_RUNGS
    }


def _reaction_flags(hits: dict[str, bool]) -> dict[str, Any]:
    return {
        "reaction_hit_025": bool(hits.get("025")),
        "reaction_hit_050": bool(hits.get("050")),
        "reaction_hit_075": bool(hits.get("075")),
        "reaction_hit_100": bool(hits.get("100")),
        "reaction_rungs": {
            "0.25": bool(hits.get("025")),
            "0.50": bool(hits.get("050")),
            "0.75": bool(hits.get("075")),
            "1.00": bool(hits.get("100")),
        },
    }


def _full_depth(*, direction: str, low: float, high: float, price: float) -> float:
    width = max(high - low, 1e-12)
    return (high - price) / width if direction == "LONG" else (price - low) / width


def _depth_band(depth: float | None) -> str | None:
    if depth is None:
        return None
    if depth < 0:
        return "BEFORE_NEAR_EDGE"
    if depth >= 1:
        return "100%+"
    lower = int(depth * 10) * 10
    return f"{lower:02d}-{lower + 10:02d}%"


def _capture_payload(
    forecast: dict[str, Any],
    *,
    turning_price: float | None,
    turning_depth: float | None,
) -> dict[str, Any]:
    if turning_price is None or turning_depth is None:
        return {
            "turning_price": None,
            "turning_depth": None,
            "turning_depth_band": None,
            "h4_hotspot_capture": None,
            "h4_iqr_capture": None,
            "h4_median_abs_depth_error": None,
            "h1_locator_capture": None,
            "m15_locator_capture": None,
        }

    h4 = dict(forecast.get("h4") or {})
    h1 = dict(forecast.get("h1") or {})
    m15 = dict(forecast.get("m15") or {})
    h4_quantiles = dict(h4.get("quantiles") or {})
    median_depth = _f(dict(h4_quantiles.get("median") or {}).get("depth"))
    p25_depth = _f(dict(h4_quantiles.get("p25") or {}).get("depth"))
    p75_depth = _f(dict(h4_quantiles.get("p75") or {}).get("depth"))
    in_iqr = (
        None
        if p25_depth is None or p75_depth is None
        else p25_depth <= turning_depth <= p75_depth
    )
    return {
        "turning_price": turning_price,
        "turning_depth": turning_depth,
        "turning_depth_band": _depth_band(turning_depth),
        "h4_hotspot_capture": _inside(turning_price, dict(h4.get("locator") or {})),
        "h4_iqr_capture": in_iqr,
        "h4_median_abs_depth_error": (
            None if median_depth is None else abs(turning_depth - median_depth)
        ),
        "h1_locator_capture": _inside(turning_price, dict(h1.get("locator") or {})),
        "m15_locator_capture": _inside(turning_price, dict(m15.get("locator") or {})),
    }


def evaluate_outcome(
    bars: Sequence[Bar],
    *,
    forecast: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    forecast_at = _dt(forecast.get("forecast_at"))
    parent = dict(forecast.get("parent") or {})
    direction = str(forecast.get("direction") or "").upper()
    low = _f(parent.get("low"))
    high = _f(parent.get("high"))
    proximal = _f(parent.get("proximal"))
    distal = _f(parent.get("distal"))
    atr = _f(parent.get("atr_points"))
    if (
        forecast_at is None
        or direction not in {"LONG", "SHORT"}
        or None in {low, high, proximal, distal, atr}
        or float(high) <= float(low)
        or float(atr) <= 0
    ):
        raise ValueError("V227_FORECAST_GEOMETRY_INVALID")

    closed = _closed_m1(bars, now=now)
    start = forecast_at
    touch_deadline = forecast_at + timedelta(hours=TOUCH_HORIZON_HOURS)
    eligible = [
        row for row in closed
        if start <= ensure_utc(row.timestamp) <= min(ensure_utc(now), touch_deadline)
    ]
    empty_hits = {key: False for key, _ in REACTION_RUNGS}

    touch_index: int | None = None
    for idx, row in enumerate(eligible):
        if _touches(row, low=float(low), high=float(high)):
            touch_index = idx
            break
        if _invalidated(row, direction=direction, distal=float(distal)):
            return {
                "status": "INVALIDATED_BEFORE_TOUCH",
                "touch_at": None,
                "outcome_at": ensure_utc(row.timestamp).isoformat(),
                **_reaction_flags(empty_hits),
                "invalidated": True,
            }

    if touch_index is None:
        return {
            "status": "NO_TOUCH" if ensure_utc(now) >= touch_deadline else "PENDING_TOUCH",
            "touch_at": None,
            "outcome_at": touch_deadline.isoformat() if ensure_utc(now) >= touch_deadline else None,
            **_reaction_flags(empty_hits),
            "invalidated": False,
        }

    touch_row = eligible[touch_index]
    touch_at = ensure_utc(touch_row.timestamp)
    adverse = (
        min(float(high), float(touch_row.low))
        if direction == "LONG"
        else max(float(low), float(touch_row.high))
    )
    max_depth = _full_depth(
        direction=direction,
        low=float(low),
        high=float(high),
        price=adverse,
    )

    if _invalidated(touch_row, direction=direction, distal=float(distal)):
        return {
            "status": "INVALIDATED_ON_TOUCH_BAR",
            "touch_at": touch_at.isoformat(),
            "outcome_at": touch_at.isoformat(),
            **_reaction_flags(empty_hits),
            "invalidated": True,
            "max_depth_reached": max_depth,
            **_capture_payload(forecast, turning_price=None, turning_depth=None),
        }

    targets = _reaction_targets(
        direction=direction,
        proximal=float(proximal),
        atr=float(atr),
    )
    hits = {key: False for key, _ in REACTION_RUNGS}
    turning_price_050: float | None = None
    turning_depth_050: float | None = None
    reaction_deadline = touch_at + timedelta(hours=REACTION_HORIZON_HOURS)
    future = [
        row for row in closed
        if touch_at < ensure_utc(row.timestamp) <= reaction_deadline
    ]

    for offset, row in enumerate(future, start=1):
        ts = ensure_utc(row.timestamp)

        # Conservative precedence: a close beyond distal invalidates the bar
        # before any reaction rung printed inside the same M1 candle is credited.
        if _invalidated(row, direction=direction, distal=float(distal)):
            if direction == "LONG":
                adverse = min(adverse, float(row.low))
            else:
                adverse = max(adverse, float(row.high))
            max_depth = max(
                max_depth,
                _full_depth(
                    direction=direction,
                    low=float(low),
                    high=float(high),
                    price=adverse,
                ),
            )
            return {
                "status": "INVALIDATED_AFTER_TOUCH",
                "touch_at": touch_at.isoformat(),
                "outcome_at": ts.isoformat(),
                "bars_after_touch": offset,
                **_reaction_flags(hits),
                "invalidated": True,
                "max_depth_reached": max_depth,
                **_capture_payload(
                    forecast,
                    turning_price=turning_price_050,
                    turning_depth=turning_depth_050,
                ),
            }

        for key, _multiple in REACTION_RUNGS:
            target = targets[key]
            reached = (
                float(row.high) >= target
                if direction == "LONG"
                else float(row.low) <= target
            )
            if not reached or hits[key]:
                continue
            hits[key] = True
            if key == "050" and turning_depth_050 is None:
                # Match V225.2: use the deepest adverse extreme known before
                # the first 0.50 ATR target bar. The target bar's new adverse
                # extreme is excluded because intrabar ordering is unknown.
                turning_price_050 = adverse
                turning_depth_050 = _full_depth(
                    direction=direction,
                    low=float(low),
                    high=float(high),
                    price=turning_price_050,
                )

        if hits["100"]:
            return {
                "status": "REACTION_100",
                "touch_at": touch_at.isoformat(),
                "outcome_at": ts.isoformat(),
                "bars_after_touch": offset,
                **_reaction_flags(hits),
                "invalidated": False,
                "max_depth_reached": max(max_depth, turning_depth_050 or max_depth),
                **_capture_payload(
                    forecast,
                    turning_price=turning_price_050,
                    turning_depth=turning_depth_050,
                ),
            }

        # Only after rung detection do we admit this bar's adverse extreme into
        # the path state, so a target bar cannot improve its own turning depth.
        if direction == "LONG":
            adverse = min(adverse, float(row.low))
        else:
            adverse = max(adverse, float(row.high))
        max_depth = max(
            max_depth,
            _full_depth(
                direction=direction,
                low=float(low),
                high=float(high),
                price=adverse,
            ),
        )

    if ensure_utc(now) < reaction_deadline:
        return {
            "status": "PENDING_REACTION",
            "touch_at": touch_at.isoformat(),
            "outcome_at": None,
            **_reaction_flags(hits),
            "invalidated": False,
            "max_depth_reached": max_depth,
            **_capture_payload(
                forecast,
                turning_price=turning_price_050,
                turning_depth=turning_depth_050,
            ),
        }

    terminal_status = (
        "REACTION_075_16H" if hits["075"]
        else "REACTION_050_16H" if hits["050"]
        else "REACTION_025_16H" if hits["025"]
        else "STALL_16H"
    )
    return {
        "status": terminal_status,
        "touch_at": touch_at.isoformat(),
        "outcome_at": reaction_deadline.isoformat(),
        **_reaction_flags(hits),
        "invalidated": False,
        "max_depth_reached": max_depth,
        **_capture_payload(
            forecast,
            turning_price=turning_price_050,
            turning_depth=turning_depth_050,
        ),
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
        key = str(row.get("signal_key") or "")
        payload = dict(row.get("payload") or {})
        if not key:
            key = str(payload.get("signal_key") or "")
        if not key:
            continue
        event_type = str(row.get("event_type") or "")
        if event_type == FORECAST_EVENT and key not in forecasts:
            forecasts[key] = payload
        elif event_type == OUTCOME_EVENT:
            outcomes[key] = payload
    return forecasts, outcomes


def _metric(rows: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    eligible = [row for row in rows if row.get(key) is not None]
    hits = sum(bool(row.get(key)) for row in eligible)
    n = len(eligible)
    return {
        "n": n,
        "hits": hits,
        "rate": None if n == 0 else hits / n,
        "wilson_lower_95": None if n == 0 else wilson_lower_bound(hits, n),
    }


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    forecasts, outcomes_map = _index_events(rows)
    outcomes = list(outcomes_map.values())
    resolved_touch = [
        row for row in outcomes
        if row.get("touch_at") and str(row.get("status") or "") not in {"PENDING_TOUCH", "PENDING_REACTION"}
    ]
    reactions_025 = [row for row in resolved_touch if bool(row.get("reaction_hit_025"))]
    reactions_050 = [row for row in resolved_touch if bool(row.get("reaction_hit_050"))]
    reactions_075 = [row for row in resolved_touch if bool(row.get("reaction_hit_075"))]
    reactions_100 = [row for row in resolved_touch if bool(row.get("reaction_hit_100"))]
    no_touch = [row for row in outcomes if str(row.get("status") or "") == "NO_TOUCH"]

    errors = [
        float(row["h4_median_abs_depth_error"])
        for row in reactions_050
        if _f(row.get("h4_median_abs_depth_error")) is not None
    ]
    depths = [
        float(row["turning_depth"])
        for row in reactions_050
        if _f(row.get("turning_depth")) is not None
    ]
    reaction_n = len(resolved_touch)

    def rung_metric(rows_for_rung: Sequence[dict[str, Any]]) -> dict[str, Any]:
        hits = len(rows_for_rung)
        return {
            "n": reaction_n,
            "hits": hits,
            "rate": None if reaction_n == 0 else hits / reaction_n,
            "wilson_lower_95": (
                None if reaction_n == 0
                else wilson_lower_bound(hits, reaction_n)
            ),
        }

    return {
        "contract": CONTRACT,
        "research_version": RESEARCH_VERSION,
        "forecasts": len(forecasts),
        "resolved_after_touch": reaction_n,
        "no_touch": len(no_touch),
        "pending": max(0, len(forecasts) - len(outcomes_map)),
        "reaction_025": rung_metric(reactions_025),
        "reaction_050": rung_metric(reactions_050),
        "reaction_075": rung_metric(reactions_075),
        "reaction_100": rung_metric(reactions_100),
        "h4_hotspot_capture_given_reaction_050": _metric(reactions_050, "h4_hotspot_capture"),
        "h4_iqr_capture_given_reaction_050": _metric(reactions_050, "h4_iqr_capture"),
        "h1_locator_capture_given_reaction_050": _metric(reactions_050, "h1_locator_capture"),
        "m15_locator_capture_given_reaction_050": _metric(reactions_050, "m15_locator_capture"),
        # Backward-compatible aliases for the original V227 dashboard/readers.
        "h4_hotspot_capture_given_reaction": _metric(reactions_050, "h4_hotspot_capture"),
        "h4_iqr_capture_given_reaction": _metric(reactions_050, "h4_iqr_capture"),
        "h1_locator_capture_given_reaction": _metric(reactions_050, "h1_locator_capture"),
        "m15_locator_capture_given_reaction": _metric(reactions_050, "m15_locator_capture"),
        "median_turning_depth": None if not depths else median(depths),
        "median_h4_depth_error": None if not errors else median(errors),
        "turning_depth_contract": "DEEPEST_ADVERSE_M1_EXTREME_BEFORE_FIRST_050_TARGET_BAR",
        "sample_state": (
            "COLLECTING" if reaction_n < 30
            else "EARLY" if reaction_n < 100
            else "MATURE"
        ),
        "latest_outcomes": outcomes[-20:],
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "V227.1 prospectively validates immutable V226 maps only for fresh untouched "
            "H4 zones while price remains outside on the correct approach side. It scores "
            "0.25/0.50/0.75/1.00 ATR reaction rungs, keeps invalidation precedence, and "
            "measures turning depth on the historical 0.50 ATR contract plus H4 hotspot/IQR "
            "and nested H1/M15 locator capture. No execution or promotion authority."
        ),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V227_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V227_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    error: str | None = None
    written_forecasts = 0
    written_outcomes = 0
    summary: dict[str, Any] = {}
    candidate_directions: list[str] = []

    try:
        source = _latest_heartbeat(store, SOURCE_WORKER)
        rows = _events(store)
        forecasts, outcomes = _index_events(rows)

        for direction in ("LONG", "SHORT"):
            candidate = _forecast_candidate(source, direction=direction)
            if not candidate:
                continue
            candidate_directions.append(direction)
            key = str(candidate.get("signal_key") or "")
            if key and key not in forecasts:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=ACCOUNT_ID,
                    signal_key=key,
                    event_type=FORECAST_EVENT,
                    accepted=None,
                    code=FORECAST_CODE,
                    message="FRESH_H4_PRE_TOUCH_CORRECT_SIDE",
                    payload=candidate,
                )
                forecasts[key] = candidate
                written_forecasts += 1

        unresolved = [
            payload for key, payload in forecasts.items()
            if key not in outcomes
        ]
        if unresolved:
            earliest = min(
                (_dt(item.get("forecast_at")) for item in unresolved),
                default=None,
            )
            if earliest is not None:
                feed = build_ctrader_research_feed(policy, (SYMBOL,))
                try:
                    feed.ensure_connected()
                    raw = tuple(
                        feed.historical_bars(
                            SYMBOL,
                            "M1",
                            from_time=max(
                                earliest - timedelta(minutes=5),
                                now - timedelta(days=LOOKBACK_DAYS),
                            ),
                            to_time=now,
                            count=REQUEST_COUNT,
                        )
                    )
                finally:
                    try:
                        feed.close()
                    except Exception:
                        pass

                for forecast in unresolved:
                    outcome = evaluate_outcome(raw, forecast=forecast, now=now)
                    if str(outcome.get("status") or "") in {"PENDING_TOUCH", "PENDING_REACTION"}:
                        continue
                    payload = {
                        "contract": CONTRACT,
                        "research_version": RESEARCH_VERSION,
                        "signal_key": forecast.get("signal_key"),
                        "forecast_at": forecast.get("forecast_at"),
                        "direction": forecast.get("direction"),
                        "parent": dict(forecast.get("parent") or {}),
                        "h4": dict(forecast.get("h4") or {}),
                        "h1": dict(forecast.get("h1") or {}),
                        "m15": dict(forecast.get("m15") or {}),
                        **outcome,
                        "execution_influence": False,
                        "execution_authority": False,
                        "promotion_authority": False,
                    }
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
                    written_outcomes += 1

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
            "research_version": RESEARCH_VERSION,
            "environment": "DEMO",
            "required_prior": REQUIRED_PRIOR,
            "candidate_directions": candidate_directions,
            "forecast_written": written_forecasts,
            "outcome_written": written_outcomes,
            "summary": summary,
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
        "CTRADER_DEMO_XAU_V227_DEPTH_MAP_PROSPECTIVE "
        f"healthy={healthy} candidates={candidate_directions} "
        f"forecast_written={written_forecasts} outcome_written={written_outcomes} "
        f"sample={summary.get('sample_state','NONE')} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
