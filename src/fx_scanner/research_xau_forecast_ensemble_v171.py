from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from statistics import median
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from .models import Bar, ensure_utc

RESEARCH_VERSION = "XAU_FORECAST_ENSEMBLE_V171"
ARTIFACT_CONTRACT = "XAU_FORECAST_ENSEMBLE_V171_SHADOW_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
LIVE_EXECUTION_ENABLED = False

HORIZONS = {"1h": 4, "4h": 16, "8h": 32}
MIN_EXACT_MATCHES = 30
MIN_FALLBACK_MATCHES = 40
MAX_MATCHES = 120
NY = ZoneInfo("America/New_York")

# These weights are preregistered for V171. V170 is magnitude-only and is not
# allowed to vote on direction.
DIRECTION_WEIGHTS = {
    "afic": 0.40,
    "conditional": 0.25,
    "acd": 0.20,
    "cot": 0.15,
}


@dataclass(frozen=True, slots=True)
class FeatureState:
    slot: int
    trend: str
    location: str


def _closed_sorted(bars: Sequence[Bar]) -> tuple[Bar, ...]:
    rows = tuple(sorted(bars, key=lambda x: ensure_utc(x.timestamp)))
    if len(rows) < 120:
        raise ValueError("V171_HISTORY_INSUFFICIENT")
    last = None
    for row in rows:
        stamp = ensure_utc(row.timestamp)
        if last is not None and stamp <= last:
            raise ValueError("V171_HISTORY_NOT_STRICTLY_INCREASING")
        last = stamp
    return rows


def _atr14(rows: Sequence[Bar], index: int) -> float:
    if index < 14:
        return 0.0
    trs: list[float] = []
    for i in range(index - 13, index + 1):
        row = rows[i]
        prev = rows[i - 1]
        tr = max(
            float(row.high) - float(row.low),
            abs(float(row.high) - float(prev.close)),
            abs(float(row.low) - float(prev.close)),
        )
        trs.append(tr)
    return float(sum(trs) / len(trs))


