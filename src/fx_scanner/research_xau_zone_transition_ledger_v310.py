from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from math import isfinite
from statistics import median
from typing import Any, Sequence

from .models import Bar, ensure_utc
from .research_xau_m15_continuation_tournament import _validate_bars
from .research_xau_supply_demand_reaction_v183 import (
    ReactionEpisode,
    ZoneDestination,
    build_reaction_dataset,
)

RESEARCH_VERSION = "XAU_ZONE_TRANSITION_LEDGER_V310"
ARTIFACT_CONTRACT = "XAU_ZONE_TRANSITION_LEDGER_V310_EVIDENCE_1"
POLICY_EFFECT = "RESEARCH_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

HANDOFF_WINDOW_MINUTES = 30
HANDOFF_GAP_USD = 5.0


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _zone_gap(price: float, zone: ZoneDestination) -> float:
    if zone.low <= price <= zone.high:
        return 0.0
    if price < zone.low:
        return float(zone.low - price)
    return float(price - zone.high)


def _active_at(zone: ZoneDestination, at: datetime) -> bool:
    timestamp = ensure_utc(at)
    if ensure_utc(zone.available_at) > timestamp:
        return False
    if zone.invalidated_at is not None and ensure_utc(zone.invalidated_at) <= timestamp:
        return False
    if zone.expired_at is not None and ensure_utc(zone.expired_at) <= timestamp:
        return False
    return True


def _bar_lookup(rows: Sequence[Bar]) -> dict[datetime, Bar]:
    return {ensure_utc(row.timestamp): row for row in rows}


def _event(
    *,
    at: datetime,
    event_type: str,
    zone: ZoneDestination,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "at": ensure_utc(at).isoformat(),
        "event_type": event_type,
        "zone_id": zone.zone_id,
        "timeframe": zone.timeframe,
        "zone_class": zone.zone_class,
        "pattern": zone.pattern,
        "direction": zone.direction,
        "low": float(zone.low),
        "high": float(zone.high),
        "details": dict(details or {}),
    }


def build_transition_ledger(
    bars: Sequence[Bar],
) -> tuple[
    tuple[ZoneDestination, ...],
    tuple[ReactionEpisode, ...],
    tuple[dict[str, Any], ...],
]:
    """Build a chronological no-lookahead supply/demand state ledger.

    Events are emitted only at timestamps that would have been observable then:
    publication, first touch, reaction outcome, invalidation and expiry.
    """
    rows = _validate_bars(bars)
    destinations, episodes = build_reaction_dataset(rows)
    by_zone = {row.zone_id: row for row in destinations}

    events: list[dict[str, Any]] = []
    for zone in destinations:
        events.append(_event(at=zone.available_at, event_type="PUBLISHED", zone=zone))
        if zone.first_touch_at is not None:
            events.append(
                _event(
                    at=zone.first_touch_at,
                    event_type="FIRST_TOUCH",
                    zone=zone,
                )
            )
        if zone.invalidated_at is not None:
            events.append(
                _event(
                    at=zone.invalidated_at,
                    event_type="INVALIDATED",
                    zone=zone,
                )
            )
        elif zone.expired_at is not None:
            events.append(
                _event(
                    at=zone.expired_at,
                    event_type="EXPIRED",
                    zone=zone,
                )
            )

    for episode in episodes:
        zone = by_zone.get(episode.zone_id)
        outcome_at = episode.outcome.outcome_at
        if zone is None or outcome_at is None:
            continue
        if episode.outcome.status == "HOLD":
            event_type = "REACTION_HOLD"
        elif episode.outcome.status in {"BREAK", "BREAK_TOUCH_BAR"}:
            event_type = "REACTION_BREAK"
        else:
            event_type = "REACTION_STALL"
        events.append(
            _event(
                at=outcome_at,
                event_type=event_type,
                zone=zone,
                details={
                    "touch_at": ensure_utc(episode.touch_at).isoformat(),
                    "touch_ordinal": int(episode.touch_ordinal),
                    "touch_bucket": episode.touch_bucket,
                    "session_context": episode.session_context,
                    "approach_state": episode.approach_state,
                    "htf_nesting_count": int(episode.htf_nesting_count),
                    "liquidity_sources": list(episode.liquidity_sources),
                    "bars_to_outcome": episode.outcome.bars_to_outcome,
                    "mfe_atr": float(episode.outcome.max_favorable_excursion_atr),
                    "mae_atr": float(episode.outcome.max_adverse_excursion_atr),
                    "hit_050_before_break": bool(episode.outcome.hit_050_before_break),
                },
            )
        )

    events.sort(
        key=lambda row: (
            row["at"],
            row["zone_id"],
            row["event_type"],
        )
    )
    return destinations, episodes, tuple(events)


