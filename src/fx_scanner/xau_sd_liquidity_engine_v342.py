from __future__ import annotations

"""Canonical XAU supply/demand engine with frozen V376 C4 path-rank champion.

The V342/V369 implementation is preserved byte-for-byte in the sibling legacy
module. This canonical module keeps the original import path used by workers,
then promotes the research-only C4 selector into production/demo evaluation.
No live execution permission is added: execution scope remains inherited from
the legacy engine and is still DEMO_ONLY.
"""

from typing import Any, Sequence

from . import xau_sd_liquidity_engine_v342_legacy as _legacy
from .xau_sd_liquidity_engine_v342_legacy import *  # noqa: F401,F403

# Source-contract compatibility markers from V363 remain present in canonical
# source while the preserved engine continues to execute them:
# build_structural_sr_map
# "support_resistance_map": support_resistance_map
# CONTEXT_ONLY_NO_DIRECTION_SIGNAL

CONTRACT = "XAU_RIZAN_SD_LIQUIDITY_V376_C4_CHAMPION_V1"
CHAMPION_ID = "V376_C4_NEXT_ZONE_PATH"
CHAMPION_STATUS = "FROZEN"
CHAMPION_FROZEN_AT = "2026-10-04"
CHAMPION_REPLAY_EPISODES = 1485
CHAMPION_REACTION_050_REPLAY_PRIOR = 0.8006734006734006
CHAMPION_EFFECTIVE_EXACT_ZONE_RATE = 0.5063973063973064
CHAMPION_RAW_EXACT_ZONE_RATE = 0.538047138047138
CHAMPION_SAME_DIRECTION_RATE = 0.8033670033670034

# Preserve the pre-C4 private selector for direct legacy/test callers only.
# Production evaluate_sd_liquidity below is bound to the frozen C4 selector.
_legacy_selector_compat = _legacy._select_parent_and_refinement


def _path_state(
    zone: dict[str, Any],
    source: Sequence[dict[str, Any]],
    *,
    price_now: float,
) -> dict[str, Any]:
    """Causal geometric path state for one eligible H1/H4 reversal zone."""
    low = float(zone["low"])
    high = float(zone["high"])
    direction = str(zone.get("direction") or "")

    if low <= price_now <= high:
        relation = "INSIDE"
        path_gap = 0.0
        plausible = True
    elif direction == "LONG" and high < price_now:
        relation = "BELOW_PRICE"
        path_gap = price_now - high
        plausible = True
    elif direction == "SHORT" and low > price_now:
        relation = "ABOVE_PRICE"
        path_gap = low - price_now
        plausible = True
    else:
        relation = "WRONG_SIDE"
        path_gap = _legacy._distance(price_now, low, high)
        plausible = False

    blockers = 0
    if plausible and relation != "INSIDE":
        for other in source:
            if other.get("zone_id") == zone.get("zone_id"):
                continue
            if str(other.get("direction") or "") != direction:
                continue
            olo = float(other["low"])
            ohi = float(other["high"])
            if olo <= price_now <= ohi:
                other_gap = 0.0
                other_plausible = True
            elif direction == "LONG" and ohi < price_now:
                other_gap = price_now - ohi
                other_plausible = True
            elif direction == "SHORT" and olo > price_now:
                other_gap = olo - price_now
                other_plausible = True
            else:
                other_gap = float("inf")
                other_plausible = False
            if not other_plausible or other_gap >= path_gap - 1e-9:
                continue
            if _legacy._overlap_ratio(zone, other) >= 0.25:
                continue
            blockers += 1

    rank = 1 + blockers if plausible else None
    if relation == "INSIDE":
        bonus = 12.0
    elif not plausible:
        bonus = -14.0
    elif rank == 1:
        bonus = 9.0
    elif rank == 2:
        bonus = 3.0
    elif rank == 3:
        bonus = 0.0
    else:
        bonus = -min(9.0, 3.0 * float(rank - 2))

    return {
        "relation": relation,
        "path_gap_points": round(float(path_gap), 6),
        "path_rank": rank,
        "blockers": blockers,
        "bonus": bonus,
    }


