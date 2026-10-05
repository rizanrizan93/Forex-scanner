from __future__ import annotations

"""V398 causal frozen-reclaim replay for the AFIQ-pattern challenger.

V397 showed that the pure EARLY leg is not profitable under STOP_FIRST / fixed-
lot risk realism, while its first confirmation experiment produced no trades.
The reason is structural: V396/V397 rebuild the nearest reclaim level every H1
bar. A moving reclaim level cannot represent the level known when the early
setup was armed.

V398 freezes the entire early setup geometry at the first causal
EARLY_TAKE_RISK observation for a zone. The frozen validation level is then
watched for a later close-through. Only after that close does the confirmed
variant fill at the next H1 open. No future information is used.

Research/shadow only. No DEMO/LIVE execution authority.
"""

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .xau_afiq_challenger_v395 import evaluate_afiq_challenger_v395
from .xau_afiq_replay_v396 import (
    _close_at,
    _ts,
    build_context,
    build_liquidity_fractals,
    build_zone_metadata,
)
from .xau_afiq_risk_replay_v397 import _metrics, _year_metrics, resolve_stop_first
from .xau_sd_liquidity_engine_v342_legacy import detect_zones

CONTRACT = "XAU_RIZAN_AFIQ_FROZEN_RECLAIM_REPLAY_V398"
CONFIRM_ARM_MAX_BARS = 48


@dataclass(slots=True)
class FrozenArm:
    zone_id: str
    direction: str
    armed_index: int
    validation_level: float
    structural_invalidation: float
    candidate: dict[str, Any]
    invalid_streak: int = 0


def _valid_frozen_geometry(candidate: dict[str, Any]) -> bool:
    direction = str(candidate.get("direction") or "")
    validation = candidate.get("validation_level")
    targets = [float(value) for value in list(candidate.get("targets") or [])]
    try:
        validation_f = float(validation)
        entry_ref = float(candidate.get("entry_reference"))
        stop = float(candidate.get("structural_invalidation"))
    except (TypeError, ValueError):
        return False
    if direction == "LONG":
        return stop < entry_ref < validation_f and any(target > validation_f for target in targets)
    if direction == "SHORT":
        return stop > entry_ref > validation_f and any(target < validation_f for target in targets)
    return False


def _arm_from_candidate(candidate: dict[str, Any], index: int) -> FrozenArm | None:
    if not _valid_frozen_geometry(candidate):
        return None
    return FrozenArm(
        zone_id=str(candidate.get("zone_id") or ""),
        direction=str(candidate["direction"]),
        armed_index=index,
        validation_level=float(candidate["validation_level"]),
        structural_invalidation=float(candidate["structural_invalidation"]),
        candidate=dict(candidate),
    )


def _update_arm(arm: FrozenArm, close: float, index: int) -> str:
    """Return ACTIVE / INVALIDATED / EXPIRED / CONFIRMED using frozen data."""
    if index <= arm.armed_index:
        return "ACTIVE"
    if index - arm.armed_index > CONFIRM_ARM_MAX_BARS:
        return "EXPIRED"

    if arm.direction == "LONG":
        beyond = close < arm.structural_invalidation
        confirmed = close >= arm.validation_level
    else:
        beyond = close > arm.structural_invalidation
        confirmed = close <= arm.validation_level
    arm.invalid_streak = arm.invalid_streak + 1 if beyond else 0
    if arm.invalid_streak >= 2:
        return "INVALIDATED"
    if confirmed:
        return "CONFIRMED"
    return "ACTIVE"


