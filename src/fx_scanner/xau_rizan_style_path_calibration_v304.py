from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any, Sequence

from .models import Bar, ensure_utc

CONTRACT = "RIZAN_STYLE_PATH_CALIBRATION_V304"
POLICY_EFFECT = "RESEARCH_ONLY"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False
CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "calibration"
    / "xau_v304_afiq_public_reference_corpus.json"
)


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


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


def _bounds(zone: dict[str, Any]) -> tuple[float, float] | None:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    if low is None or high is None or high <= low:
        return None
    return low, high


def _overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_bounds = _bounds(a)
    b_bounds = _bounds(b)
    if a_bounds is None or b_bounds is None:
        return 0.0
    a_low, a_high = a_bounds
    b_low, b_high = b_bounds
    overlap = max(0.0, min(a_high, b_high) - max(a_low, b_low))
    denominator = max(min(a_high - a_low, b_high - b_low), 1e-12)
    return overlap / denominator


def _distance_to_band(value: Any, band: dict[str, Any]) -> float | None:
    parsed = _f(value)
    bounds = _bounds(band)
    if parsed is None or bounds is None:
        return None
    low, high = bounds
    if low <= parsed <= high:
        return 0.0
    return low - parsed if parsed < low else parsed - high


def _distance_price_to_zone(value: Any, zone: dict[str, Any]) -> float | None:
    return _distance_to_band(value, zone)


def _zone_overlap_bar(bar: Bar, zone: dict[str, Any]) -> bool:
    bounds = _bounds(zone)
    if bounds is None:
        return False
    low, high = bounds
    return float(bar.high) >= low and float(bar.low) <= high


def _close_breaks_zone(bar: Bar, zone: dict[str, Any]) -> bool:
    bounds = _bounds(zone)
    if bounds is None:
        return False
    low, high = bounds
    direction = str(zone.get("direction") or "").upper()
    if direction == "SHORT":
        return float(bar.close) > high
    if direction == "LONG":
        return float(bar.close) < low
    return False


def _touches_any_zone(bar: Bar, zones: Sequence[dict[str, Any]]) -> int | None:
    for index, zone in enumerate(zones):
        if _zone_overlap_bar(bar, dict(zone or {})):
            return index
    return None