def _feature_state(rows: Sequence[Bar], index: int) -> FeatureState | None:
    if index < 96:
        return None
    stamp = ensure_utc(rows[index].timestamp)
    slot = int(stamp.hour * 4 + stamp.minute // 15)
    atr = _atr14(rows, index)
    if not isfinite(atr) or atr <= 0:
        return None
    delta = float(rows[index].close) - float(rows[index - 16].close)
    threshold = 0.25 * atr
    trend = "UP" if delta > threshold else "DOWN" if delta < -threshold else "FLAT"
    window = rows[index - 95 : index + 1]
    low = min(float(row.low) for row in window)
    high = max(float(row.high) for row in window)
    rng = high - low
    if rng <= 0:
        return None
    loc = (float(rows[index].close) - low) / rng
    location = "LOW" if loc <= 1 / 3 else "HIGH" if loc >= 2 / 3 else "MID"
    return FeatureState(slot=slot, trend=trend, location=location)


def empirical_conditional_probability(bars: Sequence[Bar]) -> dict[str, Any]:
    """Causal empirical conditional probability; Raschke-inspired, not canonical.

    The label is deliberately "Raschke-style" because public Raschke material
    supports preparation around recurring market behavior, not this exact formula.
    Every historical match must have its full future horizon known before the
    current anchor; no lookahead is allowed.
    """
    rows = _closed_sorted(bars)
    anchor = len(rows) - 1
    current = _feature_state(rows, anchor)
    if current is None:
        return {"available": False, "reason": "FEATURE_STATE_UNAVAILABLE"}

    max_h = max(HORIZONS.values())
    candidates: list[tuple[int, FeatureState]] = []
    for i in range(96, anchor - max_h):
        state = _feature_state(rows, i)
        if state is not None:
            candidates.append((i, state))

    exact = [(i, s) for i, s in candidates if s == current]
    level = "SLOT_TREND_LOCATION"
    selected = exact
    if len(selected) < MIN_EXACT_MATCHES:
        selected = [
            (i, s)
            for i, s in candidates
            if s.slot == current.slot and s.trend == current.trend
        ]
        level = "SLOT_TREND"
    if len(selected) < MIN_FALLBACK_MATCHES:
        selected = [(i, s) for i, s in candidates if s.slot == current.slot]
        level = "SLOT_ONLY"
    selected = selected[-MAX_MATCHES:]
    if len(selected) < MIN_FALLBACK_MATCHES:
        return {
            "available": False,
            "reason": "MATCH_SAMPLE_INSUFFICIENT",
            "match_level": level,
            "matches": len(selected),
            "feature_state": {
                "slot": current.slot,
                "trend": current.trend,
                "location": current.location,
            },
        }

    horizon_rows: dict[str, Any] = {}
    for label, bars_ahead in HORIZONS.items():
        up = 0
        down = 0
        flat = 0
        deltas: list[float] = []
        for i, _ in selected:
            delta = float(rows[i + bars_ahead].close) - float(rows[i].close)
            deltas.append(delta)
            if delta > 0:
                up += 1
            elif delta < 0:
                down += 1
            else:
                flat += 1
        n = up + down + flat
        # Beta(1,1) smoothing prevents small samples from reporting 0%/100%.
        p_up = (up + 1.0) / (n + 2.0)
        p_down = (down + 1.0) / (n + 2.0)
        edge = p_up - p_down
        direction = "LONG" if edge >= 0.08 else "SHORT" if edge <= -0.08 else "NEUTRAL"
        horizon_rows[label] = {
            "samples": n,
            "p_up": p_up,
            "p_down": p_down,
            "direction": direction,
            "edge": edge,
            "median_close_delta": float(median(deltas)),
        }

    four = horizon_rows["4h"]
    return {
        "available": True,
        "method": "RASCHKE_STYLE_EMPIRICAL_CONDITIONAL_V1",
        "attribution": "INSPIRED_NOT_CANONICAL_RULE",
        "match_level": level,
        "matches": len(selected),
        "feature_state": {
            "slot": current.slot,
            "trend": current.trend,
            "location": current.location,
        },
        "direction": four["direction"],
        "direction_score": float(four["edge"]),
        "confidence": min(0.90, 0.50 + abs(float(four["edge"])) * 0.50),
        "horizons": horizon_rows,
    }


def fisher_acd_session_path(bars: Sequence[Bar]) -> dict[str, Any]:
    """Fisher-inspired ACD session state using an M15 approximation.

    Gold's historical COMEX open-outcry start is 08:20 New York time. With M15
    cTrader bars, V171 deliberately uses the 08:15-09:00 ET bucket as a causal
    approximation. A/C offsets are provisional OR-normalized research parameters,
    not Mark Fisher's proprietary/current GC parameter values.
    """
    rows = _closed_sorted(bars)
    latest = ensure_utc(rows[-1].timestamp).astimezone(NY)
    session_date = latest.date()
    today = [
        row
        for row in rows
        if ensure_utc(row.timestamp).astimezone(NY).date() == session_date
    ]
    opening = [
        row
        for row in today
        if (8, 15) <= (
            ensure_utc(row.timestamp).astimezone(NY).hour,
            ensure_utc(row.timestamp).astimezone(NY).minute,
        ) < (9, 0)
    ]
    if len(opening) < 3:
        return {
            "available": False,
            "reason": "OPENING_RANGE_NOT_COMPLETE",
            "session_date": str(session_date),
        }

    or_high = max(float(row.high) for row in opening)
    or_low = min(float(row.low) for row in opening)
    or_range = or_high - or_low
    if or_range <= 0:
        return {"available": False, "reason": "OPENING_RANGE_INVALID"}

    # Preregistered V171 research offsets. They must be validated before any use
    # outside dashboard/shadow research.
    a_value = 0.20 * or_range
    c_value = 0.40 * or_range
    levels = {
        "or_high": or_high,
        "or_low": or_low,
        "a_up": or_high + a_value,
        "a_down": or_low - a_value,
        "c_up": or_high + c_value,
        "c_down": or_low - c_value,
    }

    after = [
        row
        for row in today
        if (
            ensure_utc(row.timestamp).astimezone(NY).hour,
            ensure_utc(row.timestamp).astimezone(NY).minute,
        ) >= (9, 0)
    ]
    first_a: str | None = None
    first_a_index: int | None = None
    for idx, row in enumerate(after):
        if float(row.close) >= levels["a_up"]:
            first_a, first_a_index = "A_UP", idx
            break
        if float(row.close) <= levels["a_down"]:
            first_a, first_a_index = "A_DOWN", idx
            break

    state = "INSIDE_OR"
    direction = "NEUTRAL"
    score = 0.0
    if first_a == "A_UP":
        state, direction, score = "A_UP", "LONG", 0.55
        subsequent = after[(first_a_index or 0) + 1 :]
        if any(float(row.close) <= levels["c_down"] for row in subsequent):
            state, direction, score = "C_DOWN_REVERSAL", "SHORT", -0.80
    elif first_a == "A_DOWN":
        state, direction, score = "A_DOWN", "SHORT", -0.55
        subsequent = after[(first_a_index or 0) + 1 :]
        if any(float(row.close) >= levels["c_up"] for row in subsequent):
            state, direction, score = "C_UP_REVERSAL", "LONG", 0.80
    else:
        close = float(rows[-1].close)
        if close > or_high:
            state, direction, score = "ABOVE_OR_NOT_A", "LONG", 0.20
        elif close < or_low:
            state, direction, score = "BELOW_OR_NOT_A", "SHORT", -0.20

    return {
        "available": True,
        "method": "FISHER_ACD_INSPIRED_M15_V1",
        "attribution": "PUBLIC_FRAMEWORK_ADAPTED_PARAMETERS",
        "session_date": str(session_date),
        "opening_range_local": "08:15-09:00 America/New_York",
        "state": state,
        "direction": direction,
        "direction_score": score,
        "confidence": min(0.85, 0.50 + abs(score) * 0.35),
        "levels": levels,
        "parameter_contract": {
            "a_value": "0.20_OR_RANGE_V171_PREREGISTERED_SHADOW",
            "c_value": "0.40_OR_RANGE_V171_PREREGISTERED_SHADOW",
            "execution_influence": False,
        },
    }


def parse_cftc_gold_cot(text: str) -> dict[str, Any]:
    """Parse CFTC disaggregated futures-only Gold block from the official report."""
    lines = [line.rstrip() for line in str(text).splitlines()]
    gold_index = next(
        (i for i, line in enumerate(lines) if "GOLD - COMMODITY EXCHANGE INC." in line and "MICRO GOLD" not in line),
        None,
    )
    if gold_index is None:
        return {"available": False, "reason": "GOLD_BLOCK_NOT_FOUND"}

    block = lines[gold_index : gold_index + 40]
    report_line = next((line for line in block if "Futures Only," in line), "")
    positions_line = next((line for line in block if line.lstrip().startswith("All  :") and "100.0" not in line), "")
    change_marker = next((i for i, line in enumerate(block) if "Changes in Commitments from:" in line), None)
    change_line = ""
    if change_marker is not None:
        change_line = next(
            (line for line in block[change_marker + 1 :] if line.strip().startswith(":")),
            "",
        )

    import re

    def numbers(line: str) -> list[int]:
        return [int(token.replace(",", "")) for token in re.findall(r"-?\d[\d,]*", line)]

    pos = numbers(positions_line)
    chg = numbers(change_line)
    if len(pos) < 9:
        return {"available": False, "reason": "GOLD_POSITIONS_PARSE_FAILED"}

    # All row order: OI, producer L/S, swap L/S/spread, managed-money L/S/spread...
    mm_long, mm_short = int(pos[6]), int(pos[7])
    mm_net = mm_long - mm_short
    delta_long = delta_short = None
    delta_net = None
    if len(chg) >= 8:
        delta_long, delta_short = int(chg[6]), int(chg[7])
        delta_net = delta_long - delta_short

    direction = "NEUTRAL"
    score = 0.0
    if delta_net is not None and delta_net > 0:
        direction, score = "LONG", 0.35
    elif delta_net is not None and delta_net < 0:
        direction, score = "SHORT", -0.35

    return {
        "available": True,
        "method": "CFTC_DISAGGREGATED_GOLD_MANAGED_MONEY_WEEKLY_V1",
        "source": "CFTC_OFFICIAL",
        "report_label": report_line.strip(),
        "managed_money_long": mm_long,
        "managed_money_short": mm_short,
        "managed_money_net": mm_net,
        "weekly_change_long": delta_long,
        "weekly_change_short": delta_short,
        "weekly_change_net": delta_net,
        "direction": direction,
        "direction_score": score,
        "confidence": 0.55 if direction != "NEUTRAL" else 0.45,
    }


def _component_vote(component: dict[str, Any] | None) -> float | None:
    if not component or not component.get("available", True):
        return None
    raw = component.get("direction_score")
    if raw is not None:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return max(-1.0, min(1.0, value))
    direction = str(component.get("direction") or "").upper()
    return 1.0 if direction == "LONG" else -1.0 if direction == "SHORT" else 0.0


def build_forecast_ensemble(
    *,
    afic: dict[str, Any] | None,
    expected_move: dict[str, Any] | None,
    conditional: dict[str, Any] | None,
    acd: dict[str, Any] | None,
    cot: dict[str, Any] | None,
) -> dict[str, Any]:
    components = {
        "afic": dict(afic or {}),
        "conditional": dict(conditional or {}),
        "acd": dict(acd or {}),
        "cot": dict(cot or {}),
    }

    afic_direction = str(components["afic"].get("direction") or "").upper()
    afic_grade = str(components["afic"].get("grade") or "").upper()
    afic_state = str(components["afic"].get("state") or "").upper()
    afic_available = bool(components["afic"].get("available")) and afic_direction in {"LONG", "SHORT"}
    if afic_available:
        components["afic"]["direction_score"] = 1.0 if afic_direction == "LONG" else -1.0
    else:
        components["afic"]["available"] = False

    weighted = 0.0
    available_weight = 0.0
    votes: dict[str, Any] = {}
    for name, weight in DIRECTION_WEIGHTS.items():
        vote = _component_vote(components[name])
        votes[name] = vote
        if vote is None:
            continue
        weighted += weight * vote
        available_weight += weight

    score = 0.0 if available_weight <= 0 else weighted / available_weight
    coverage = available_weight / sum(DIRECTION_WEIGHTS.values())
    prior_direction = (
        "LONG" if score >= 0.15 else "SHORT" if score <= -0.15 else "NEUTRAL"
    )
    primary_direction = prior_direction if prior_direction != "NEUTRAL" else "UNCLEAR"
    structural_invalid = "INVALID" in afic_state or "REMAP" in afic_state
    if not afic_available:
        primary_direction = "WAIT_H4_MAP"
    elif structural_invalid:
        primary_direction = "WAIT_REMAP"

    conflict = False
    nonzero = [vote for vote in votes.values() if vote not in (None, 0.0)]
    if nonzero:
        conflict = any(v > 0 for v in nonzero) and any(v < 0 for v in nonzero)

    structural_penalty = 1.0
    if not afic_available:
        structural_penalty *= 0.35
    elif afic_grade == "B":
        structural_penalty *= 0.82
    elif afic_grade not in {"A", ""}:
        structural_penalty *= 0.68
    if structural_invalid:
        structural_penalty *= 0.45

    raw_conf = (0.45 + 0.45 * abs(score)) * coverage * structural_penalty
    if conflict:
        raw_conf *= 0.85
    confidence = max(0.0, min(0.90, raw_conf))
    if not afic_available:
        confidence = min(confidence, 0.25)

    alternative = "WAIT_FOR_REMAP"
    if primary_direction == "LONG":
        alternative = "SHORT_REVERSAL_IF_PRIMARY_INVALIDATES"
    elif primary_direction == "SHORT":
        alternative = "LONG_REVERSAL_IF_PRIMARY_INVALIDATES"
    elif not afic_available:
        alternative = f"{prior_direction}_PRIOR_PENDING_H4_MAP"
    elif structural_invalid:
        conditional_direction = str(components["conditional"].get("direction") or "NEUTRAL").upper()
        alternative = f"{conditional_direction}_PRIOR_PENDING_H4_REMAP"
    elif afic_direction in {"LONG", "SHORT"}:
        alternative = f"{afic_direction}_STRUCTURAL_PATH_PENDING_CONFIRMATION"

    invalidation = components["afic"].get("invalidation")
    if invalidation is None and acd and acd.get("available"):
        levels = dict(acd.get("levels") or {})
        if primary_direction == "LONG":
            invalidation = levels.get("c_down")
        elif primary_direction == "SHORT":
            invalidation = levels.get("c_up")

    envelope = dict(expected_move or {})
    return {
        "research_version": RESEARCH_VERSION,
        "artifact_contract": ARTIFACT_CONTRACT,
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "live_execution_enabled": LIVE_EXECUTION_ENABLED,
        "primary_scenario": {
            "direction": primary_direction,
            "structural_path": components["afic"].get("path"),
            "confidence": confidence,
            "direction_score": score,
        },
        "alternative_scenario": {
            "type": alternative,
            "component_conflict": conflict,
        },
        "invalidation": invalidation,
        "confidence": confidence,
        "coverage": coverage,
        "directional_prior": {
            "direction": prior_direction,
            "score": score,
            "confidence": max(0.0, min(0.90, 0.45 + 0.45 * abs(score))),
            "structural_map_required_for_primary": True,
        },
        "expected_move": envelope,
        "components": {
            "afic": components["afic"],
            "conditional": components["conditional"],
            "acd": components["acd"],
            "cot": components["cot"],
            "v170": envelope,
        },
        "vote_weights": DIRECTION_WEIGHTS,
        "vote_values": votes,
        "decision": {
            "stage": "FORECAST_ENSEMBLE_SHADOW_ONLY",
            "promotion": False,
            "execution_change": False,
            "note": (
                "V171 is a dashboard/research ensemble. It must not alter AFIC "
                "Grade-A execution authority until separately forward-validated."
            ),
        },
    }