def run_replay(bars_h1: Iterable[Any], bars_h4: Iterable[Any]) -> dict[str, Any]:
    h1 = tuple(sorted(bars_h1, key=lambda bar: _ts(bar)))
    h4 = tuple(sorted(bars_h4, key=lambda bar: _ts(bar)))
    if len(h1) < 200 or len(h4) < 30:
        raise ValueError("V398_REPLAY_INSUFFICIENT_HISTORY")

    as_of = _close_at(h1[-1])
    zones = tuple(detect_zones(h1, timeframe="H1", as_of=as_of)) + tuple(
        detect_zones(h4, timeframe="H4", as_of=as_of)
    )
    metas = build_zone_metadata(zones, h1)
    fractals = build_liquidity_fractals(h1)

    early = []
    confirmed = []
    next_free_early = 0
    next_free_confirmed = 0
    arms: dict[str, FrozenArm] = {}
    state_counts: dict[str, int] = {}
    diagnostics = {
        "arm_created": 0,
        "arm_geometry_rejected": 0,
        "arm_confirmed": 0,
        "arm_invalidated": 0,
        "arm_expired": 0,
        "confirmed_fill_rejected": 0,
        "early_fill_rejected": 0,
    }

    for i in range(120, len(h1) - 1):
        context = build_context(h1, metas, fractals, i)
        result = evaluate_afiq_challenger_v395(context)
        state = str(result.get("state") or "UNKNOWN")
        state_counts[state] = state_counts.get(state, 0) + 1
        candidates = list(result.get("candidates") or [])
        selected = dict(candidates[0]) if candidates else None

        if state == "EARLY_TAKE_RISK" and selected is not None:
            zone_id = str(selected.get("zone_id") or "")
            if zone_id and zone_id not in arms:
                arm = _arm_from_candidate(selected, i)
                if arm is None:
                    diagnostics["arm_geometry_rejected"] += 1
                else:
                    arms[zone_id] = arm
                    diagnostics["arm_created"] += 1

            if i >= next_free_early:
                trade = resolve_stop_first(
                    h1,
                    signal_index=i,
                    candidate=selected,
                    variant="EARLY_STOP_FIRST",
                    require_entry_in_zone=True,
                )
                if trade is None:
                    diagnostics["early_fill_rejected"] += 1
                else:
                    early.append(trade)
                    next_free_early = trade.exit_index + 1

        close = float(h1[i].close)
        confirmed_now: list[FrozenArm] = []
        remove: list[str] = []
        for zone_id, arm in list(arms.items()):
            arm_state = _update_arm(arm, close, i)
            if arm_state == "CONFIRMED":
                diagnostics["arm_confirmed"] += 1
                confirmed_now.append(arm)
                remove.append(zone_id)
            elif arm_state == "INVALIDATED":
                diagnostics["arm_invalidated"] += 1
                remove.append(zone_id)
            elif arm_state == "EXPIRED":
                diagnostics["arm_expired"] += 1
                remove.append(zone_id)

        # If several frozen setups confirm on the same H1 close, prefer the one
        # that had the strongest causal score at arming. Only one position is
        # permitted in this replay variant at a time.
        confirmed_now.sort(
            key=lambda arm: (
                -float(arm.candidate.get("score") or 0.0),
                arm.armed_index,
            )
        )
        if i >= next_free_confirmed:
            for arm in confirmed_now:
                trade = resolve_stop_first(
                    h1,
                    signal_index=i,
                    candidate=dict(arm.candidate),
                    variant="FROZEN_RECLAIM_STOP_FIRST",
                    require_entry_in_zone=False,
                )
                if trade is None:
                    diagnostics["confirmed_fill_rejected"] += 1
                    continue
                confirmed.append(trade)
                next_free_confirmed = trade.exit_index + 1
                break
        else:
            diagnostics["confirmed_fill_rejected"] += len(confirmed_now)

        for zone_id in remove:
            arms.pop(zone_id, None)

    variants = {
        "EARLY_STOP_FIRST": {
            "metrics": _metrics(early),
            "by_year": _year_metrics(early, h1),
            "trades": [asdict(trade) for trade in early],
        },
        "FROZEN_RECLAIM_STOP_FIRST": {
            "metrics": _metrics(confirmed),
            "by_year": _year_metrics(confirmed, h1),
            "trades": [asdict(trade) for trade in confirmed],
        },
    }

    gates: dict[str, Any] = {}
    for name, payload in variants.items():
        metrics = payload["metrics"]
        years = payload["by_year"]
        pf = metrics.get("fixed_price_pf")
        exp = metrics.get("expectancy_price")
        yearly_pfs = [row.get("fixed_price_pf") for row in years.values()]
        stress_pf = metrics.get("cost_stress", {}).get("cost_0.50", {}).get("fixed_price_pf")
        gates[name] = {
            "fixed_price_pf_gte_1_5": pf is not None and float(pf) >= 1.5,
            "expectancy_price_positive": exp is not None and float(exp) > 0,
            "each_year_pf_gte_1_0": bool(yearly_pfs) and all(
                value is not None and float(value) >= 1.0 for value in yearly_pfs
            ),
            "cost_0_50_pf_gte_1_2": stress_pf is not None and float(stress_pf) >= 1.2,
        }

    return {
        "contract": CONTRACT,
        "engine_contract": "XAU_RIZAN_AFIQ_CHALLENGER_V395",
        "bars": {"H1": len(h1), "H4": len(h4)},
        "period": {"start": _ts(h1[0]).isoformat(), "end": _close_at(h1[-1]).isoformat()},
        "causality": {
            "signal_time": "H1_CLOSE",
            "fill_time": "NEXT_H1_OPEN",
            "zone_availability_enforced": True,
            "fractal_availability_enforced": True,
            "historical_outcomes_not_signal_inputs": True,
            "afiq_reference_prices_used_as_runtime_inputs": False,
            "frozen_validation_from_early_signal": True,
            "confirmation_rule": "LATER_H1_CLOSE_THROUGH_FROZEN_VALIDATION",
            "pre_confirmation_zone_cancel": "TWO_ACCEPTANCE_CLOSES_BEYOND_FROZEN_STRUCTURAL_INVALIDATION",
            "post_entry_same_bar_conflict": "STOP_FIRST",
        },
        "risk_realism": {
            "primary_metric": "FIXED_PRICE_UNIT_PNL",
            "structural_stop_widened": False,
            "min_risk_formula": "max(0.75, 0.0005*entry, 0.50*zone_width)",
            "historical_costs": "STRESS_TEST_ONLY_NOT_OBSERVED",
            "cost_stress_price_units": [0.0, 0.25, 0.50, 1.0],
        },
        "zones_detected": len(zones),
        "liquidity_fractals": len(fractals),
        "state_counts": state_counts,
        "diagnostics": diagnostics,
        "open_arms_at_end": len(arms),
        "variants": variants,
        "numeric_gates": gates,
        "promotion_eligible": False,
        "promotion_blockers": [
            "HISTORICAL_SPREAD_AND_COMMISSION_NOT_OBSERVED",
            "CAUSAL_EVENT_BLACKOUT_ARCHIVE_NOT_APPLIED",
            "WALK_FORWARD_AND_LONGER_HISTORY_REQUIRED",
        ],
    }
