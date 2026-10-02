from __future__ import annotations

from typing import Any, Sequence


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_demand_tiers(
    *,
    active_zones: Sequence[dict[str, Any]],
    sr_map: dict[str, Any],
    price_now: float,
    atr_reference: float,
) -> dict[str, Any]:
    price = float(price_now)
    atr = max(float(atr_reference), 1e-9)

    levels = []
    for raw in list(dict(sr_map or {}).get("levels") or []):
        row = dict(raw or {})
        px = _num(row.get("price"))
        role = str(row.get("current_role") or row.get("kind") or "").upper()
        if px is None or px > price:
            continue
        if role in {"SUPPORT", "FLIP", "SUPPORT_FLIP_CANDIDATE"}:
            levels.append(row)

    reaction = {}
    if levels:
        levels.sort(key=lambda row: abs(float(row["price"]) - price))
        anchor = float(levels[0]["price"])
        group = [
            row for row in levels
            if abs(float(row["price"]) - anchor) <= max(0.80 * atr, 1.0)
        ]
        reaction = {
            "state": "REACTION_SUPPORT_CLUSTER",
            "low": min(float(_num(r.get("band_low")) or r["price"]) for r in group),
            "high": max(float(_num(r.get("band_high")) or r["price"]) for r in group),
            "anchor": anchor,
            "levels": [float(r["price"]) for r in group],
            "strength": sum(float(r.get("strength") or 0.0) for r in group),
            "classification": "REACTION_ONLY",
        }

    mains = [
        dict(row)
        for row in active_zones
        if row.get("timeframe") == "H4"
        and row.get("direction") == "LONG"
        and bool(row.get("main_reversal_eligible"))
        and not bool(row.get("intraday_quarantined"))
    ]
    mains.sort(
        key=lambda row: (
            0.0
            if float(row["low"]) <= price <= float(row["high"])
            else min(abs(price - float(row["low"])), abs(price - float(row["high"]))),
            -float(row.get("main_reversal_score") or 0.0),
        )
    )
    main = dict(mains[0]) if mains else {}

    deeper = []
    if main:
        deeper = [
            dict(row)
            for row in mains[1:]
            if float(row.get("high") or 0.0) < float(main["low"])
        ]
        deeper.sort(key=lambda row: float(main["low"]) - float(row["high"]))
    next_main = dict(deeper[0]) if deeper else {}

    return {
        "state": "AVAILABLE" if (reaction or main) else "EMPTY",
        "nearest_reaction_support": reaction,
        "main_reversal_demand": main,
        "next_main_demand_if_failed": next_main,
        "note": "Reaction support and main H4 demand are displayed separately.",
    }
