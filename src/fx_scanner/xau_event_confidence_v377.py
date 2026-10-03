from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Mapping

CONTRACT = "XAU_EVENT_CONFIDENCE_V377"


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _scheduled_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _available(value: Any) -> bool:
    return value is not None and not isinstance(value, bool)


def event_confidence(
    event: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, str]:
    """Classify event data quality separately from directional confidence.

    V377 deliberately does not manufacture consensus or actual values.  The
    classification describes what is really present in the event payload.
    """

    now_utc = (now or _utc_now()).astimezone(UTC)
    scheduled = _scheduled_at(event.get("scheduled_at"))
    has_actual = _available(event.get("actual"))
    has_forecast = _available(event.get("forecast"))
    has_previous = _available(event.get("previous"))
    category = str(event.get("category") or "").upper()
    source_tier = str(event.get("source_tier") or "").upper()

    if has_actual and has_forecast:
        numeric_coverage = "POST_RELEASE_READY"
        data_confidence = (
            "HIGH" if source_tier.startswith("OFFICIAL_ACTUAL") else "MEDIUM"
        )
        direction_confidence = "MEDIUM"
    elif has_forecast and has_previous:
        numeric_coverage = "CONSENSUS_READY"
        data_confidence = "MEDIUM"
        direction_confidence = "LOW"
    elif has_actual or has_forecast or has_previous:
        numeric_coverage = "PARTIAL_NUMERIC"
        data_confidence = "LOW"
        direction_confidence = "UNAVAILABLE"
    else:
        numeric_coverage = "SCHEDULE_ONLY"
        data_confidence = "LOW"
        direction_confidence = "UNAVAILABLE"

    if category in {"FOMC", "FED_SPEECH"} and not (has_actual and has_forecast):
        direction_confidence = "UNDETERMINED"

    if has_actual:
        actual_status = "AVAILABLE"
    elif scheduled is not None and scheduled > now_utc:
        actual_status = "PENDING_RELEASE"
    else:
        actual_status = "NOT_AVAILABLE_POST_RELEASE"

    return {
        "confidence_contract": CONTRACT,
        "data_confidence": data_confidence,
        "direction_confidence": direction_confidence,
        "numeric_coverage": numeric_coverage,
        "actual_status": actual_status,
        "forecast_status": "AVAILABLE" if has_forecast else "NO_CONSENSUS_AVAILABLE",
        "previous_status": "AVAILABLE" if has_previous else "NOT_AVAILABLE",
    }


def decorate_event_dict(
    event: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Add V377 metadata while preserving raw numeric field types/None values."""

    out = dict(event)
    out.update(event_confidence(out, now=now))
    return out


def _actual_display(status: str) -> str:
    if status == "PENDING_RELEASE":
        return "MENUNGGU RILIS"
    return "BELUM TERSEDIA"


def prepare_dashboard_event(
    event: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a display-only copy with explicit missing-data labels.

    Raw heartbeat/storage payloads keep None for unavailable numerics so no
    execution or research consumer can mistake a label for a number.
    """

    out = decorate_event_dict(event, now=now)
    if out.get("actual") is None:
        out["actual"] = _actual_display(str(out["actual_status"]))
    if out.get("forecast") is None:
        out["forecast"] = "BELUM ADA KONSENSUS"
    if out.get("previous") is None:
        out["previous"] = "BELUM TERSEDIA"
    out["gold_bias_confidence"] = (
        f"ARAH:{out['direction_confidence']} | DATA:{out['data_confidence']}"
    )
    return out


def _prepare_event_container(
    container: dict[str, Any],
    *,
    now: datetime | None,
) -> None:
    focal = container.get("focal_event")
    if isinstance(focal, Mapping) and focal:
        container["focal_event"] = prepare_dashboard_event(focal, now=now)

    latest = container.get("latest_released_event")
    if isinstance(latest, Mapping) and latest:
        container["latest_released_event"] = prepare_dashboard_event(latest, now=now)

    upcoming = container.get("upcoming_events")
    if isinstance(upcoming, (list, tuple)):
        container["upcoming_events"] = [
            prepare_dashboard_event(event, now=now)
            if isinstance(event, Mapping)
            else event
            for event in upcoming
        ]


def prepare_dashboard_heartbeat(
    heartbeat: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prepare an event heartbeat for Streamlit without mutating source data."""

    out: dict[str, Any] = deepcopy(dict(heartbeat or {}))
    details = out.get("details")
    if not isinstance(details, dict):
        return out

    risk = details.get("risk")
    if isinstance(risk, dict):
        _prepare_event_container(risk, now=now)

    projection = details.get("dashboard_projection")
    if isinstance(projection, dict):
        _prepare_event_container(projection, now=now)

    return out
