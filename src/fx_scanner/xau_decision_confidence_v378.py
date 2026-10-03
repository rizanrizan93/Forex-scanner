from __future__ import annotations

from typing import Any

CONTRACT = "XAU_RIZAN_DECISION_CONFIDENCE_V378"
WEIGHTS = {
    "STRUCTURE_ZONE": 30.0,
    "BEHAVIORAL_CONTEXT": 25.0,
    "MICRO_CONFIRMATION": 20.0,
    "MACRO_YIELD": 15.0,
    "EVENT": 10.0,
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _bias_match(direction: str, bias: Any) -> bool | None:
    raw = str(bias or "").upper()
    if raw not in {"BULLISH_XAU", "BEARISH_XAU", "GOLD_BULLISH", "GOLD_BEARISH"}:
        return None
    if direction == "LONG":
        return raw in {"BULLISH_XAU", "GOLD_BULLISH"}
    if direction == "SHORT":
        return raw in {"BEARISH_XAU", "GOLD_BEARISH"}
    return None


def _structure_component(
    *, direction: str, sd: dict[str, Any], behavior: dict[str, Any]
) -> tuple[float, bool, str, list[str], list[str]]:
    main = _dict(sd.get("main_reversal_zone") or sd.get("decision_zone"))
    if direction not in {"LONG", "SHORT"} or not main:
        return 0.0, False, "NO_DIRECTION_OR_MAIN_ZONE", [], []

    supporting: list[str] = []
    conflicting: list[str] = []
    condition = str(main.get("condition") or "ACTIVE").upper()
    if condition in {"BROKEN", "INVALID", "RETIRED", "EXPIRED"} or bool(main.get("intraday_quarantined")):
        return 0.0, True, "MAIN_ZONE_INVALID", [], ["MAIN zone invalid/quarantined"]

    score = 45.0
    structure = _dict(sd.get("market_structure"))
    h4 = str(_dict(structure.get("H4")).get("state") or "").upper()
    h1 = str(_dict(structure.get("H1")).get("state") or "").upper()
    wanted = "BULLISH" if direction == "LONG" else "BEARISH"
    opposite = "BEARISH" if direction == "LONG" else "BULLISH"
    for label, state in (("H4", h4), ("H1", h1)):
        if wanted in state:
            score += 17.5
            supporting.append(f"{label} structure aligned")
        elif opposite in state:
            score -= 15.0
            conflicting.append(f"{label} structure conflicts")

    role = str(_dict(behavior.get("active_zone_role")).get("role") or "")
    if role == "MAIN_REVERSAL":
        score += 10.0
        supporting.append("zone role MAIN_REVERSAL")
    elif role in {"FAILED_RETIRED", "CONTEXT_ONLY"}:
        score -= 20.0
        conflicting.append(f"zone role {role}")

    structural_room = str(
        sd.get("structural_room_state")
        or _dict(sd.get("structural_destination")).get("room_state")
        or ""
    ).upper()
    if "BLOCK" in structural_room:
        score -= 25.0
        conflicting.append("structural room blocked")
    elif structural_room and any(token in structural_room for token in ("ALLOW", "OPEN", "CLEAR")):
        score += 10.0
        supporting.append("structural room open")

    score = max(0.0, min(100.0, score))
    return score, True, f"{condition}; role={role or 'UNKNOWN'}", supporting, conflicting


def _behavior_component(
    *, direction: str, behavior: dict[str, Any]
) -> tuple[float, bool, str, list[str], list[str]]:
    if not behavior:
        return 0.0, False, "V376_UNAVAILABLE", [], []

    supporting: list[str] = []
    conflicting: list[str] = []
    score = 50.0
    acceptance = str(_dict(behavior.get("acceptance_rejection")).get("state") or "UNAVAILABLE")
    response = str(_dict(behavior.get("response_timer")).get("state") or "NOT_STARTED")
    m30_aligned = bool(behavior.get("m30_aligned"))
    m30_conflict = bool(behavior.get("m30_conflict"))
    gate = str(behavior.get("demo_entry_gate") or "")

    if acceptance == "REJECTION_CONFIRMED":
        score += 25.0
        supporting.append("rejection confirmed")
    elif acceptance == "REJECTION_DEVELOPING":
        score += 12.0
        supporting.append("rejection developing")
    elif acceptance == "ACCEPTANCE_AGAINST_THESIS":
        score -= 50.0
        conflicting.append("acceptance against thesis")

    if m30_aligned:
        score += 15.0
        supporting.append("M30 aligned")
    elif m30_conflict:
        score -= 20.0
        conflicting.append("M30 conflict")

    if response == "FOLLOW_THROUGH_CONFIRMED":
        score += 20.0
        supporting.append("response follow-through confirmed")
    elif response in {"REACTION_FAILED", "REACTION_STALLED"}:
        score -= 35.0 if response == "REACTION_FAILED" else 20.0
        conflicting.append(response.lower().replace("_", " "))
    elif response in {"FOLLOW_THROUGH_PENDING", "FOLLOW_THROUGH_WEAK"}:
        score -= 5.0

    if gate.startswith("BLOCK_"):
        score = min(score, 10.0)
        conflicting.append(f"behavior gate {gate}")

    score = max(0.0, min(100.0, score))
    return score, True, f"{acceptance}; M30={'ALIGNED' if m30_aligned else 'CONFLICT' if m30_conflict else 'NEUTRAL'}; {response}", supporting, conflicting


def _micro_component(
    *, direction: str, micro: dict[str, Any], reaction: dict[str, Any]
) -> tuple[float, bool, str, list[str], list[str]]:
    if direction not in {"LONG", "SHORT"}:
        return 0.0, False, "NO_DIRECTION", [], []
    if not micro and not reaction:
        return 0.0, False, "MICRO_UNAVAILABLE", [], []

    supporting: list[str] = []
    conflicting: list[str] = []
    if bool(micro.get("confirmed")):
        score = 100.0
        supporting.append("full micro confirmation")
    elif bool(micro.get("early_confirmed")):
        score = 82.0
        supporting.append("early micro confirmation")
    else:
        stage = str(micro.get("stage") or "WAIT").upper()
        score = 35.0 if stage not in {"WAIT", "FAR", "UNAVAILABLE"} else 20.0
        if score == 35.0:
            supporting.append(f"micro stage {stage}")

    reaction_state = str(reaction.get("state") or "")
    if reaction_state == f"EARLY_REACTION_{direction}":
        score = max(score, 72.0)
        supporting.append("early reaction interceptor aligned")
    elif reaction_state == "MISSED_NO_CHASE":
        score = min(score, 25.0)
        conflicting.append("move missed / no chase")

    return max(0.0, min(100.0, score)), True, str(micro.get("stage") or reaction_state or "WAIT"), supporting, conflicting


def _macro_component(
    *, direction: str, macro_summary: dict[str, Any]
) -> tuple[float, bool, str, list[str], list[str]]:
    if not macro_summary:
        return 0.0, False, "MACRO_UNAVAILABLE", [], []

    yield_summary = _dict(macro_summary.get("yield"))
    daily = _dict(yield_summary.get("daily"))
    intraday = _dict(yield_summary.get("intraday"))
    biases = [macro_summary.get("broader_bias"), daily.get("gold_bias"), intraday.get("gold_bias")]
    matches = [_bias_match(direction, bias) for bias in biases]
    usable = [value for value in matches if value is not None]
    if not usable:
        return 0.0, False, "NO_DIRECTIONAL_MACRO_EVIDENCE", [], []

    supporting: list[str] = []
    conflicting: list[str] = []
    aligned = sum(1 for value in usable if value)
    opposed = sum(1 for value in usable if not value)
    score = 50.0 + 18.0 * aligned - 22.0 * opposed
    if _bias_match(direction, daily.get("gold_bias")) is True:
        supporting.append("FRED US10Y daily supports direction")
    elif _bias_match(direction, daily.get("gold_bias")) is False:
        conflicting.append("FRED US10Y daily conflicts")
    if _bias_match(direction, intraday.get("gold_bias")) is True:
        supporting.append("US10Y intraday supports timing")
    elif _bias_match(direction, intraday.get("gold_bias")) is False:
        conflicting.append("US10Y intraday conflicts with timing")

    alignment = str(yield_summary.get("alignment") or "UNAVAILABLE")
    if alignment == "ALIGNED":
        score += 8.0
    elif alignment == "DIVERGENT":
        score -= 8.0
        conflicting.append("daily/intraday yield divergent")

    return max(0.0, min(100.0, score)), True, f"yield={alignment}", supporting, conflicting


def _event_component(
    *, direction: str, event: dict[str, Any]
) -> tuple[float, bool, str, list[str], list[str]]:
    if not event:
        return 0.0, False, "NO_RELEASED_EVENT", [], []
    data_conf = str(event.get("data_confidence") or "").upper()
    direction_conf = str(event.get("direction_confidence") or "").upper()
    coverage = str(event.get("numeric_coverage") or "").upper()
    if data_conf not in {"MEDIUM", "HIGH"} or direction_conf in {"", "UNAVAILABLE", "UNDETERMINED"}:
        return 0.0, False, f"{coverage or 'INSUFFICIENT_EVENT_DATA'}", [], []
    match = _bias_match(direction, event.get("gold_bias"))
    if match is None:
        return 0.0, False, "EVENT_DIRECTION_NOT_NUMERIC", [], []
    if match:
        return 85.0 if data_conf == "HIGH" else 70.0, True, f"{coverage}; aligned", ["released event supports direction"], []
    return 20.0, True, f"{coverage}; conflict", [], ["released event conflicts with direction"]


def build_decision_confidence(
    *,
    direction: str,
    sd: dict[str, Any] | None,
    behavior: dict[str, Any] | None,
    micro: dict[str, Any] | None,
    reaction: dict[str, Any] | None,
    macro_summary: dict[str, Any] | None,
    latest_event: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a conservative evidence-quality score, not a win probability."""
    direction = str(direction or "WAIT").upper()
    sd_dict = _dict(sd)
    behavior_dict = _dict(behavior)
    micro_dict = _dict(micro)
    reaction_dict = _dict(reaction)
    macro_dict = _dict(macro_summary)
    event_dict = _dict(latest_event)

    builders = {
        "STRUCTURE_ZONE": _structure_component(direction=direction, sd=sd_dict, behavior=behavior_dict),
        "BEHAVIORAL_CONTEXT": _behavior_component(direction=direction, behavior=behavior_dict),
        "MICRO_CONFIRMATION": _micro_component(direction=direction, micro=micro_dict, reaction=reaction_dict),
        "MACRO_YIELD": _macro_component(direction=direction, macro_summary=macro_dict),
        "EVENT": _event_component(direction=direction, event=event_dict),
    }

    components: list[dict[str, Any]] = []
    supporting: list[str] = []
    conflicting: list[str] = []
    missing: list[str] = []
    contribution_total = 0.0
    coverage_weight = 0.0
    for name, (score, available, state, support, conflict) in builders.items():
        weight = WEIGHTS[name]
        contribution = weight * float(score) / 100.0 if available else 0.0
        if available:
            coverage_weight += weight
        else:
            missing.append(name)
        contribution_total += contribution
        supporting.extend(support)
        conflicting.extend(conflict)
        components.append(
            {
                "name": name,
                "weight": weight,
                "score": round(float(score), 1),
                "available": bool(available),
                "contribution": round(contribution, 2),
                "state": state,
            }
        )

    evidence_score = round(max(0.0, min(100.0, contribution_total)), 1)
    coverage_pct = round(coverage_weight, 1)
    if evidence_score >= 80.0 and coverage_pct >= 80.0:
        band = "HIGH"
    elif evidence_score >= 65.0 and coverage_pct >= 70.0:
        band = "MEDIUM_HIGH"
    elif evidence_score >= 50.0 and coverage_pct >= 50.0:
        band = "MEDIUM"
    else:
        band = "LOW"

    if direction not in {"LONG", "SHORT"}:
        band = "LOW"
        evidence_score = 0.0

    return {
        "contract": CONTRACT,
        "direction": direction,
        "evidence_score": evidence_score,
        "confidence_band": band,
        "coverage_pct": coverage_pct,
        "components": components,
        "supporting_factors": supporting,
        "conflicting_factors": conflicting,
        "missing_evidence": missing,
        "execution_authority": False,
        "execution_influence": False,
        "caveat": "Evidence quality score; not a calibrated win probability and not an independent entry trigger.",
    }
