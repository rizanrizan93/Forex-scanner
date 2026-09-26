from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from math import isfinite
import os
from typing import Any, Sequence

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_v232_v231_prospective_shadow"
CONTRACT = "XAU_V231_PROSPECTIVE_SHADOW_V232"
RESEARCH_VERSION = "XAU_V231_PROSPECTIVE_SHADOW_V232_1"
SOURCE_WORKER = "ctrader_demo_xau_v226_rizan_depth_map"
ATLAS_WORKER = "ctrader_demo_xau_supply_demand_atlas_v182"

FORECAST_EVENT = "DEMO_XAU_V231_SHADOW_FORECAST_V232"
OUTCOME_EVENT = "DEMO_XAU_V231_SHADOW_OUTCOME_V232"
FORECAST_CODE = "XAU_V231_SHADOW_FORECAST_V232"
OUTCOME_CODE = "XAU_V231_SHADOW_OUTCOME_V232"
ACCOUNT_ID = "OBSERVABILITY"

ALLOWED_SOURCES = {"H1_NESTED_LOCATOR", "M15_NESTED_LOCATOR"}
TARGET_SOURCE = "ATLAS_TERMINAL_OPPOSING_ZONE"
H4_STOP_BUFFER_ATR = 0.15
MIN_RR = 1.0
ENTRY_HORIZON_HOURS = 24 * 30
MAX_HOLD_HOURS = 16
LOOKBACK_DAYS = 365
REQUEST_COUNT = 50000
MAX_EVENT_ROWS = 8000
FRICTIONS = (0.0, 0.5, 1.0)
MIN_VALIDATION_ORDERS = 30


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


def _stable_signal_key(*, h4_zone_id: str, slot: str) -> str:
    raw = "|".join((CONTRACT, h4_zone_id, slot))
    return "V232:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _terminal_target(
    atlas_evaluation: dict[str, Any],
    *,
    direction: str,
) -> float | None:
    path = dict(
        dict(atlas_evaluation.get("path_map") or {}).get(
            "demand_to_supply" if direction == "LONG" else "supply_to_demand"
        )
        or {}
    )
    terminal = dict(path.get("terminal_target_zone") or {})
    return _f(terminal.get("low" if direction == "LONG" else "high"))


