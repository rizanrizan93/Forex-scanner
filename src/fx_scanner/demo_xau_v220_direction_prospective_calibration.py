from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from math import isfinite, log
import os
from statistics import mean
from typing import Any, Sequence

from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .models import Bar, ensure_utc
from .research_xau_m15_dual_strategy_runtime import _fetch_history
from .storage.supabase_operational import SupabaseOperationalStore

SYMBOL = "XAUUSD"
WORKER_NAME = "ctrader_demo_xau_v220_direction_prospective_calibration"
CONTRACT = "XAU_DIRECTION_PROSPECTIVE_CALIBRATION_V220"
V217_WORKER = "ctrader_demo_xau_v217_direction_probability"
V213_WORKER = "ctrader_demo_xau_v213_post_zone_path"
FORECAST_EVENT = "DEMO_XAU_DIRECTION_FORECAST_V220"
OUTCOME_EVENT = "DEMO_XAU_DIRECTION_OUTCOME_V220"
FORECAST_CODE = "XAU_DIRECTION_FORECAST_V220"
OUTCOME_CODE = "XAU_DIRECTION_OUTCOME_V220"
ACCOUNT_ID = "OBSERVABILITY"

LOOKBACK_DAYS = 10
HISTORY_BARS = 1000
TOUCH_HORIZON_HOURS = 7 * 24
REACTION_HORIZON_BARS = 16
PRIMARY_REACTION_ATR = 0.50
MAX_EVENT_ROWS = 4000


@dataclass(frozen=True, slots=True)
class ProspectiveOutcome:
    status: str
    touch_at: datetime | None
    outcome_at: datetime | None
    actual_class: str | None
    bars_to_outcome: int | None


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


def _stable_signal_key(role: str, zone: dict[str, Any]) -> str | None:
    zone_id = str(zone.get("zone_id") or "").strip()
    direction = str(zone.get("direction") or "").upper().strip()
    available_at = str(zone.get("available_at") or "").strip()
    if not zone_id or direction not in {"LONG", "SHORT"} or not available_at:
        return None
    raw = "|".join((CONTRACT, role, zone_id, direction, available_at))
    return "V220:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _normalize_probabilities(raw: dict[str, Any]) -> dict[str, float] | None:
    values = {
        "LONG": _f(raw.get("p_long")),
        "SHORT": _f(raw.get("p_short")),
        "NEUTRAL": _f(raw.get("p_neutral")),
    }
    if any(value is None or value < 0 for value in values.values()):
        return None
    total = sum(float(value) for value in values.values() if value is not None)
    if not isfinite(total) or total <= 0:
        return None
    return {key: float(value) / total for key, value in values.items() if value is not None}


def _dominant(probabilities: dict[str, float]) -> str:
    return max(probabilities, key=probabilities.get)