def active_opposite_zones_at(
    *,
    destinations: Sequence[ZoneDestination],
    direction: str,
    at: datetime,
    price: float,
) -> tuple[dict[str, Any], ...]:
    opposite = "SHORT" if str(direction).upper() == "LONG" else "LONG"
    rows: list[dict[str, Any]] = []
    for zone in destinations:
        if zone.direction != opposite or not _active_at(zone, at):
            continue
        gap = _zone_gap(float(price), zone)
        rows.append(
            {
                **asdict(zone),
                "gap_usd": gap,
                "already_touched": bool(
                    zone.first_touch_at is not None
                    and ensure_utc(zone.first_touch_at) <= ensure_utc(at)
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            float(row["gap_usd"]),
            0 if str(row["timeframe"]).upper() == "H1" else 1,
            str(row["zone_id"]),
        )
    )
    return tuple(rows)


def evaluate_reaction_handoffs(
    bars: Sequence[Bar],
    *,
    handoff_window_minutes: int = HANDOFF_WINDOW_MINUTES,
    handoff_gap_usd: float = HANDOFF_GAP_USD,
) -> tuple[dict[str, Any], ...]:
    """Measure opposite-zone coverage at a confirmed 0.50 ATR reaction.

    This is deliberately not a trading-cycle or TP metric. A V183 HOLD outcome is
    treated as a structural reaction milestone, then V310 asks whether an opposite
    zone was already active nearby or became available shortly afterward.
    """
    rows = _validate_bars(bars)
    destinations, episodes, _ = build_transition_ledger(rows)
    bars_by_time = _bar_lookup(rows)
    output: list[dict[str, Any]] = []

    for episode in episodes:
        if episode.outcome.status != "HOLD" or episode.outcome.outcome_at is None:
            continue
        outcome_at = ensure_utc(episode.outcome.outcome_at)
        bar = bars_by_time.get(outcome_at)
        if bar is None:
            continue
        price = float(bar.close)
        active = active_opposite_zones_at(
            destinations=destinations,
            direction=episode.direction,
            at=outcome_at,
            price=price,
        )
        nearby_active = [row for row in active if float(row["gap_usd"]) <= handoff_gap_usd]

        deadline = outcome_at + timedelta(minutes=handoff_window_minutes)
        new_after = []
        for zone in destinations:
            if zone.direction == episode.direction:
                continue
            available = ensure_utc(zone.available_at)
            if not (outcome_at < available <= deadline):
                continue
            gap = _zone_gap(price, zone)
            if gap <= handoff_gap_usd:
                new_after.append(
                    {
                        **asdict(zone),
                        "gap_usd": gap,
                    }
                )
        new_after.sort(
            key=lambda row: (
                ensure_utc(row["available_at"]),
                float(row["gap_usd"]),
                str(row["zone_id"]),
            )
        )

        selected = None
        origin = None
        if nearby_active:
            selected = dict(nearby_active[0])
            origin = "ACTIVE_AT_REACTION"
        elif new_after:
            selected = dict(new_after[0])
            origin = "NEW_WITHIN_WINDOW"

        output.append(
            {
                "source_zone_id": episode.zone_id,
                "source_direction": episode.direction,
                "source_timeframe": episode.timeframe,
                "reaction_at": outcome_at.isoformat(),
                "reaction_price_close": price,
                "touch_ordinal": int(episode.touch_ordinal),
                "active_opposite_count": len(active),
                "nearby_active_opposite_count": len(nearby_active),
                "new_opposite_within_window_count": len(new_after),
                "selected_origin": origin,
                "selected_zone_id": None if selected is None else selected.get("zone_id"),
                "selected_zone_timeframe": None if selected is None else selected.get("timeframe"),
                "selected_zone_low": None if selected is None else _f(selected.get("low")),
                "selected_zone_high": None if selected is None else _f(selected.get("high")),
                "selected_gap_usd": None if selected is None else _f(selected.get("gap_usd")),
                "selected_already_touched": (
                    None if selected is None else bool(selected.get("already_touched", False))
                ),
            }
        )

    output.sort(key=lambda row: (row["reaction_at"], row["source_zone_id"]))
    return tuple(output)


def summarize_transition_research(
    bars: Sequence[Bar],
) -> dict[str, Any]:
    rows = _validate_bars(bars)
    destinations, episodes, ledger = build_transition_ledger(rows)
    handoffs = evaluate_reaction_handoffs(rows)

    active_at_reaction = [
        row for row in handoffs if row.get("selected_origin") == "ACTIVE_AT_REACTION"
    ]
    new_within_window = [
        row for row in handoffs if row.get("selected_origin") == "NEW_WITHIN_WINDOW"
    ]
    selected = [
        row for row in handoffs if row.get("selected_origin") in {
            "ACTIVE_AT_REACTION",
            "NEW_WITHIN_WINDOW",
        }
    ]
    gaps = [
        float(row["selected_gap_usd"])
        for row in selected
        if row.get("selected_gap_usd") is not None
    ]

    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
        "closed_m15_bars": len(rows),
        "data_start": ensure_utc(rows[0].timestamp).isoformat(),
        "data_end": ensure_utc(rows[-1].timestamp).isoformat(),
        "zones": len(destinations),
        "reaction_episodes": len(episodes),
        "ledger_events": len(ledger),
        "reaction_hold_milestones": len(handoffs),
        "handoff_coverage": {
            "selected_any": len(selected),
            "selected_rate": len(selected) / len(handoffs) if handoffs else None,
            "active_at_reaction": len(active_at_reaction),
            "active_at_reaction_rate": (
                len(active_at_reaction) / len(handoffs) if handoffs else None
            ),
            "new_within_30m": len(new_within_window),
            "new_within_30m_rate": (
                len(new_within_window) / len(handoffs) if handoffs else None
            ),
            "median_selected_gap_usd": median(gaps) if gaps else None,
            "handoff_window_minutes": HANDOFF_WINDOW_MINUTES,
            "handoff_gap_usd": HANDOFF_GAP_USD,
        },
        "ledger": list(ledger),
        "reaction_handoffs": list(handoffs),
        "interpretation": (
            "V310 measures chronological zone-transition and opposite-zone coverage "
            "at V183 0.50 ATR reaction milestones. It is not a TP/win-rate study and "
            "does not change production or DEMO execution parameters."
        ),
    }