def build_shadow_forecasts(
    *,
    source_heartbeat: dict[str, Any],
    atlas_heartbeat: dict[str, Any],
) -> list[dict[str, Any]]:
    if not bool(source_heartbeat.get("healthy")) or not bool(atlas_heartbeat.get("healthy")):
        return []

    source_details = dict(source_heartbeat.get("details") or {})
    source_eval = dict(source_details.get("evaluation") or {})
    atlas_details = dict(atlas_heartbeat.get("details") or {})
    atlas_eval = dict(atlas_details.get("evaluation") or {})
    observed_at = _dt(source_heartbeat.get("observed_at"))
    direction = str(source_eval.get("focus_direction") or "").upper()
    candidate = dict(source_eval.get("depth_entry_candidate") or {})

    if (
        observed_at is None
        or direction not in {"LONG", "SHORT"}
        or str(source_eval.get("state") or "") != "RIZAN_DEPTH_MAP_AVAILABLE"
        or str(candidate.get("source_layer") or "") not in ALLOWED_SOURCES
        or not bool(candidate.get("calibrated_fresh_first_touch"))
        or str(candidate.get("display_status") or "") != "PREPARE_ONLY_FRESH_FIRST_TOUCH"
        or str(candidate.get("approach_state") or "") not in {"AHEAD", "INSIDE_CANDIDATE"}
    ):
        return []

    low = _f(candidate.get("entry_low"))
    high = _f(candidate.get("entry_high"))
    reference = _f(candidate.get("entry_reference"))
    if low is None or high is None or reference is None or not 0 < low < high:
        return []

    side_map = dict(source_eval.get(direction.lower()) or {})
    h4 = dict(dict(side_map.get("h4") or {}).get("zone") or {})
    h4_zone_id = str(h4.get("zone_id") or "")
    h4_low = _f(h4.get("low"))
    h4_high = _f(h4.get("high"))
    h4_atr = _f(h4.get("atr_points"))
    if (
        not h4_zone_id
        or h4_low is None
        or h4_high is None
        or h4_atr is None
        or h4_atr <= 0
        or h4_high <= h4_low
    ):
        return []

    target = _terminal_target(atlas_eval, direction=direction)
    if target is None:
        return []

    stop = (
        h4_low - H4_STOP_BUFFER_ATR * h4_atr
        if direction == "LONG"
        else h4_high + H4_STOP_BUFFER_ATR * h4_atr
    )
    near = high if direction == "LONG" else low
    levels = [("NEAR_EDGE", near)]
    if abs(reference - near) > 1e-9:
        levels.append(("REFERENCE", reference))

    forecasts: list[dict[str, Any]] = []
    for slot, entry in levels[:2]:
        risk = entry - stop if direction == "LONG" else stop - entry
        reward = target - entry if direction == "LONG" else entry - target
        if risk <= 0 or reward <= 0:
            continue
        rr = reward / risk
        if rr + 1e-9 < MIN_RR:
            continue

        forecasts.append(
            {
                "contract": CONTRACT,
                "research_version": RESEARCH_VERSION,
                "signal_key": _stable_signal_key(
                    h4_zone_id=h4_zone_id,
                    slot=slot,
                ),
                "forecast_at": observed_at.isoformat(),
                "forecast_timing": "FRESH_V226_PRE_ENTRY_IMMUTABLE",
                "direction": direction,
                "slot": slot,
                "source_layer": str(candidate.get("source_layer") or ""),
                "h4_zone_id": h4_zone_id,
                "candidate_low": low,
                "candidate_high": high,
                "entry_reference": reference,
                "entry": float(entry),
                "sl": float(stop),
                "tp": float(target),
                "rr": float(rr),
                "target_source": TARGET_SOURCE,
                "fixed_lot": 0.01,
                "ounces": 1.0,
                "risk_percent_filter": None,
                "max_hold_hours": MAX_HOLD_HOURS,
                "entry_horizon_hours": ENTRY_HORIZON_HOURS,
                "source": {
                    "v226_code_version": source_details.get("code_version"),
                    "v226_observed_at": source_heartbeat.get("observed_at"),
                    "atlas_observed_at": atlas_heartbeat.get("observed_at"),
                },
                "policy_effect": "SHADOW_ONLY",
                "execution_influence": False,
                "execution_authority": False,
                "promotion_authority": False,
            }
        )
    return forecasts