def build_forecast_candidates(
    v217_heartbeat: dict[str, Any],
    v213_heartbeat: dict[str, Any],
) -> list[dict[str, Any]]:
    forecast_at = _dt(v217_heartbeat.get("observed_at"))
    if forecast_at is None or not bool(v217_heartbeat.get("healthy")):
        return []

    v217_eval = dict(dict(v217_heartbeat.get("details") or {}).get("evaluation") or {})
    v213_eval = dict(dict(v213_heartbeat.get("details") or {}).get("evaluation") or {})
    mappings = (
        ("current_leg", "tactical_first_leg"),
        ("next_leg", "opposing_next_leg"),
    )
    output: list[dict[str, Any]] = []

    for role, probability_key in mappings:
        leg = dict(v213_eval.get(role) or {})
        zone = dict(leg.get("source_zone") or {})
        probability_block = dict(v217_eval.get(probability_key) or {})
        probabilities = _normalize_probabilities(probability_block)
        signal_key = _stable_signal_key(role, zone)
        if probabilities is None or signal_key is None:
            continue

        lifecycle = dict(zone.get("lifecycle") or {})
        first_touch_at = _dt(lifecycle.get("first_touch_at"))
        invalidated_at = _dt(lifecycle.get("invalidated_at"))
        active = bool(lifecycle.get("active", True))
        pre_touch = first_touch_at is None or first_touch_at > forecast_at
        if not active or invalidated_at is not None or not pre_touch:
            continue

        low = _f(zone.get("low"))
        high = _f(zone.get("high"))
        distal = _f(zone.get("distal"))
        atr = _f(zone.get("atr_points"))
        direction = str(zone.get("direction") or "").upper()
        if (
            direction not in {"LONG", "SHORT"}
            or low is None
            or high is None
            or distal is None
            or atr is None
            or atr <= 0
        ):
            continue

        htf_context = dict(dict(v217_eval.get("strategic_htf") or {}).get("htf_context") or {})
        output.append(
            {
                "contract": CONTRACT,
                "signal_key": signal_key,
                "role": role,
                "forecast_at": forecast_at.isoformat(),
                "forecast_timing": "PRE_TOUCH_NO_LEAKAGE",
                "stage_at_forecast": leg.get("stage"),
                "direction": direction,
                "probabilities": probabilities,
                "dominant_class": _dominant(probabilities),
                "zone": {
                    "zone_id": zone.get("zone_id"),
                    "timeframe": zone.get("timeframe"),
                    "zone_class": zone.get("zone_class"),
                    "pattern": zone.get("pattern"),
                    "available_at": zone.get("available_at"),
                    "origin_at": zone.get("origin_at"),
                    "low": low,
                    "high": high,
                    "distal": distal,
                    "atr_points": atr,
                    "touch_count_at_forecast": lifecycle.get("touch_count"),
                    "first_touch_at_at_forecast": lifecycle.get("first_touch_at"),
                    "freshness_at_forecast": lifecycle.get("freshness"),
                },
                "htf_context": htf_context,
                "v217_code_version": dict(v217_heartbeat.get("details") or {}).get("code_version"),
                "v217_source_freshness": dict(v217_eval.get("source_freshness") or {}),
                "execution_influence": False,
                "execution_authority": False,
                "promotion_authority": False,
            }
        )
    return output


