from __future__ import annotations

from typing import Any

CONTRACT = "XAU_RIZAN_REACTION_INTERCEPTOR_V374"


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _role(row: dict[str, Any]) -> str:
    return str(
        row.get("current_role")
        or row.get("base_kind")
        or row.get("kind")
        or ""
    ).upper()


def _band(row: dict[str, Any], atr: float) -> tuple[float, float] | None:
    center = _f(row.get("price"))
    low = _f(row.get("band_low"))
    high = _f(row.get("band_high"))
    if center is None and (low is None or high is None):
        return None
    if low is None or high is None:
        width = max(0.08 * atr, 0.75)
        low = float(center) - width
        high = float(center) + width
    if high < low:
        low, high = high, low
    return float(low), float(high)


def _distance_to_band(price: float, low: float, high: float) -> float:
    if low <= price <= high:
        return 0.0
    if price < low:
        return low - price
    return price - high


def _candidate_levels(sd_eval: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    sr = _d(sd_eval.get("support_resistance_map"))
    levels = [_d(row) for row in list(sr.get("levels") or [])]
    fallback = (
        _d(sr.get("nearest_support"))
        if direction == "LONG"
        else _d(sr.get("nearest_resistance"))
    )
    if fallback:
        levels.append(fallback)

    wanted = "SUPPORT" if direction == "LONG" else "RESISTANCE"
    rows: list[dict[str, Any]] = []
    seen: set[tuple[float | None, str]] = set()
    for row in levels:
        role = _role(row)
        state = str(row.get("lifecycle_state") or "").upper()
        center = _f(row.get("price"))
        if center is None:
            continue
        if wanted not in role and wanted not in state:
            if direction == "LONG" and "DOWNSIDE_SWEEP" not in state:
                continue
            if direction == "SHORT" and "UPSIDE_SWEEP" not in state:
                continue
        key = (round(center, 4), state)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def _liquidity_near(
    sd_eval: dict[str, Any],
    *,
    direction: str,
    center: float,
    atr: float,
) -> list[dict[str, Any]]:
    relevant_side = "SELL_SIDE" if direction == "LONG" else "BUY_SIDE"
    rows: list[dict[str, Any]] = []
    for raw in list(sd_eval.get("liquidity_candidates") or []):
        row = _d(raw)
        price = _f(row.get("price"))
        side = str(row.get("side") or "").upper()
        if price is None or side not in {relevant_side, "BOTH"}:
            continue
        if abs(price - center) <= 0.30 * atr:
            rows.append(row)
    rows.sort(key=lambda row: abs(float(row.get("price") or center) - center))
    return rows[:4]


def evaluate_reaction_interceptor(
    sd_eval: dict[str, Any] | None,
    *,
    direction: str,
    context_alignment: str = "UNAVAILABLE",
) -> dict[str, Any]:
    """Promote a reaction/liquidity area before the deeper MAIN HTF zone.

    This layer is deliberately earlier than full MSS confirmation. It uses the
    already-causal S/R lifecycle plus nearby liquidity to decide whether a
    reaction area deserves REVERSAL WATCH or an EARLY DEMO probe candidate.
    It never creates live execution authority and never chases price after the
    reaction has already moved too far without an entry.
    """
    sd = _d(sd_eval)
    direction = str(direction or "WAIT").upper()
    price = _f(sd.get("price_now"))
    main = _d(sd.get("main_reversal_zone") or sd.get("decision_zone"))
    atr = _f(main.get("atr"))
    if atr is None or atr <= 0:
        width = None
        low = _f(main.get("low"))
        high = _f(main.get("high"))
        if low is not None and high is not None and high > low:
            width = high - low
        atr = max(float(width or 10.0), 1.0)

    empty = {
        "contract": CONTRACT,
        "state": "NONE",
        "promoted": False,
        "direction": direction,
        "execution_authority": False,
        "execution_scope": "SUMMARY_EARLY_INTERCEPTION",
    }
    if price is None or direction not in {"LONG", "SHORT"}:
        return empty

    main_low = _f(main.get("low"))
    main_high = _f(main.get("high"))
    candidates = []
    for row in _candidate_levels(sd, direction):
        band = _band(row, atr)
        if band is None:
            continue
        low, high = band
        center = (_f(row.get("price")) or (low + high) / 2.0)

        # Reaction candidates must sit before the deeper MAIN zone, not beyond it.
        if direction == "LONG" and main_high is not None and center < main_high - 0.10 * atr:
            continue
        if direction == "SHORT" and main_low is not None and center > main_low + 0.10 * atr:
            continue

        distance = _distance_to_band(price, low, high)
        liquidity = _liquidity_near(sd, direction=direction, center=center, atr=atr)
        state = str(row.get("lifecycle_state") or "UNKNOWN").upper()
        confirmed_flip = bool(row.get("confirmed_flip"))
        reclaim_required = bool(row.get("reclaim_required"))
        strength = _f(row.get("strength")) or 0.0

        strong_states = (
            {"DOWNSIDE_SWEEP_LIKE_REJECTION", "CONFIRMED_SUPPORT_FLIP"}
            if direction == "LONG"
            else {"UPSIDE_SWEEP_LIKE_REJECTION", "CONFIRMED_RESISTANCE_FLIP"}
        )
        watch_states = (
            {
                "ACTIVE_SUPPORT",
                "ACTIVE_FLIP_CONTEXT",
                "BULL_RETEST_IN_PROGRESS",
                "DOWNSIDE_SWEEP_LIKE_REJECTION",
                "CONFIRMED_SUPPORT_FLIP",
            }
            if direction == "LONG"
            else {
                "ACTIVE_RESISTANCE",
                "ACTIVE_FLIP_CONTEXT",
                "BEAR_RETEST_IN_PROGRESS",
                "UPSIDE_SWEEP_LIKE_REJECTION",
                "CONFIRMED_RESISTANCE_FLIP",
            }
        )

        score = 0
        if state in strong_states:
            score += 3
        elif state in watch_states:
            score += 1
        if confirmed_flip:
            score += 2
        if liquidity:
            score += 2
        if strength >= 1.5:
            score += 1
        if distance <= 0.20 * atr:
            score += 1
        if context_alignment == "SUPPORTIVE":
            score += 1
        elif context_alignment == "CONFLICT":
            score -= 2
        if reclaim_required:
            score -= 2

        candidates.append(
            {
                "source": row,
                "low": low,
                "high": high,
                "center": center,
                "distance": distance,
                "distance_atr": distance / atr,
                "liquidity": liquidity,
                "lifecycle_state": state,
                "confirmed_flip": confirmed_flip,
                "reclaim_required": reclaim_required,
                "score": score,
                "strong": state in strong_states or confirmed_flip,
                "watch": state in watch_states,
            }
        )

    if not candidates:
        return empty

    candidates.sort(
        key=lambda row: (
            row["distance_atr"],
            -row["score"],
            -(_f(_d(row["source"]).get("strength")) or 0.0),
        )
    )
    best = candidates[0]
    low = float(best["low"])
    high = float(best["high"])
    score = int(best["score"])
    strong = bool(best["strong"])
    liquidity = list(best["liquidity"])
    distance_atr = float(best["distance_atr"])

    favorable_move = (
        price > high + 0.65 * atr
        if direction == "LONG"
        else price < low - 0.65 * atr
    )
    if strong and favorable_move:
        state = "MISSED_NO_CHASE"
        promoted = True
        action = "Reversal reaction sudah bergerak terlalu jauh tanpa entry. Jangan chase; tunggu retest/refined pocket atau setup berikutnya."
    elif (
        strong
        and liquidity
        and score >= 5
        and context_alignment != "CONFLICT"
        and distance_atr <= 0.35
        and not best["reclaim_required"]
    ):
        state = f"EARLY_REACTION_{direction}"
        promoted = True
        action = (
            "Reaction/liquidity area dipromosikan menjadi early reversal candidate. "
            "Tidak perlu menunggu MAIN zone atau MSS penuh; gunakan hanya probe DEMO kecil dengan invalidation struktural."
        )
    elif strong and distance_atr <= 0.50:
        state = f"EARLY_REVERSAL_WATCH_{direction}"
        promoted = True
        action = "Ada rejection/role-flip awal di reaction zone. Pantau proximal reclaim/displacement awal; MAIN zone menjadi fallback, bukan syarat wajib disentuh."
    elif best["watch"] and distance_atr <= 0.75:
        state = f"REACTION_WATCH_{direction}"
        promoted = True
        action = "Harga berada dekat reaction/liquidity area. Pantau apakah area ini mengambil alih sebagai reversal candidate sebelum MAIN zone."
    else:
        state = "REACTION_AHEAD"
        promoted = False
        action = "Reaction level terpetakan tetapi belum cukup dekat/kuat untuk dipromosikan."

    invalidation = low - 0.12 * atr if direction == "LONG" else high + 0.12 * atr
    return {
        "contract": CONTRACT,
        "state": state,
        "promoted": promoted,
        "direction": direction,
        "candidate": {
            "low": low,
            "high": high,
            "center": best["center"],
            "lifecycle_state": best["lifecycle_state"],
            "score": score,
            "distance_atr": distance_atr,
            "strength": _f(_d(best["source"]).get("strength")),
            "sources": list(_d(best["source"]).get("sources") or []),
            "confirmed_flip": bool(best["confirmed_flip"]),
            "reclaim_required": bool(best["reclaim_required"]),
        },
        "nearby_liquidity": liquidity,
        "early_entry_band": {"low": low, "high": high},
        "invalidation": invalidation,
        "action": action,
        "main_zone_role": "DEEP_FALLBACK_NOT_MANDATORY_TOUCH" if promoted else "PRIMARY_HTF_FALLBACK",
        "execution_authority": False,
        "execution_scope": "SUMMARY_EARLY_INTERCEPTION",
        "no_chase": state == "MISSED_NO_CHASE",
    }