def _closed_m1(rows: Sequence[Bar], *, now: datetime) -> tuple[Bar, ...]:
    cutoff = ensure_utc(now)
    return tuple(
        row
        for row in sorted(tuple(rows), key=lambda item: ensure_utc(item.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=1) <= cutoff
    )


def evaluate_shadow_order(
    bars: Sequence[Bar],
    *,
    forecast: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    forecast_at = _dt(forecast.get("forecast_at"))
    direction = str(forecast.get("direction") or "").upper()
    entry = _f(forecast.get("entry"))
    stop = _f(forecast.get("sl"))
    target = _f(forecast.get("tp"))
    if (
        forecast_at is None
        or direction not in {"LONG", "SHORT"}
        or entry is None
        or stop is None
        or target is None
    ):
        raise ValueError("V232_FORECAST_GEOMETRY_INVALID")

    closed = _closed_m1(bars, now=now)
    fill_deadline = forecast_at + timedelta(hours=ENTRY_HORIZON_HOURS)
    eligible = [
        row
        for row in closed
        if forecast_at <= ensure_utc(row.timestamp) <= min(ensure_utc(now), fill_deadline)
    ]

    fill_index: int | None = None
    for idx, row in enumerate(eligible):
        if float(row.low) <= entry <= float(row.high):
            fill_index = idx
            break

    if fill_index is None:
        return {
            "status": "NO_FILL_30D" if ensure_utc(now) >= fill_deadline else "PENDING_FILL",
            "fill_at": None,
            "exit_at": fill_deadline.isoformat() if ensure_utc(now) >= fill_deadline else None,
            "exit_price": None,
            "gross_points": None,
            "gross_pnl_usd": None,
        }

    fill_row = eligible[fill_index]
    fill_at = ensure_utc(fill_row.timestamp)
    entry_bar_stop = (
        float(fill_row.low) <= stop
        if direction == "LONG"
        else float(fill_row.high) >= stop
    )
    if entry_bar_stop:
        points = stop - entry if direction == "LONG" else entry - stop
        return {
            "status": "SL_ENTRY_BAR_CONSERVATIVE",
            "fill_at": fill_at.isoformat(),
            "exit_at": fill_at.isoformat(),
            "exit_price": stop,
            "gross_points": points,
            "gross_pnl_usd": points,
        }

    exit_deadline = fill_at + timedelta(hours=MAX_HOLD_HOURS)
    future = [
        row
        for row in closed
        if fill_at < ensure_utc(row.timestamp) <= min(ensure_utc(now), exit_deadline)
    ]
    for row in future:
        ts = ensure_utc(row.timestamp)
        if direction == "LONG":
            sl_hit = float(row.low) <= stop
            tp_hit = float(row.high) >= target
        else:
            sl_hit = float(row.high) >= stop
            tp_hit = float(row.low) <= target

        # Conservative same-M1 precedence, matching V230 historical replay.
        if sl_hit:
            points = stop - entry if direction == "LONG" else entry - stop
            return {
                "status": "SL",
                "fill_at": fill_at.isoformat(),
                "exit_at": ts.isoformat(),
                "exit_price": stop,
                "gross_points": points,
                "gross_pnl_usd": points,
            }
        if tp_hit:
            points = target - entry if direction == "LONG" else entry - target
            return {
                "status": "TP",
                "fill_at": fill_at.isoformat(),
                "exit_at": ts.isoformat(),
                "exit_price": target,
                "gross_points": points,
                "gross_pnl_usd": points,
            }

    if ensure_utc(now) < exit_deadline:
        return {
            "status": "PENDING_EXIT",
            "fill_at": fill_at.isoformat(),
            "exit_at": None,
            "exit_price": None,
            "gross_points": None,
            "gross_pnl_usd": None,
        }

    exit_candidates = [
        row for row in closed
        if fill_at < ensure_utc(row.timestamp) <= exit_deadline
    ]
    last = exit_candidates[-1] if exit_candidates else fill_row
    exit_price = float(last.close)
    exit_at = ensure_utc(last.timestamp)
    points = exit_price - entry if direction == "LONG" else entry - exit_price
    return {
        "status": "TIME_EXIT_16H",
        "fill_at": fill_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "exit_price": exit_price,
        "gross_points": points,
        "gross_pnl_usd": points,
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


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    forecasts, outcomes_map = _index_events(rows)
    outcomes = list(outcomes_map.values())
    resolved = [
        row
        for row in outcomes
        if str(row.get("status") or "") in {
            "TP",
            "SL",
            "SL_ENTRY_BAR_CONSERVATIVE",
            "TIME_EXIT_16H",
        }
    ]
    no_fill = [row for row in outcomes if str(row.get("status") or "") == "NO_FILL_30D"]

    friction_summary: dict[str, Any] = {}
    for friction in FRICTIONS:
        pnl = [
            float(row.get("gross_pnl_usd") or 0.0) - friction
            for row in resolved
        ]
        wins = sum(value > 0 for value in pnl)
        losses = sum(value < 0 for value in pnl)
        gross_profit = sum(max(value, 0.0) for value in pnl)
        gross_loss = -sum(min(value, 0.0) for value in pnl)
        friction_summary[str(friction)] = {
            "resolved_orders": len(resolved),
            "net_pnl_usd_fixed_0_01": sum(pnl),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / (wins + losses) if wins + losses else None,
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        }

    return {
        "contract": CONTRACT,
        "research_version": RESEARCH_VERSION,
        "forecasts": len(forecasts),
        "resolved_orders": len(resolved),
        "no_fill_30d": len(no_fill),
        "pending": max(0, len(forecasts) - len(outcomes_map)),
        "tp_count": sum(str(row.get("status") or "") == "TP" for row in resolved),
        "sl_count": sum(str(row.get("status") or "").startswith("SL") for row in resolved),
        "time_exit_count": sum(str(row.get("status") or "") == "TIME_EXIT_16H" for row in resolved),
        "frictions": friction_summary,
        "minimum_validation_orders": MIN_VALIDATION_ORDERS,
        "validation_sample_sufficient": len(resolved) >= MIN_VALIDATION_ORDERS,
        "sample_state": (
            "INSUFFICIENT" if len(resolved) < MIN_VALIDATION_ORDERS
            else "EARLY" if len(resolved) < 100
            else "MATURE"
        ),
        "latest_outcomes": outcomes[-20:],
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "V232 is the prospective shadow ledger for the frozen V231 rule: "
            "fresh V226 Depth Candidate, H1/M15 nested locator only, terminal "
            "opposing-zone target only, RR >= 1, two immutable virtual entries "
            "(near edge/reference), H4 distal plus 0.15 ATR stop, 16h max hold, "
            "fixed 0.01-lot PnL accounting, and no risk-percent filter. It never "
            "creates EXECUTION_READY signals or broker orders."
        ),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V232_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V232_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    error: str | None = None
    forecast_written = 0
    outcome_written = 0
    summary: dict[str, Any] = {}

    try:
        source = _latest_heartbeat(store, SOURCE_WORKER)
        atlas = _latest_heartbeat(store, ATLAS_WORKER)
        rows = _events(store)
        forecasts, outcomes = _index_events(rows)

        for candidate in build_shadow_forecasts(
            source_heartbeat=source,
            atlas_heartbeat=atlas,
        ):
            key = str(candidate.get("signal_key") or "")
            if key and key not in forecasts:
                store.record_order_event(
                    backend="CTRADER",
                    account_id=ACCOUNT_ID,
                    signal_key=key,
                    event_type=FORECAST_EVENT,
                    accepted=None,
                    code=FORECAST_CODE,
                    message="V231_FROZEN_RULE_PRE_ENTRY_SHADOW",
                    payload=candidate,
                )
                forecasts[key] = candidate
                forecast_written += 1

        unresolved = [
            forecast
            for key, forecast in forecasts.items()
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
                                now - timedelta(days=35),
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
                    result = evaluate_shadow_order(raw, forecast=forecast, now=now)
                    if str(result.get("status") or "") in {"PENDING_FILL", "PENDING_EXIT"}:
                        continue
                    payload = {
                        **forecast,
                        **result,
                        "resolved_at": now.isoformat(),
                        "policy_effect": "SHADOW_ONLY",
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
                        message=str(result.get("status") or "OUTCOME"),
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
            "research_version": RESEARCH_VERSION,
            "environment": "DEMO",
            "frozen_rule": {
                "allowed_source_layers": sorted(ALLOWED_SOURCES),
                "target_source_required": TARGET_SOURCE,
                "minimum_rr": MIN_RR,
                "fixed_lot": 0.01,
                "max_virtual_orders_per_candidate": 2,
                "risk_percent_filter": None,
                "execution_authority": False,
            },
            "forecast_written": forecast_written,
            "outcome_written": outcome_written,
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
        "CTRADER_DEMO_XAU_V232_V231_PROSPECTIVE_SHADOW "
        f"healthy={healthy} forecasts={summary.get('forecasts',0)} "
        f"resolved={summary.get('resolved_orders',0)} "
        f"sample={summary.get('sample_state','NONE')} error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
