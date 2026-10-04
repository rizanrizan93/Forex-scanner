from __future__ import annotations

"""Research-only V376 C4 next-zone path challenger.

C1 remains frozen. This module monkey-patches only the research process so the
production/demo engine is not modified. The C4 hypothesis is that cross-TF ATR
normalisation can make a deeper H4 zone appear artificially competitive with a
nearer H1 zone. C4 therefore adds an ordinal, causal path-rank term based on the
actual geometric order in which price would encounter eligible zones.
"""

import argparse
from pathlib import Path
from typing import Any, Sequence

import fx_scanner.xau_sd_liquidity_engine_v342 as eng


def _path_state(
    zone: dict[str, Any],
    source: Sequence[dict[str, Any]],
    *,
    price_now: float,
) -> dict[str, Any]:
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
        path_gap = eng._distance(price_now, low, high)
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
                other_plausible = False
                other_gap = float("inf")
            if not other_plausible or other_gap >= path_gap - 1e-9:
                continue
            # Nested/overlapping H1-H4 geometry is one interaction cluster, not
            # two separate blockers.
            if eng._overlap_ratio(zone, other) >= 0.25:
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
    profiled: list[dict[str, Any]] = []
    for raw in active_zones:
        row = dict(raw)
        profile = eng._main_reversal_profile(row, price_now=price_now)
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

    def _selector_score(z: dict[str, Any]) -> float:
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
            -_selector_score(z),
            path[str(z.get("zone_id"))].get("path_rank") or 999,
            float(path[str(z.get("zone_id"))].get("path_gap_points") or 0.0),
        ),
    )
    parent = dict(candidates[0])
    pstate = path[str(parent.get("zone_id"))]
    parent["selector_score_v376_c4"] = round(_selector_score(parent), 4)
    parent["next_zone_path"] = pstate

    refinement: dict[str, Any] = {}
    if parent.get("timeframe") == "H4":
        children: list[tuple[float, float, dict[str, Any]]] = []
        for z in source:
            if z.get("timeframe") != "H1" or z.get("direction") != parent.get("direction"):
                continue
            overlap = eng._overlap_ratio(z, parent)
            center = (float(z["low"]) + float(z["high"])) / 2.0
            if overlap < 0.25 and not (float(parent["low"]) <= center <= float(parent["high"])):
                continue
            child_score = _selector_score(z) + 6.0 * overlap
            children.append((child_score, overlap, z))
        if children:
            children.sort(key=lambda item: (item[0], item[1]), reverse=True)
            refinement = dict(children[0][2])
            refinement["selector_score_v376_c4"] = round(_selector_score(refinement), 4)
            refinement["next_zone_path"] = path[str(refinement.get("zone_id"))]

    selection = (
        "V376_C4_NEXT_ZONE_PATH_H4"
        if parent.get("timeframe") == "H4"
        else "V376_C4_NEXT_ZONE_PATH_H1"
    )
    return parent, refinement, selection


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    # Research-only patch. evaluate_sd_liquidity resolves this global selector
    # at runtime, so production source remains identical to frozen C1.
    eng._select_parent_and_refinement = _select_parent_and_refinement_c4

    import xau_v342_afiq_behavioral_replay as replay

    replay.SCHEMA = "XAU_V376_C4_NEXT_ZONE_PATH_REPLAY_V1"
    replay.run(args.year, args.csv, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