def _select_parent_and_refinement_c4(
    active_zones: Sequence[dict[str, Any]],
    *,
    price_now: float,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Frozen C4 selector: quality + lifecycle + causal geometric path rank."""
    profiled: list[dict[str, Any]] = []
    for raw in active_zones:
        row = dict(raw)
        profile = _legacy._main_reversal_profile(row, price_now=price_now)
        row["main_reversal_eligible"] = bool(profile["eligible"])
        row["main_reversal_score"] = profile["quality_score"]
        row["main_reversal_reasons"] = list(profile["reasons"])
        row["main_reversal_distance_atr"] = profile["distance_atr"]
        profiled.append(row)

    source = [z for z in profiled if z.get("main_reversal_eligible")]
    if not source:
        return {}, {}, "NO_MAIN_REVERSAL_ELIGIBLE"

    path = {
        str(z.get("zone_id")): _path_state(z, source, price_now=price_now)
        for z in source
    }

    def selector_score(z: dict[str, Any]) -> float:
        distance = float(z.get("main_reversal_distance_atr") or 0.0)
        quality = float(z.get("main_reversal_score") or 0.0)
        raw = float(z.get("score") or 0.0)
        life = dict(z.get("lifecycle") or {})
        mitigation = float(life.get("mitigation_depth") or 0.0)
        touches = int(life.get("touch_count") or 0)
        tf_prior = 4.0 if z.get("timeframe") == "H4" else 0.0
        hierarchy = str(z.get("hierarchy_role") or "")
        hierarchy_bonus = 5.0 if hierarchy == "H1_REFINEMENT" else 0.0
        path_bonus = float(path[str(z.get("zone_id"))]["bonus"])
        return (
            quality
            + 0.20 * raw
            + tf_prior
            + hierarchy_bonus
            + path_bonus
            - 12.0 * distance
            - 10.0 * mitigation
            - 2.0 * touches
        )

    candidates = sorted(
        source,
        key=lambda z: (
            -selector_score(z),
            path[str(z.get("zone_id"))].get("path_rank") or 999,
            float(path[str(z.get("zone_id"))].get("path_gap_points") or 0.0),
        ),
    )
    parent = dict(candidates[0])
    parent["selector_score_v376_c4"] = round(selector_score(parent), 4)
    parent["next_zone_path"] = path[str(parent.get("zone_id"))]

    refinement: dict[str, Any] = {}
    if parent.get("timeframe") == "H4":
        children: list[tuple[float, float, dict[str, Any]]] = []
        for z in source:
            if z.get("timeframe") != "H1" or z.get("direction") != parent.get("direction"):
                continue
            overlap = _legacy._overlap_ratio(z, parent)
            center = (float(z["low"]) + float(z["high"])) / 2.0
            if overlap < 0.25 and not (
                float(parent["low"]) <= center <= float(parent["high"])
            ):
                continue
            children.append((selector_score(z) + 6.0 * overlap, overlap, z))
        if children:
            children.sort(key=lambda item: (item[0], item[1]), reverse=True)
            refinement = dict(children[0][2])
            refinement["selector_score_v376_c4"] = round(selector_score(refinement), 4)
            refinement["next_zone_path"] = path[str(refinement.get("zone_id"))]

    selection = (
        "V376_C4_NEXT_ZONE_PATH_H4"
        if parent.get("timeframe") == "H4"
        else "V376_C4_NEXT_ZONE_PATH_H1"
    )
    return parent, refinement, selection


# Direct private callers keep the legacy selector contract. The preserved
# engine's global selector is separately promoted to C4 for real evaluation.
_select_parent_and_refinement = _legacy_selector_compat
_legacy._select_parent_and_refinement = _select_parent_and_refinement_c4
_legacy.CONTRACT = CONTRACT
_legacy_evaluate_sd_liquidity = _legacy.evaluate_sd_liquidity


def evaluate_sd_liquidity(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run the production/demo engine with C4 and attach frozen research provenance."""
    # Reassert the freeze in case a research module touched the preserved global.
    _legacy._select_parent_and_refinement = _select_parent_and_refinement_c4
    result = dict(_legacy_evaluate_sd_liquidity(*args, **kwargs) or {})
    main_zone = dict(result.get("main_reversal_zone") or {})
    result["contract"] = CONTRACT
    result["champion"] = {
        "id": CHAMPION_ID,
        "status": CHAMPION_STATUS,
        "frozen_at": CHAMPION_FROZEN_AT,
        "selector": "CAUSAL_H1_H4_PATH_RANK",
        "replay_years": [2025, 2026],
        "replay_episodes": CHAMPION_REPLAY_EPISODES,
        "effective_exact_zone_rate": CHAMPION_EFFECTIVE_EXACT_ZONE_RATE,
        "raw_exact_zone_rate": CHAMPION_RAW_EXACT_ZONE_RATE,
        "same_direction_rate": CHAMPION_SAME_DIRECTION_RATE,
    }
    result["reversal_probability"] = {
        "value": CHAMPION_REACTION_050_REPLAY_PRIOR if main_zone else None,
        "basis": "V376_C4_2025_2026_REACTION_050_REPLAY_PRIOR",
        "sample_size": CHAMPION_REPLAY_EPISODES,
        "threshold": "REACTION_GTE_0.50_ATR",
        "calibration": "RESEARCH_PRIOR_NOT_LIVE_CONDITIONAL_PROBABILITY",
    }
    return result


def __getattr__(name: str) -> Any:
    return getattr(_legacy, name)
