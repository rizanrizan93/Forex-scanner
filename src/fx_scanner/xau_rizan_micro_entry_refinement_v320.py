from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from statistics import mean
from typing import Any, Iterable, Sequence

CONTRACT = "RIZAN_STYLE_MICRO_ENTRY_REFINEMENT_V320"
DISPLAY_NAME = "RIZAN STYLE MICRO ENTRY REFINEMENT"
POLICY_EFFECT = "RESEARCH_FORECAST_ONLY"
EXECUTION_AUTHORITY = False
EXECUTION_INFLUENCE = False

# Reconstructed from repeated user-provided captures. The observed ladder is
# approximately A -> X(1Δ) -> Y(2Δ) -> TP1(5Δ) -> TP2(8Δ) -> TP3(13Δ).
# Δ itself is not known from the original indicator, so this engine starts with
# a prospective seed of 0.22 * ATR14 and keeps the model explicitly research-only.
STEP_ATR_FRACTION = 0.22
ANCHOR_IMPULSE_ATR = 0.75
STRUCTURAL_SL_BUFFER_ATR = 0.10
MIN_BARS_FOR_ATR = 8
PIVOT_LOOKBACK = 80


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _dt(value: Any) -> datetime | None:
    if value is None:
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


def _bar_value(bar: Any, field: str) -> Any:
    if isinstance(bar, dict):
        return bar.get(field)
    return getattr(bar, field, None)


def _bar_time(bar: Any) -> datetime | None:
    return _dt(_bar_value(bar, "timestamp") or _bar_value(bar, "time"))


