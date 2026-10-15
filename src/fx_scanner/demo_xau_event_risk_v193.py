"""V193 Pre-News calendar worker with multi-source consensus fusion.

The heartbeat/contract names intentionally remain V192-compatible so the existing
read-only dashboard transport and cBot-isolated publication contract do not change.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable

from .config import load_project_config
from .demo_xau_event_risk_v192 import (
    CONTRACT,
    WORKER_NAME,
    RiskEvent,
    _category,
    _event_id,
    _from_discovery,
    evaluate_event_risk,
    overlay_bls_employment_actuals,
    parse_bea_schedule,
    parse_bls_employment_release,
    parse_bls_ics,
)
from .pre_news_secondary_calendar import InvestingCalendarProvider, MyfxbookCalendarProvider
from .pre_news_source_fusion import FusedConsensus, SourceQuote, canonical_event_key, fuse_consensus
from .providers.news import ForexFactoryCalendarProvider
from .providers.transport import UrllibHttpTransport
from .storage.supabase_operational import SupabaseOperationalStore

SECONDARY_SOURCES = frozenset({"MYFXBOOK", "INVESTING_COM"})
IMPACT_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
DASHBOARD_EVENT_KEYS = (
    "source",
    "source_tier",
    "title",
    "actual",
    "impact",
    "category",
    "event_component",
    "forecast",
    "previous",
    "gold_bias",
    "scheduled_at",
    "scheduled_at_wib",
    "gold_bias_basis",
    "gold_bias_confidence",
    "source_count",
    "sources",
    "source_agreement",
    "source_confidence",
    "conflicts",
)


def _secondary_config() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "config" / "pre_news_secondary_sources.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("secondary Pre-News source config must be an object")
    return data


def _secondary_tier(event: RiskEvent) -> RiskEvent:
    return replace(event, source_tier="SECONDARY_CONSENSUS")


def _align_secondary_events(
    events: Iterable[RiskEvent], *, max_hours: float = 14.0
) -> tuple[RiskEvent, ...]:
    """Snap secondary provider clocks to the nearest trusted matching release.

    Calendar sites can render timestamps in different presentation zones. Identity
    is therefore canonical component + nearest trusted release, never category alone.
    """
    rows = list(events)
    anchors = [event for event in rows if event.source not in SECONDARY_SOURCES]
    out: list[RiskEvent] = []
    max_seconds = max_hours * 3600.0
    for event in rows:
        if event.source not in SECONDARY_SOURCES:
            out.append(event)
            continue
        key = canonical_event_key(event.title)
        candidates = [
            anchor
            for anchor in anchors
            if canonical_event_key(anchor.title) == key
        ]
        if candidates:
            nearest = min(
                candidates,
                key=lambda anchor: abs((anchor.scheduled_at - event.scheduled_at).total_seconds()),
            )
            if abs((nearest.scheduled_at - event.scheduled_at).total_seconds()) <= max_seconds:
                event = replace(event, scheduled_at=nearest.scheduled_at)
        out.append(event)
    return tuple(out)


def _priority(event: RiskEvent) -> tuple[int, int]:
    if event.source_tier.startswith("OFFICIAL") and event.actual is not None:
        source_rank = 0
    elif event.source_tier.startswith("OFFICIAL"):
        source_rank = 1
    elif event.source == "FOREX_FACTORY_WEEKLY":
        source_rank = 2
    elif event.source == "MYFXBOOK":
        source_rank = 3
    elif event.source == "INVESTING_COM":
        source_rank = 4
    else:
        source_rank = 5
    return source_rank, -IMPACT_RANK.get(event.impact, 0)


def _fuse_events(
    events: Iterable[RiskEvent],
) -> tuple[tuple[RiskEvent, ...], dict[tuple[str, int], FusedConsensus]]:
    groups: dict[tuple[str, int], list[RiskEvent]] = {}
    for event in events:
        key = canonical_event_key(event.title)
        bucket = int(event.scheduled_at.timestamp() // 300)
        groups.setdefault((key, bucket), []).append(event)

    fused_events: list[RiskEvent] = []
    metadata: dict[tuple[str, int], FusedConsensus] = {}
    for (_key, _bucket), group in groups.items():
        representative = min(group, key=_priority)
        quotes = [
            SourceQuote(
                source=event.source,
                title=event.title,
                currency="USD",
                scheduled_at=event.scheduled_at,
                forecast=event.forecast,
                previous=event.previous,
                actual=event.actual,
                authoritative_actual=(
                    event.source_tier.startswith("OFFICIAL") and event.actual is not None
                ),
            )
            for event in group
        ]
        fused = fuse_consensus(quotes)
        impact = max(group, key=lambda item: IMPACT_RANK.get(item.impact, 0)).impact
        has_official = any(item.source_tier.startswith("OFFICIAL") for item in group)
        if fused.source_count >= 2:
            source = "MULTI_SOURCE_FUSION"
            source_tier = (
                "OFFICIAL_SCHEDULE_PLUS_CONSENSUS" if has_official else "SECONDARY_CONSENSUS_FUSED"
            )
        else:
            source = representative.source
            source_tier = representative.source_tier
        event = replace(
            representative,
            event_id=_event_id(source, representative.title, fused.scheduled_at),
            scheduled_at=fused.scheduled_at,
            impact=impact,
            source=source,
            source_tier=source_tier,
            actual=fused.actual,
            forecast=fused.forecast,
            previous=fused.previous,
        )
        fused_events.append(event)
        metadata[(fused.canonical_key, int(fused.scheduled_at.timestamp() // 300))] = fused
    fused_events.sort(key=lambda event: (event.scheduled_at, canonical_event_key(event.title)))
    return tuple(fused_events), metadata


def _overlay_employment_actuals(
    events: Iterable[RiskEvent], actuals: dict[str, Any]
) -> tuple[RiskEvent, ...]:
    """Apply BLS actuals component-by-component, including wage MoM vs YoY."""
    release_at = actuals.get("release_at")
    if not isinstance(release_at, datetime):
        return tuple(events)
    source_url = str(actuals.get("source_url") or "").strip()
    mapping = {
        "NONFARM_PAYROLLS": "EMPLOYMENT",
        "UNEMPLOYMENT_RATE": "UNEMPLOYMENT_RATE",
        "AVERAGE_HOURLY_EARNINGS": "WAGES",
        "AVERAGE_HOURLY_EARNINGS_MOM": "WAGES",
        "AVERAGE_HOURLY_EARNINGS_YOY": "WAGES_YOY",
    }
    out: list[RiskEvent] = []
    for event in events:
        if abs((event.scheduled_at - release_at).total_seconds()) > 120:
            out.append(event)
            continue
        canonical = canonical_event_key(event.title)
        actual_key = mapping.get(canonical)
        if actual_key is None:
            if event.category == "EMPLOYMENT":
                actual_key = "EMPLOYMENT"
            elif event.category == "UNEMPLOYMENT_RATE":
                actual_key = "UNEMPLOYMENT_RATE"
            elif event.category == "WAGES" and "YOY" not in canonical:
                actual_key = "WAGES"
        value = actuals.get(actual_key) if actual_key else None
        if value is None:
            out.append(event)
            continue
        out.append(
            replace(
                event,
                actual=float(value),
                source="BLS_OFFICIAL_EMPLOYMENT_RELEASE",
                source_tier="OFFICIAL_ACTUAL_WITH_FUSED_CONSENSUS",
                source_url=source_url or event.source_url,
            )
        )
    return tuple(sorted(out, key=lambda event: event.scheduled_at))


def _fusion_for_dict(
    event: dict[str, Any], metadata: dict[tuple[str, int], FusedConsensus]
) -> FusedConsensus | None:
    title = str(event.get("title") or "")
    raw = event.get("scheduled_at")
    if not title or not raw:
        return None
    try:
        timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None
    return metadata.get((canonical_event_key(title), int(timestamp // 300)))


def _enrich_event_dict(
    event: dict[str, Any] | None,
    metadata: dict[tuple[str, int], FusedConsensus],
) -> dict[str, Any] | None:
    if not event:
        return event
    row = dict(event)
    row["event_component"] = canonical_event_key(str(row.get("title") or ""))
    fused = _fusion_for_dict(row, metadata)
    if fused is None:
        row.update(
            {
                "source_count": 1,
                "sources": [row.get("source")],
                "source_agreement": "SINGLE_SOURCE",
                "source_confidence": "LOW",
                "conflicts": [],
            }
        )
        return row
    row["source_count"] = fused.source_count
    row["sources"] = list(fused.sources)
    row["source_agreement"] = fused.source_agreement
    row["conflicts"] = list(fused.conflicts)
    if fused.source_conflict:
        row["source_confidence"] = "LOW"
        row["gold_bias"] = "NEUTRAL_SOURCE_CONFLICT"
        row["gold_bias_confidence"] = "LOW"
        row["gold_bias_basis"] = "SOURCE_CONFLICT"
    elif fused.source_count >= 3:
        row["source_confidence"] = "HIGH"
    elif fused.source_count >= 2:
        row["source_confidence"] = "MEDIUM"
    else:
        row["source_confidence"] = "LOW"
    return row


def _enrich_risk(
    risk: dict[str, Any], metadata: dict[tuple[str, int], FusedConsensus]
) -> dict[str, Any]:
    out = dict(risk)
    out["focal_event"] = _enrich_event_dict(risk.get("focal_event"), metadata)
    out["latest_released_event"] = _enrich_event_dict(
        risk.get("latest_released_event"), metadata
    )
    out["upcoming_events"] = [
        _enrich_event_dict(item, metadata)
        for item in list(risk.get("upcoming_events") or [])
    ]
    return out


def _compact_dashboard_event(value: Any) -> dict[str, Any]:
    event = dict(value or {})
    return {key: event.get(key) for key in DASHBOARD_EVENT_KEYS if key in event}


def build_dashboard_projection(risk: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": risk.get("state"),
        "action": risk.get("action"),
        "focal_event": _compact_dashboard_event(risk.get("focal_event")),
        "latest_released_event": _compact_dashboard_event(risk.get("latest_released_event")),
        "upcoming_events": [
            _compact_dashboard_event(item) for item in list(risk.get("upcoming_events") or [])
        ],
        "minutes_to_focal": risk.get("minutes_to_focal"),
        "execution_authority": False,
        "execution_influence": False,
    }


def run() -> int:
    cfg = load_project_config(None)
    calendar_cfg = cfg.providers.get("calendar", {})
    transport_cfg = cfg.providers["transport"]
    transport = UrllibHttpTransport(
        timeout_seconds=float(transport_cfg["timeout_seconds"]),
        max_response_bytes=int(transport_cfg["max_response_bytes"]),
        user_agent=str(transport_cfg["user_agent"]),
    )
    secondary_cfg = _secondary_config()
    policy_cfg = dict(secondary_cfg.get("policy") or {})
    max_align_hours = float(policy_cfg.get("secondary_time_alignment_hours", 14))
    now = datetime.now(tz=UTC)
    events: list[RiskEvent] = []
    source_status: dict[str, str] = {}

    ff_cfg = calendar_cfg.get("FOREX_FACTORY_WEEKLY", {})
    if bool(ff_cfg.get("enabled", False)):
        try:
            snapshot = ForexFactoryCalendarProvider(
                transport,
                url=str(ff_cfg["base_url"]),
                allowed_host=str(ff_cfg["allowed_host"]),
            ).fetch(now=now)
            usd_events = [event for event in snapshot.events if event.currency == "USD"]
            events.extend(_from_discovery(event) for event in usd_events)
            source_status["FOREX_FACTORY_WEEKLY"] = f"OK:{len(usd_events)}"
        except Exception as exc:
            source_status["FOREX_FACTORY_WEEKLY"] = f"ERROR:{type(exc).__name__}:{exc}"

    bls_cfg = calendar_cfg.get("BLS_OFFICIAL_ICS", {})
    if bool(bls_cfg.get("enabled", False)):
        try:
            response = transport.get(
                str(bls_cfg["base_url"]),
                allowed_host=str(bls_cfg["allowed_host"]),
                headers={"Accept": "text/calendar,text/plain;q=0.9,*/*;q=0.1"},
            )
            parsed = parse_bls_ics(response.body, source_url=str(bls_cfg["base_url"]))
            events.extend(parsed)
            source_status["BLS_OFFICIAL_ICS"] = f"OK:{len(parsed)}"
        except Exception as exc:
            source_status["BLS_OFFICIAL_ICS"] = f"ERROR:{type(exc).__name__}:{exc}"

    bls_release_actuals: dict[str, Any] = {}
    bls_release_cfg = calendar_cfg.get("BLS_EMPLOYMENT_RELEASE", {})
    if bool(bls_release_cfg.get("enabled", False)):
        try:
            response = transport.get(
                str(bls_release_cfg["base_url"]),
                allowed_host=str(bls_release_cfg["allowed_host"]),
                headers={"Accept": "text/html,*/*;q=0.1"},
            )
            bls_release_actuals = parse_bls_employment_release(
                response.body,
                source_url=str(bls_release_cfg["base_url"]),
                now=now,
            )
            source_status["BLS_EMPLOYMENT_RELEASE"] = (
                "OK:CURRENT" if bls_release_actuals else "OK:NO_CURRENT_RELEASE"
            )
        except Exception as exc:
            source_status["BLS_EMPLOYMENT_RELEASE"] = f"ERROR:{type(exc).__name__}:{exc}"

    bea_cfg = calendar_cfg.get("BEA_OFFICIAL_SCHEDULE", {})
    if bool(bea_cfg.get("enabled", False)):
        try:
            response = transport.get(
                str(bea_cfg["base_url"]),
                allowed_host=str(bea_cfg["allowed_host"]),
                headers={"Accept": "text/html,*/*;q=0.1"},
            )
            parsed = parse_bea_schedule(
                response.body,
                source_url=str(bea_cfg["base_url"]),
                now=now,
            )
            events.extend(parsed)
            source_status["BEA_OFFICIAL_SCHEDULE"] = f"OK:{len(parsed)}"
        except Exception as exc:
            source_status["BEA_OFFICIAL_SCHEDULE"] = f"ERROR:{type(exc).__name__}:{exc}"

    myfx_cfg = dict(secondary_cfg.get("MYFXBOOK") or {})
    if bool(myfx_cfg.get("enabled", False)):
        try:
            snapshot = MyfxbookCalendarProvider(
                transport,
                url=str(myfx_cfg["base_url"]),
                allowed_host=str(myfx_cfg["allowed_host"]),
                timezone_name=str(myfx_cfg.get("timezone", "UTC")),
            ).fetch(now=now)
            usd_events = [event for event in snapshot.events if event.currency == "USD"]
            events.extend(_secondary_tier(_from_discovery(event)) for event in usd_events)
            source_status["MYFXBOOK"] = f"OK:{len(usd_events)}"
        except Exception as exc:
            source_status["MYFXBOOK"] = f"ERROR:{type(exc).__name__}"

    investing_cfg = dict(secondary_cfg.get("INVESTING_COM") or {})
    if bool(investing_cfg.get("enabled", False)):
        try:
            snapshot = InvestingCalendarProvider(
                transport,
                url=str(investing_cfg["base_url"]),
                allowed_host=str(investing_cfg["allowed_host"]),
                timezone_name=str(investing_cfg.get("timezone", "UTC")),
            ).fetch(now=now)
            usd_events = [event for event in snapshot.events if event.currency == "USD"]
            events.extend(_secondary_tier(_from_discovery(event)) for event in usd_events)
            source_status["INVESTING_COM"] = f"OK:{len(usd_events)}"
        except Exception as exc:
            source_status["INVESTING_COM"] = f"ERROR:{type(exc).__name__}"

    aligned = _align_secondary_events(events, max_hours=max_align_hours)
    fused_events, fusion_metadata = _fuse_events(aligned)
    if bls_release_actuals:
        fused_events = _overlay_employment_actuals(fused_events, bls_release_actuals)
    risk = _enrich_risk(evaluate_event_risk(fused_events, now=now), fusion_metadata)

    official_count = sum(event.source_tier.startswith("OFFICIAL") for event in fused_events)
    secondary_count = sum(
        event.source in SECONDARY_SOURCES or "CONSENSUS_FUSED" in event.source_tier
        for event in fused_events
    )
    healthy = bool(fused_events) and any(value.startswith("OK:") for value in source_status.values())
    details = {
        "contract": CONTRACT,
        "calendar_fusion_version": "V193",
        "symbol": "XAUUSD",
        "currency_focus": "USD",
        "observed_at": now.isoformat(),
        "risk": risk,
        "dashboard_projection": build_dashboard_projection(risk),
        "source_status": source_status,
        "event_count": len(fused_events),
        "official_or_fused_count": official_count,
        "secondary_or_fused_count": secondary_count,
        "fusion_policy": {
            "identity": "CANONICAL_COMPONENT_PLUS_RELEASE_TIME",
            "numeric": "MEDIAN_WITH_CONFLICT_DETECTION",
            "official_actual_precedence": True,
            "source_conflict_abstains": True,
            "secondary_fail_open": True,
        },
        "policy_effect": "SHADOW_EVENT_CONTEXT_ONLY",
        "execution_influence": False,
        "execution_authority": False,
    }
    store = SupabaseOperationalStore.from_env()
    store.write_heartbeat(
        WORKER_NAME,
        healthy=healthy,
        lag_seconds=0.0,
        details=details,
    )
    print(
        "CTRADER_DEMO_XAU_EVENT_RISK_V193 "
        f"healthy={int(healthy)} events={len(fused_events)} "
        f"myfxbook={source_status.get('MYFXBOOK','DISABLED')} "
        f"investing={source_status.get('INVESTING_COM','DISABLED')} "
        f"state={risk.get('state')} execution_authority=0"
    )
    return 0 if healthy else 2


if __name__ == "__main__":
    raise SystemExit(run())