def _first_full_m15_at_or_after(value: datetime) -> datetime:
    ts = ensure_utc(value)
    minute_bucket = (ts.minute // 15) * 15
    floor = ts.replace(minute=minute_bucket, second=0, microsecond=0)
    if ts == floor:
        return floor
    return floor + timedelta(minutes=15)


def _invalidated(row: Bar, *, direction: str, distal: float) -> bool:
    if direction == "LONG":
        return float(row.close) < distal
    return float(row.close) > distal


def _favorable_excursion(row: Bar, *, direction: str, low: float, high: float) -> float:
    if direction == "LONG":
        return max(0.0, float(row.high) - high)
    return max(0.0, low - float(row.low))


def evaluate_forecast_outcome(
    bars: Sequence[Bar],
    *,
    forecast_at: datetime,
    direction: str,
    low: float,
    high: float,
    distal: float,
    atr_points: float,
    now: datetime,
    touch_horizon_hours: int = TOUCH_HORIZON_HOURS,
    reaction_horizon_bars: int = REACTION_HORIZON_BARS,
    primary_reaction_atr: float = PRIMARY_REACTION_ATR,
) -> ProspectiveOutcome:
    normalized = str(direction).upper()
    if normalized not in {"LONG", "SHORT"}:
        raise ValueError("V220_DIRECTION_INVALID")
    if atr_points <= 0 or not isfinite(atr_points):
        raise ValueError("V220_ATR_INVALID")

    start = _first_full_m15_at_or_after(forecast_at)
    touch_deadline = ensure_utc(forecast_at) + timedelta(hours=int(touch_horizon_hours))
    rows = tuple(
        row
        for row in sorted(bars, key=lambda item: ensure_utc(item.timestamp))
        if start <= ensure_utc(row.timestamp) <= min(ensure_utc(now), touch_deadline)
    )

    touch_index: int | None = None
    for index, row in enumerate(rows):
        if float(row.low) <= high and float(row.high) >= low:
            touch_index = index
            break

    if touch_index is None:
        if ensure_utc(now) >= touch_deadline:
            return ProspectiveOutcome(
                status="NO_TOUCH",
                touch_at=None,
                outcome_at=touch_deadline,
                actual_class=None,
                bars_to_outcome=None,
            )
        return ProspectiveOutcome(
            status="PENDING_TOUCH",
            touch_at=None,
            outcome_at=None,
            actual_class=None,
            bars_to_outcome=None,
        )

    touch = rows[touch_index]
    touch_at = ensure_utc(touch.timestamp)
    opposite = "SHORT" if normalized == "LONG" else "LONG"

    if _invalidated(touch, direction=normalized, distal=distal):
        return ProspectiveOutcome(
            status="BREAK_TOUCH_BAR",
            touch_at=touch_at,
            outcome_at=touch_at,
            actual_class=opposite,
            bars_to_outcome=0,
        )

    threshold = float(primary_reaction_atr) * float(atr_points)
    future = rows[touch_index + 1 : touch_index + 1 + int(reaction_horizon_bars)]
    max_favorable = 0.0
    for offset, row in enumerate(future, start=1):
        if _invalidated(row, direction=normalized, distal=distal):
            return ProspectiveOutcome(
                status="BREAK",
                touch_at=touch_at,
                outcome_at=ensure_utc(row.timestamp),
                actual_class=opposite,
                bars_to_outcome=offset,
            )
        max_favorable = max(
            max_favorable,
            _favorable_excursion(
                row,
                direction=normalized,
                low=low,
                high=high,
            ),
        )
        if max_favorable + 1e-12 >= threshold:
            return ProspectiveOutcome(
                status="HOLD_0_50",
                touch_at=touch_at,
                outcome_at=ensure_utc(row.timestamp),
                actual_class=normalized,
                bars_to_outcome=offset,
            )

    if len(future) < int(reaction_horizon_bars):
        return ProspectiveOutcome(
            status="PENDING_REACTION",
            touch_at=touch_at,
            outcome_at=None,
            actual_class=None,
            bars_to_outcome=None,
        )

    return ProspectiveOutcome(
        status="NEUTRAL_4H",
        touch_at=touch_at,
        outcome_at=ensure_utc(future[-1].timestamp),
        actual_class="NEUTRAL",
        bars_to_outcome=int(reaction_horizon_bars),
    )


def score_categorical_forecast(
    probabilities: dict[str, Any],
    actual_class: str,
) -> dict[str, Any]:
    normalized = _normalize_probabilities(
        {
            "p_long": probabilities.get("LONG"),
            "p_short": probabilities.get("SHORT"),
            "p_neutral": probabilities.get("NEUTRAL"),
        }
    )
    actual = str(actual_class).upper()
    if normalized is None or actual not in {"LONG", "SHORT", "NEUTRAL"}:
        raise ValueError("V220_SCORE_INPUT_INVALID")

    brier = sum(
        (float(probability) - (1.0 if key == actual else 0.0)) ** 2
        for key, probability in normalized.items()
    )
    actual_probability = max(1e-12, float(normalized[actual]))
    dominant = _dominant(normalized)
    return {
        "brier_multiclass": brier,
        "log_loss": -log(actual_probability),
        "actual_probability": actual_probability,
        "dominant_class": dominant,
        "dominant_correct": dominant == actual,
    }


def _events(store: SupabaseOperationalStore) -> list[dict[str, Any]]:
    cutoff = datetime.now(tz=UTC) - timedelta(days=LOOKBACK_DAYS)
    response = (
        store.client.table("broker_order_events")
        .select("observed_at,event_type,signal_key,code,payload")
        .eq("backend", "CTRADER")
        .eq("account_id", ACCOUNT_ID)
        .gte("observed_at", cutoff.isoformat())
        .order("observed_at", desc=False)
        .limit(MAX_EVENT_ROWS)
        .execute()
    )
    return [
        dict(row)
        for row in list(response.data or [])
        if str(dict(row).get("event_type") or "") in {FORECAST_EVENT, OUTCOME_EVENT}
    ]


def _indexed_events(
    events: Sequence[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    forecasts: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    for row in events:
        key = str(row.get("signal_key") or "")
        if not key:
            continue
        payload = dict(row.get("payload") or {})
        event_type = str(row.get("event_type") or "")
        if event_type == FORECAST_EVENT and key not in forecasts:
            forecasts[key] = payload
        elif event_type == OUTCOME_EVENT:
            outcomes[key] = payload
    return forecasts, outcomes


def _outcome_payload(
    forecast: dict[str, Any],
    outcome: ProspectiveOutcome,
) -> dict[str, Any]:
    probabilities = dict(forecast.get("probabilities") or {})
    score = (
        {}
        if outcome.actual_class is None
        else score_categorical_forecast(probabilities, outcome.actual_class)
    )
    return {
        "contract": CONTRACT,
        "signal_key": forecast.get("signal_key"),
        "role": forecast.get("role"),
        "forecast_at": forecast.get("forecast_at"),
        "direction": forecast.get("direction"),
        "probabilities": probabilities,
        "dominant_class": forecast.get("dominant_class"),
        "zone": dict(forecast.get("zone") or {}),
        "htf_context": dict(forecast.get("htf_context") or {}),
        "status": outcome.status,
        "touch_at": None if outcome.touch_at is None else outcome.touch_at.isoformat(),
        "outcome_at": None if outcome.outcome_at is None else outcome.outcome_at.isoformat(),
        "actual_class": outcome.actual_class,
        "bars_to_outcome": outcome.bars_to_outcome,
        "score": score,
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def summarize(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    forecasts, outcomes = _indexed_events(events)
    resolved = [
        payload
        for payload in outcomes.values()
        if str(payload.get("actual_class") or "") in {"LONG", "SHORT", "NEUTRAL"}
    ]
    no_touch = [
        payload
        for payload in outcomes.values()
        if str(payload.get("status") or "") == "NO_TOUCH"
    ]
    briers = [
        _f(dict(payload.get("score") or {}).get("brier_multiclass"))
        for payload in resolved
    ]
    logs = [
        _f(dict(payload.get("score") or {}).get("log_loss"))
        for payload in resolved
    ]
    correctness = [
        bool(dict(payload.get("score") or {}).get("dominant_correct"))
        for payload in resolved
    ]
    briers = [value for value in briers if value is not None]
    logs = [value for value in logs if value is not None]
    class_counts = {
        label: sum(str(payload.get("actual_class") or "") == label for payload in resolved)
        for label in ("LONG", "SHORT", "NEUTRAL")
    }
    resolved_n = len(resolved)
    return {
        "contract": CONTRACT,
        "forecasts": len(forecasts),
        "resolved_directional": resolved_n,
        "no_touch": len(no_touch),
        "pending": max(0, len(forecasts) - len(outcomes)),
        "mean_brier_multiclass": None if not briers else mean(briers),
        "mean_log_loss": None if not logs else mean(logs),
        "dominant_accuracy": None if not correctness else sum(correctness) / len(correctness),
        "actual_class_counts": class_counts,
        "sample_state": (
            "COLLECTING"
            if resolved_n < 30
            else "EARLY"
            if resolved_n < 100
            else "MATURE"
        ),
        "latest_resolved": resolved[-20:],
        "policy_effect": "SHADOW_ONLY",
        "execution_influence": False,
        "execution_authority": False,
        "promotion_authority": False,
        "interpretation": (
            "V220 scores only immutable PRE_TOUCH V217 forecasts. Direction outcomes use "
            "the V183 conservative 0.50 ATR HOLD/BREAK/4h-neutral contract. POST_TOUCH "
            "forecasts are excluded to prevent hindsight leakage. No execution authority."
        ),
    }


def run() -> int:
    policy = load_execution_policy(None)
    if str(policy.ctrader.get("environment", "")).upper() != "DEMO":
        raise SystemExit("XAU_V220_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo", False)):
        raise SystemExit("XAU_V220_REQUIRE_DEMO")

    store = SupabaseOperationalStore.from_env()
    now = datetime.now(tz=UTC)
    error: str | None = None
    forecasts_written = 0
    outcomes_written = 0
    candidates: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

    try:
        v217 = _latest_heartbeat(store, V217_WORKER)
        v213 = _latest_heartbeat(store, V213_WORKER)
        candidates = build_forecast_candidates(v217, v213)

        events = _events(store)
        forecasts, outcomes = _indexed_events(events)

        for payload in candidates:
            key = str(payload.get("signal_key") or "")
            if not key or key in forecasts:
                continue
            store.record_order_event(
                backend="CTRADER",
                account_id=ACCOUNT_ID,
                signal_key=key,
                event_type=FORECAST_EVENT,
                accepted=None,
                code=FORECAST_CODE,
                message="PRE_TOUCH_NO_LEAKAGE",
                payload=payload,
            )
            forecasts[key] = payload
            forecasts_written += 1

        unresolved = [
            payload
            for key, payload in forecasts.items()
            if key not in outcomes
        ]

        if unresolved:
            feed = build_ctrader_research_feed(policy, (SYMBOL,))
            try:
                feed.ensure_connected()
                bars, _pages = _fetch_history(feed, target=HISTORY_BARS, as_of=now)
            finally:
                try:
                    feed.close()
                except Exception:
                    pass

            for forecast in unresolved:
                forecast_at = _dt(forecast.get("forecast_at"))
                zone = dict(forecast.get("zone") or {})
                direction = str(forecast.get("direction") or "").upper()
                low = _f(zone.get("low"))
                high = _f(zone.get("high"))
                distal = _f(zone.get("distal"))
                atr = _f(zone.get("atr_points"))
                key = str(forecast.get("signal_key") or "")
                if (
                    forecast_at is None
                    or direction not in {"LONG", "SHORT"}
                    or low is None
                    or high is None
                    or distal is None
                    or atr is None
                    or atr <= 0
                    or not key
                ):
                    continue

                outcome = evaluate_forecast_outcome(
                    bars,
                    forecast_at=forecast_at,
                    direction=direction,
                    low=low,
                    high=high,
                    distal=distal,
                    atr_points=atr,
                    now=now,
                )
                if outcome.status in {"PENDING_TOUCH", "PENDING_REACTION"}:
                    continue

                payload = _outcome_payload(forecast, outcome)
                store.record_order_event(
                    backend="CTRADER",
                    account_id=ACCOUNT_ID,
                    signal_key=key,
                    event_type=OUTCOME_EVENT,
                    accepted=None,
                    code=OUTCOME_CODE,
                    message=outcome.status,
                    payload=payload,
                )
                outcomes[key] = payload
                outcomes_written += 1

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
            "summary": summary,
            "candidates_considered": len(candidates),
            "forecasts_written": forecasts_written,
            "outcomes_written": outcomes_written,
            "lookback_days": LOOKBACK_DAYS,
            "history_bars": HISTORY_BARS,
            "touch_horizon_hours": TOUCH_HORIZON_HOURS,
            "reaction_horizon_bars": REACTION_HORIZON_BARS,
            "primary_reaction_atr": PRIMARY_REACTION_ATR,
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
        "CTRADER_DEMO_XAU_V220_DIRECTION_PROSPECTIVE_CALIBRATION "
        f"healthy={healthy} forecasts_written={forecasts_written} "
        f"outcomes_written={outcomes_written} resolved={summary.get('resolved_directional',0)} "
        f"error={error or 'NONE'}"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