def _normalize_bars(bars: Iterable[Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in bars:
        ts = _bar_time(raw)
        o = _f(_bar_value(raw, "open"))
        h = _f(_bar_value(raw, "high"))
        l = _f(_bar_value(raw, "low"))
        c = _f(_bar_value(raw, "close"))
        if ts is None or None in {o, h, l, c}:
            continue
        assert o is not None and h is not None and l is not None and c is not None
        if h < l:
            continue
        output.append(
            {
                "time": ts,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
            }
        )
    output.sort(key=lambda row: row["time"])
    return output


def _atr(bars: Sequence[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) < MIN_BARS_FOR_ATR:
        return None
    rows = list(bars[-max(period + 1, MIN_BARS_FOR_ATR + 1) :])
    trs: list[float] = []
    previous_close: float | None = None
    for row in rows:
        high = float(row["high"])
        low = float(row["low"])
        if previous_close is None:
            tr = high - low
        else:
            tr = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        trs.append(max(0.0, tr))
        previous_close = float(row["close"])
    if not trs:
        return None
    selected = trs[-period:]
    return float(mean(selected)) if selected else None


def _valid_zone(zone: dict[str, Any]) -> bool:
    low = _f(zone.get("low"))
    high = _f(zone.get("high"))
    direction = str(zone.get("direction") or "").upper()
    lifecycle = dict(zone.get("lifecycle") or {})
    return bool(
        low is not None
        and high is not None
        and high > low
        and direction in {"LONG", "SHORT"}
        and lifecycle.get("active", True) is not False
        and "BROKEN" not in str(zone.get("status") or "").upper()
        and "INVALID" not in str(zone.get("status") or "").upper()
    )


def _candidate_reversal_zone(atlas_evaluation: dict[str, Any]) -> dict[str, Any]:
    path_map = dict(atlas_evaluation.get("path_map") or {})
    active_path = dict(path_map.get("active_path") or {})
    for raw in (
        active_path.get("primary_opposing_zone"),
        active_path.get("terminal_target_zone"),
        *list(active_path.get("destination_stack") or []),
    ):
        zone = dict(raw or {})
        if _valid_zone(zone):
            return zone

    projection = dict(atlas_evaluation.get("m5_path_projection") or {})
    next_leg = dict(projection.get("next_leg") or {})
    zone = dict(next_leg.get("source_zone") or {})
    if _valid_zone(zone):
        return zone
    return {}


def _opposing_zone(
    atlas_evaluation: dict[str, Any],
    *,
    direction: str,
    entry_reference: float,
) -> dict[str, Any]:
    wanted = "SHORT" if direction == "LONG" else "LONG"
    candidates: list[dict[str, Any]] = []
    for raw in list(atlas_evaluation.get("zones") or []):
        zone = dict(raw or {})
        if not _valid_zone(zone):
            continue
        if str(zone.get("direction") or "").upper() != wanted:
            continue
        low = float(zone["low"])
        high = float(zone["high"])
        if direction == "LONG" and high <= entry_reference:
            continue
        if direction == "SHORT" and low >= entry_reference:
            continue
        candidates.append(zone)
    if not candidates:
        return {}
    candidates.sort(
        key=lambda z: min(
            abs(float(z["low"]) - entry_reference),
            abs(float(z["high"]) - entry_reference),
        )
    )
    return candidates[0]


def _zone_touch_time(
    zone: dict[str, Any],
    bars: Sequence[dict[str, Any]],
) -> datetime | None:
    lifecycle = dict(zone.get("lifecycle") or {})
    for key in ("first_touch_at", "last_touch_at"):
        ts = _dt(lifecycle.get(key))
        if ts is not None:
            return ts

    low = float(zone["low"])
    high = float(zone["high"])
    available_at = _dt(zone.get("available_at"))
    for row in bars:
        if available_at is not None and row["time"] < available_at:
            continue
        if float(row["high"]) >= low and float(row["low"]) <= high:
            return row["time"]
    return None


def _reclaim_confirmed(
    zone: dict[str, Any],
    bars: Sequence[dict[str, Any]],
    *,
    touch_at: datetime | None,
) -> tuple[bool, datetime | None]:
    if touch_at is None:
        return False, None
    direction = str(zone.get("direction") or "").upper()
    proximal = _f(zone.get("proximal"))
    if proximal is None:
        proximal = float(zone["high"] if direction == "LONG" else zone["low"])

    post = [row for row in bars if row["time"] >= touch_at]
    if len(post) < 2:
        return False, None

    for i in range(1, len(post)):
        a = float(post[i - 1]["close"])
        b = float(post[i]["close"])
        if direction == "LONG" and a > proximal and b > proximal:
            return True, post[i]["time"]
        if direction == "SHORT" and a < proximal and b < proximal:
            return True, post[i]["time"]
    return False, None


def _find_anchor(
    zone: dict[str, Any],
    bars: Sequence[dict[str, Any]],
    *,
    touch_at: datetime | None,
    atr_points: float,
) -> tuple[float | None, datetime | None, str]:
    if touch_at is None:
        return None, None, "WAIT_ZONE_TOUCH"

    direction = str(zone.get("direction") or "").upper()
    proximal = _f(zone.get("proximal"))
    if proximal is None:
        proximal = float(zone["high"] if direction == "LONG" else zone["low"])

    post = [row for row in bars if row["time"] >= touch_at][-PIVOT_LOOKBACK:]
    if len(post) < 5:
        return None, None, "WAIT_POST_TOUCH_BARS"

    threshold = float(atr_points) * ANCHOR_IMPULSE_ATR
    if direction == "LONG":
        impulse_indices = [
            i for i, row in enumerate(post)
            if float(row["high"]) >= proximal + threshold
        ]
    else:
        impulse_indices = [
            i for i, row in enumerate(post)
            if float(row["low"]) <= proximal - threshold
        ]
    if not impulse_indices:
        return None, None, "WAIT_POST_TOUCH_IMPULSE"

    start = impulse_indices[0]
    candidates: list[tuple[int, float]] = []
    for i in range(max(start + 1, 1), len(post) - 1):
        prev_row = post[i - 1]
        row = post[i]
        next_row = post[i + 1]
        if direction == "LONG":
            is_pivot = (
                float(row["low"]) <= float(prev_row["low"])
                and float(row["low"]) < float(next_row["low"])
                and float(next_row["close"]) > float(row["close"])
            )
            if is_pivot:
                candidates.append((i, float(row["low"])))
        else:
            is_pivot = (
                float(row["high"]) >= float(prev_row["high"])
                and float(row["high"]) > float(next_row["high"])
                and float(next_row["close"]) < float(row["close"])
            )
            if is_pivot:
                candidates.append((i, float(row["high"])))

    if not candidates:
        return None, None, "WAIT_FIRST_POST_IMPULSE_PULLBACK"

    i, price = candidates[-1]
    return float(price), post[i]["time"], "ANCHOR_A_CONFIRMED"


def _projected_anchor(
    zone: dict[str, Any],
    *,
    atr_points: float,
) -> float:
    direction = str(zone.get("direction") or "").upper()
    proximal = _f(zone.get("proximal"))
    if proximal is None:
        proximal = float(zone["high"] if direction == "LONG" else zone["low"])
    sign = 1.0 if direction == "LONG" else -1.0
    return float(proximal) + sign * float(atr_points) * ANCHOR_IMPULSE_ATR


def _ladder(
    *,
    direction: str,
    anchor: float,
    delta: float,
) -> dict[str, float]:
    sign = 1.0 if direction == "LONG" else -1.0
    return {
        "a": float(anchor),
        "x": float(anchor + sign * delta),
        "y": float(anchor + sign * 2.0 * delta),
        "tp1": float(anchor + sign * 5.0 * delta),
        "tp2": float(anchor + sign * 8.0 * delta),
        "tp3": float(anchor + sign * 13.0 * delta),
    }


def _structural_sl(
    zone: dict[str, Any],
    *,
    atr_points: float,
) -> float:
    direction = str(zone.get("direction") or "").upper()
    low = float(zone["low"])
    high = float(zone["high"])
    buffer_points = max(float(atr_points) * STRUCTURAL_SL_BUFFER_ATR, 0.5)
    return (
        low - buffer_points
        if direction == "LONG"
        else high + buffer_points
    )


def _phase(
    *,
    direction: str,
    price_now: float | None,
    levels: dict[str, float],
    anchor_confirmed: bool,
    reclaim_confirmed: bool,
) -> str:
    if not anchor_confirmed:
        return "WAIT_ANCHOR_A"
    if not reclaim_confirmed:
        return "ANCHOR_A_ONLY_WAIT_RECLAIM"
    if price_now is None:
        return "RECLAIM_CONFIRMED"

    sign = 1.0 if direction == "LONG" else -1.0
    progress = sign * (float(price_now) - float(levels["a"]))
    thresholds = {
        "x": abs(float(levels["x"]) - float(levels["a"])),
        "y": abs(float(levels["y"]) - float(levels["a"])),
        "tp1": abs(float(levels["tp1"]) - float(levels["a"])),
        "tp2": abs(float(levels["tp2"]) - float(levels["a"])),
        "tp3": abs(float(levels["tp3"]) - float(levels["a"])),
    }
    if progress < 0:
        return "PULLBACK_BELOW_A"
    if progress < thresholds["x"]:
        return "A_RECLAIM_ACTIVE"
    if progress < thresholds["y"]:
        return "X_RECLAIM_ACTIVE"
    if progress < thresholds["tp1"]:
        return "Y_ACCEPTANCE_CONFIRMED"
    if progress < thresholds["tp2"]:
        return "TP1_REACHED_RUNNER"
    if progress < thresholds["tp3"]:
        return "TP2_REACHED_RUNNER"
    return "TP3_REACHED_CYCLE_COMPLETE"


def build_micro_entry_refinement(
    *,
    atlas_evaluation: dict[str, Any],
    bars_m5: Iterable[Any],
    bars_m15: Iterable[Any],
    bars_h1: Iterable[Any] = (),
    price_now: float | None = None,
    zone_override: dict[str, Any] | None = None,
    timeframe_preference: str | None = None,
    setup_role: str | None = None,
) -> dict[str, Any]:
    atlas = dict(atlas_evaluation or {})
    m5 = _normalize_bars(bars_m5)
    m15 = _normalize_bars(bars_m15)
    h1 = _normalize_bars(bars_h1)
    zone = dict(zone_override or {}) or _candidate_reversal_zone(atlas)
    if not zone:
        return {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": "WAIT_STRUCTURAL_DECISION_ZONE",
            "policy_effect": POLICY_EFFECT,
            "execution_authority": False,
            "execution_influence": False,
        }

    direction = str(zone.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        return {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": "WAIT_DIRECTION",
            "policy_effect": POLICY_EFFECT,
            "execution_authority": False,
            "execution_influence": False,
        }

    requested_tf = str(timeframe_preference or "").upper()
    if requested_tf == "H1" and len(h1) >= MIN_BARS_FOR_ATR:
        selected_tf = "H1"
        selected = h1
    elif requested_tf == "M15" and len(m15) >= MIN_BARS_FOR_ATR:
        selected_tf = "M15"
        selected = m15
    elif requested_tf == "M5" and len(m5) >= MIN_BARS_FOR_ATR:
        selected_tf = "M5"
        selected = m5
    elif len(m5) >= MIN_BARS_FOR_ATR:
        selected_tf = "M5"
        selected = m5
    elif len(m15) >= MIN_BARS_FOR_ATR:
        selected_tf = "M15"
        selected = m15
    else:
        selected_tf = "H1"
        selected = h1
    atr_points = _atr(selected)
    if atr_points is None:
        zone_atr = _f(zone.get("atr_points"))
        atr_points = zone_atr
    if atr_points is None or atr_points <= 0:
        return {
            "contract": CONTRACT,
            "name": DISPLAY_NAME,
            "state": "WAIT_ATR",
            "direction": direction,
            "decision_zone": zone,
            "policy_effect": POLICY_EFFECT,
            "execution_authority": False,
            "execution_influence": False,
        }

    touch_at = _zone_touch_time(zone, selected)
    reclaim_ok, reclaim_at = _reclaim_confirmed(
        zone,
        selected,
        touch_at=touch_at,
    )
    anchor, anchor_at, anchor_state = _find_anchor(
        zone,
        selected,
        touch_at=touch_at,
        atr_points=float(atr_points),
    )
    projected = False
    if anchor is None:
        anchor = _projected_anchor(zone, atr_points=float(atr_points))
        projected = True

    delta = max(0.25, float(atr_points) * STEP_ATR_FRACTION)
    levels = _ladder(
        direction=direction,
        anchor=float(anchor),
        delta=float(delta),
    )
    sl = _structural_sl(zone, atr_points=float(atr_points))
    current = _f(price_now)
    if current is None and selected:
        current = float(selected[-1]["close"])

    phase = _phase(
        direction=direction,
        price_now=current,
        levels=levels,
        anchor_confirmed=not projected,
        reclaim_confirmed=reclaim_ok,
    )
    opposite = _opposing_zone(
        atlas,
        direction=direction,
        entry_reference=float(levels["a"]),
    )
    structural_conflict = None
    if opposite:
        if direction == "LONG":
            structural_conflict = _f(opposite.get("proximal")) or _f(opposite.get("low"))
        else:
            structural_conflict = _f(opposite.get("proximal")) or _f(opposite.get("high"))

    lifecycle = dict(zone.get("lifecycle") or {})
    relation = "UNKNOWN"
    if current is not None:
        low = float(zone["low"])
        high = float(zone["high"])
        if low <= current <= high:
            relation = "INSIDE_PARENT_ZONE"
        elif direction == "LONG":
            relation = "ABOVE_PARENT_ZONE" if current > high else "BELOW_PARENT_ZONE"
        else:
            relation = "BELOW_PARENT_ZONE" if current < low else "ABOVE_PARENT_ZONE"

    confidence_components = {
        "parent_zone_active": 1.0,
        "zone_touched": 1.0 if touch_at is not None else 0.0,
        "reclaim_confirmed": 1.0 if reclaim_ok else 0.0,
        "anchor_confirmed": 0.0 if projected else 1.0,
        "first_touch_or_fresh": 1.0
        if str(lifecycle.get("freshness") or "").upper() in {"FRESH", "FIRST_TEST"}
        else 0.5,
    }
    confidence = 100.0 * sum(confidence_components.values()) / len(confidence_components)

    return {
        "contract": CONTRACT,
        "name": DISPLAY_NAME,
        "state": (
            "MICRO_LADDER_CONFIRMED"
            if not projected and reclaim_ok
            else "MICRO_LADDER_PROJECTED_WAIT_A"
            if projected
            else "MICRO_LADDER_ANCHOR_WAIT_RECLAIM"
        ),
        "phase": phase,
        "direction": direction,
        "price_now": current,
        "selected_timeframe": selected_tf,
        "setup_role": setup_role or "NEXT_OPPOSING_REVERSAL",
        "decision_zone": {
            key: zone.get(key)
            for key in (
                "zone_id",
                "timeframe",
                "pattern",
                "zone_class",
                "direction",
                "low",
                "high",
                "proximal",
                "distal",
                "atr_points",
                "status",
                "lifecycle",
            )
            if zone.get(key) is not None
        },
        "parent_zone_relation": relation,
        "touch_at": touch_at.isoformat() if touch_at else None,
        "reclaim_confirmed": reclaim_ok,
        "reclaim_at": reclaim_at.isoformat() if reclaim_at else None,
        "anchor": {
            "a": float(levels["a"]),
            "confirmed": not projected,
            "confirmed_at": anchor_at.isoformat() if anchor_at else None,
            "state": anchor_state,
            "projection_rule": (
                None
                if not projected
                else f"proximal +/- {ANCHOR_IMPULSE_ATR:.2f} ATR until first post-impulse pullback confirms A"
            ),
        },
        "delta": {
            "value": float(delta),
            "atr14": float(atr_points),
            "atr_fraction": STEP_ATR_FRACTION,
            "model": "RECONSTRUCTED_SEED_DELTA_EQ_0_22_ATR14",
            "verified_original_formula": False,
        },
        "levels": {
            **levels,
            "sl": float(sl),
        },
        "entries": [
            {
                "name": "A",
                "price": float(levels["a"]),
                "role": "AGGRESSIVE_POST_REVERSAL_ANCHOR",
                "eligible": bool(not projected and reclaim_ok),
            },
            {
                "name": "X",
                "price": float(levels["x"]),
                "role": "RECLAIM_CONFIRMATION",
                "eligible": bool(not projected and reclaim_ok),
            },
            {
                "name": "Y",
                "price": float(levels["y"]),
                "role": "ACCEPTANCE_CONFIRMATION",
                "eligible": bool(not projected and reclaim_ok),
            },
        ],
        "targets": [
            {"name": "TP1", "multiple": 5, "price": float(levels["tp1"])},
            {"name": "TP2", "multiple": 8, "price": float(levels["tp2"])},
            {"name": "TP3", "multiple": 13, "price": float(levels["tp3"])},
        ],
        "nearest_opposing_zone": {
            key: opposite.get(key)
            for key in ("zone_id", "timeframe", "direction", "low", "high", "proximal", "distal")
            if opposite.get(key) is not None
        },
        "structural_conflict_price": structural_conflict,
        "confidence": round(float(confidence), 2),
        "confidence_components": confidence_components,
        "interpretation": (
            "Prospective reconstruction of the observed A/X/Y and 5Δ/8Δ/13Δ ladder. "
            "The ladder is only promoted from PROJECTED to CONFIRMED after the structural "
            "decision zone is touched, reclaimed on the selected micro timeframe, and a "
            "post-impulse pullback pivot confirms anchor A. The original proprietary "
            "indicator formula is unknown; delta calibration remains research-only."
        ),
        "policy_effect": POLICY_EFFECT,
        "execution_authority": EXECUTION_AUTHORITY,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": False,
    }