def load_reference_corpus(
    path: Path = CORPUS_PATH,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("references", [])
    return payload


def select_reference(
    *,
    as_of: datetime,
    symbol: str = "XAUUSD",
    corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(corpus or load_reference_corpus())
    now = ensure_utc(as_of)
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for raw in list(payload.get("references") or []):
        row = dict(raw or {})
        if str(row.get("symbol") or "").upper() != str(symbol or "").upper():
            continue
        available = _dt(row.get("available_from"))
        if available is None or available > now:
            continue
        horizon_hours = _f(row.get("horizon_hours")) or 0.0
        if horizon_hours > 0 and now > available + timedelta(hours=horizon_hours):
            continue
        candidates.append((available, row))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _first_destination(path: dict[str, Any]) -> dict[str, Any]:
    rows = [dict(row or {}) for row in list(path.get("destinations") or [])]
    return rows[0] if rows else {}


def _route_distance_to_zone(
    route: Sequence[dict[str, Any]],
    zone: dict[str, Any],
) -> float | None:
    distances: list[float] = []
    for raw in route:
        row = dict(raw or {})
        distance = _distance_price_to_zone(row.get("price"), zone)
        if distance is not None:
            distances.append(distance)
    return min(distances) if distances else None


def _route_distance_to_price(
    route: Sequence[dict[str, Any]],
    price: Any,
) -> float | None:
    target = _f(price)
    if target is None:
        return None
    distances = [
        abs(float(parsed) - target)
        for parsed in (_f(dict(row or {}).get("price")) for row in route)
        if parsed is not None
    ]
    return min(distances) if distances else None


def evaluate_reference_alignment(
    *,
    style_path: dict[str, Any],
    reference: dict[str, Any],
) -> dict[str, Any]:
    if not reference:
        return {
            "contract": CONTRACT,
            "state": "NO_ACTIVE_PUBLIC_REFERENCE",
            "execution_authority": EXECUTION_AUTHORITY,
            "execution_influence": EXECUTION_INFLUENCE,
            "policy_effect": POLICY_EFFECT,
        }

    rizan_zone = dict(style_path.get("next_decision_zone") or {})
    ref_zone = dict(reference.get("decision_zone") or {})
    ref_key_band = dict(reference.get("key_band") or {})
    rejection = dict(style_path.get("rejection_branch") or {})
    acceptance = dict(style_path.get("acceptance_branch") or {})
    ref_rejection = dict(reference.get("rejection_path") or {})
    ref_acceptance = dict(reference.get("acceptance_path") or {})

    zone_overlap = _overlap_ratio(rizan_zone, ref_zone)
    zone_direction_match = bool(
        str(rizan_zone.get("direction") or "").upper()
        and str(rizan_zone.get("direction") or "").upper()
        == str(ref_zone.get("direction") or "").upper()
    )
    rejection_direction_match = bool(
        str(rejection.get("direction") or "").upper()
        == str(ref_rejection.get("direction") or "").upper()
        and str(ref_rejection.get("direction") or "").upper() in {"LONG", "SHORT"}
    )
    acceptance_direction_match = bool(
        str(acceptance.get("direction") or "").upper()
        == str(ref_acceptance.get("direction") or "").upper()
        and str(ref_acceptance.get("direction") or "").upper() in {"LONG", "SHORT"}
    )

    keys = dict(style_path.get("key_levels") or {})
    rejection_key_error = _distance_to_band(
        keys.get("rejection_reclaim_key"),
        ref_key_band,
    )
    acceptance_key_error = _distance_to_band(
        keys.get("break_acceptance_key"),
        ref_key_band,
    )

    ref_rejection_first = _first_destination(ref_rejection)
    ref_acceptance_first = _first_destination(ref_acceptance)
    rejection_route_error = _route_distance_to_zone(
        [dict(row or {}) for row in list(rejection.get("route") or [])],
        ref_rejection_first,
    )
    acceptance_next = dict(acceptance.get("next_destination_zone") or {})
    acceptance_zone_overlap = _overlap_ratio(
        acceptance_next,
        ref_acceptance_first,
    )

    reference_roadblock = dict(reference.get("roadblock_key") or {})
    primary_path = dict(style_path.get("primary_path") or {})
    roadblock_route_error = _route_distance_to_price(
        [dict(row or {}) for row in list(primary_path.get("route") or [])],
        reference_roadblock.get("price"),
    )

    ref_width = None
    ref_bounds = _bounds(ref_zone)
    if ref_bounds is not None:
        ref_width = ref_bounds[1] - ref_bounds[0]
    key_scale = max(ref_width or 1.0, 1.0)
    rejection_key_component = (
        0.0
        if rejection_key_error is None
        else max(0.0, 1.0 - rejection_key_error / key_scale)
    )
    acceptance_key_component = (
        0.0
        if acceptance_key_error is None
        else max(0.0, 1.0 - acceptance_key_error / key_scale)
    )
    rejection_route_component = (
        0.0
        if rejection_route_error is None
        else max(0.0, 1.0 - rejection_route_error / max(2.0 * key_scale, 1.0))
    )
    alignment_score = 100.0 * (
        0.30 * zone_overlap
        + 0.10 * float(zone_direction_match)
        + 0.10 * rejection_key_component
        + 0.10 * acceptance_key_component
        + 0.10 * float(rejection_direction_match)
        + 0.10 * float(acceptance_direction_match)
        + 0.10 * rejection_route_component
        + 0.10 * acceptance_zone_overlap
    )

    return {
        "contract": CONTRACT,
        "state": "REFERENCE_ALIGNMENT_AVAILABLE",
        "reference_id": reference.get("reference_id"),
        "source_name": reference.get("source_name"),
        "available_from": reference.get("available_from"),
        "style_path_state": style_path.get("state"),
        "style_path_direction": style_path.get("active_direction"),
        "decision_zone_overlap_ratio": round(zone_overlap, 6),
        "decision_zone_direction_match": zone_direction_match,
        "rejection_key_error_points": rejection_key_error,
        "acceptance_key_error_points": acceptance_key_error,
        "rejection_direction_match": rejection_direction_match,
        "acceptance_direction_match": acceptance_direction_match,
        "rejection_first_destination_error_points": rejection_route_error,
        "acceptance_first_destination_overlap_ratio": round(
            acceptance_zone_overlap,
            6,
        ),
        "reference_roadblock_price": _f(reference_roadblock.get("price")),
        "roadblock_route_error_points": roadblock_route_error,
        "reference_alignment_score": round(alignment_score, 3),
        "score_semantics": "REFERENCE_GEOMETRY_ALIGNMENT_NOT_WIN_RATE",
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "policy_effect": POLICY_EFFECT,
    }


def evaluate_reference_outcome(
    *,
    reference: dict[str, Any],
    bars: Sequence[Bar],
    as_of: datetime,
) -> dict[str, Any]:
    if not reference:
        return {
            "contract": CONTRACT,
            "state": "NO_ACTIVE_PUBLIC_REFERENCE",
            "execution_authority": EXECUTION_AUTHORITY,
            "execution_influence": EXECUTION_INFLUENCE,
            "policy_effect": POLICY_EFFECT,
        }

    available = _dt(reference.get("available_from"))
    if available is None:
        return {
            "contract": CONTRACT,
            "state": "REFERENCE_TIME_UNAVAILABLE",
            "reference_id": reference.get("reference_id"),
            "execution_authority": EXECUTION_AUTHORITY,
            "execution_influence": EXECUTION_INFLUENCE,
            "policy_effect": POLICY_EFFECT,
        }

    horizon_hours = _f(reference.get("horizon_hours")) or 48.0
    end_at = min(
        ensure_utc(as_of),
        available + timedelta(hours=horizon_hours),
    )
    rows = tuple(
        row
        for row in sorted(tuple(bars), key=lambda x: ensure_utc(x.timestamp))
        if available <= ensure_utc(row.timestamp)
        and ensure_utc(row.timestamp) + timedelta(minutes=15) <= end_at
    )
    decision_zone = dict(reference.get("decision_zone") or {})
    key_band = dict(reference.get("key_band") or {})
    rejection_path = dict(reference.get("rejection_path") or {})
    acceptance_path = dict(reference.get("acceptance_path") or {})
    rejection_destinations = [
        dict(row or {}) for row in list(rejection_path.get("destinations") or [])
    ]
    acceptance_destinations = [
        dict(row or {}) for row in list(acceptance_path.get("destinations") or [])
    ]

    first_touch_index: int | None = None
    first_touch_at: datetime | None = None
    break_index: int | None = None
    break_at: datetime | None = None
    rejection_hit_index: int | None = None
    rejection_hit_at: datetime | None = None
    rejection_destination_rank: int | None = None
    acceptance_hit_index: int | None = None
    acceptance_hit_at: datetime | None = None
    acceptance_destination_rank: int | None = None
    terminal_rejection_complete = False
    terminal_acceptance_complete = False

    for index, row in enumerate(rows):
        if first_touch_index is None and _zone_overlap_bar(row, decision_zone):
            first_touch_index = index
            first_touch_at = ensure_utc(row.timestamp)
        if first_touch_index is None:
            continue

        if break_index is None and _close_breaks_zone(row, decision_zone):
            break_index = index
            break_at = ensure_utc(row.timestamp)

        if rejection_hit_index is None and (break_index is None or index <= break_index):
            rank = _touches_any_zone(row, rejection_destinations)
            if rank is not None:
                rejection_hit_index = index
                rejection_hit_at = ensure_utc(row.timestamp)
                rejection_destination_rank = rank

        if break_index is not None and index >= break_index and acceptance_hit_index is None:
            rank = _touches_any_zone(row, acceptance_destinations)
            if rank is not None:
                acceptance_hit_index = index
                acceptance_hit_at = ensure_utc(row.timestamp)
                acceptance_destination_rank = rank

    if rows and first_touch_index is not None:
        post_touch = rows[first_touch_index:]
        side = str(decision_zone.get("direction") or "").upper()
        if side == "SHORT":
            reversal_extreme = max(float(row.high) for row in post_touch)
        elif side == "LONG":
            reversal_extreme = min(float(row.low) for row in post_touch)
        else:
            reversal_extreme = None
    else:
        reversal_extreme = None

    reversal_price_error = _distance_to_band(reversal_extreme, key_band)

    if rejection_destinations and first_touch_index is not None:
        final_zone = rejection_destinations[-1]
        terminal_rejection_complete = any(
            _zone_overlap_bar(row, final_zone)
            for row in rows[first_touch_index:]
        )
    if acceptance_destinations and break_index is not None:
        final_zone = acceptance_destinations[-1]
        terminal_acceptance_complete = any(
            _zone_overlap_bar(row, final_zone)
            for row in rows[break_index:]
        )

    if first_touch_index is None:
        branch = "WAIT_DECISION_ZONE_ARRIVAL"
    elif rejection_hit_index is not None and (
        break_index is None or rejection_hit_index < break_index
    ):
        branch = "REJECTION_PATH_CONFIRMED"
    elif break_index is not None and acceptance_hit_index is not None:
        branch = "ACCEPTANCE_PATH_CONFIRMED"
    elif break_index is not None:
        branch = "ACCEPTANCE_BREAK_WAIT_DESTINATION"
    else:
        branch = "DECISION_PENDING"

    return {
        "contract": CONTRACT,
        "state": "REFERENCE_OUTCOME_AVAILABLE",
        "reference_id": reference.get("reference_id"),
        "available_from": reference.get("available_from"),
        "evaluated_until": end_at.isoformat(),
        "bars_evaluated": len(rows),
        "decision_zone_arrived": first_touch_index is not None,
        "first_touch_at": None if first_touch_at is None else first_touch_at.isoformat(),
        "branch_outcome": branch,
        "break_at": None if break_at is None else break_at.isoformat(),
        "rejection_first_destination_at": (
            None if rejection_hit_at is None else rejection_hit_at.isoformat()
        ),
        "rejection_destination_rank": rejection_destination_rank,
        "acceptance_first_destination_at": (
            None if acceptance_hit_at is None else acceptance_hit_at.isoformat()
        ),
        "acceptance_destination_rank": acceptance_destination_rank,
        "reversal_extreme_price": reversal_extreme,
        "reversal_price_error_to_key_band_points": reversal_price_error,
        "terminal_rejection_path_complete": terminal_rejection_complete,
        "terminal_acceptance_path_complete": terminal_acceptance_complete,
        "prospective_no_lookahead": True,
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "policy_effect": POLICY_EFFECT,
        "note": (
            "Outcome evaluation uses only bars timestamped at/after reference available_from. "
            "It measures a public-reference forecast, not trading win rate or execution performance."
        ),
    }


def _compact_style_snapshot(style_path: dict[str, Any]) -> dict[str, Any]:
    decision_zone = dict(style_path.get("next_decision_zone") or {})
    keys = dict(style_path.get("key_levels") or {})
    acceptance = dict(style_path.get("acceptance_branch") or {})
    rejection = dict(style_path.get("rejection_branch") or {})
    return {
        "state": style_path.get("state"),
        "price_now": _f(style_path.get("price_now")),
        "active_direction": style_path.get("active_direction"),
        "decision_zone": {
            "zone_id": decision_zone.get("zone_id"),
            "timeframe": decision_zone.get("timeframe"),
            "direction": decision_zone.get("direction"),
            "low": _f(decision_zone.get("low")),
            "high": _f(decision_zone.get("high")),
        },
        "key_levels": {
            "rejection_reclaim_key": _f(keys.get("rejection_reclaim_key")),
            "break_acceptance_key": _f(keys.get("break_acceptance_key")),
            "midpoint": _f(keys.get("midpoint")),
        },
        "rejection_direction": rejection.get("direction"),
        "acceptance_direction": acceptance.get("direction"),
        "acceptance_next_destination_zone": dict(
            acceptance.get("next_destination_zone") or {}
        ),
    }


def evaluate_v304(
    *,
    style_path: dict[str, Any],
    bars: Sequence[Bar],
    as_of: datetime,
    corpus: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reference = select_reference(
        as_of=as_of,
        symbol="XAUUSD",
        corpus=corpus,
    )
    return {
        "contract": CONTRACT,
        "rizan_baseline_snapshot": _compact_style_snapshot(style_path),
        "reference": {
            "reference_id": reference.get("reference_id"),
            "source_name": reference.get("source_name"),
            "source_type": reference.get("source_type"),
            "available_from": reference.get("available_from"),
            "quality_flags": list(reference.get("quality_flags") or []),
        }
        if reference
        else {},
        "alignment": evaluate_reference_alignment(
            style_path=style_path,
            reference=reference,
        ),
        "outcome": evaluate_reference_outcome(
            reference=reference,
            bars=bars,
            as_of=as_of,
        ),
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "policy_effect": POLICY_EFFECT,
    }
