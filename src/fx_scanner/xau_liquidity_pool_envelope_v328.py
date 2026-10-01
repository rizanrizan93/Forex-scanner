from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from statistics import mean
from typing import Any, Iterable, Sequence

from .xau_liquidity_sweep_map_v317 import (
    build_liquidity_sweep_map as build_v317_map,
)

CONTRACT = "XAU_LIQUIDITY_POOL_ENVELOPE_V328_1"
POLICY_EFFECT = "STRUCTURAL_CONTEXT_ONLY"
EXECUTION_INFLUENCE = False
EXECUTION_AUTHORITY = False
PROMOTION_AUTHORITY = False

PIVOT_LEFT = 2
PIVOT_RIGHT = 2
BAR_LOOKBACK = 192
MAX_SWEEP_EXTENSION_ATR = 1.25


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bars(atlas: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in list(atlas.get("chart_bars_m15") or [])[-BAR_LOOKBACK:]:
        item = dict(raw or {})
        high = _f(item.get("high"))
        low = _f(item.get("low"))
        close = _f(item.get("close"))
        when = _dt(item.get("time") or item.get("timestamp"))
        if high is None or low is None or close is None or when is None or high < low:
            continue
        rows.append(
            {
                "time": when,
                "high": high,
                "low": low,
                "close": close,
            }
        )
    rows.sort(key=lambda row: row["time"])
    return rows


def _pivot_levels(
    rows: Sequence[dict[str, Any]],
    *,
    side: str,
) -> list[dict[str, Any]]:
    if len(rows) < PIVOT_LEFT + PIVOT_RIGHT + 1:
        return []
    output: list[dict[str, Any]] = []
    field = "high" if side == "HIGH" else "low"
    for index in range(PIVOT_LEFT, len(rows) - PIVOT_RIGHT):
        value = float(rows[index][field])
        left = [float(rows[j][field]) for j in range(index - PIVOT_LEFT, index)]
        right = [float(rows[j][field]) for j in range(index + 1, index + PIVOT_RIGHT + 1)]
        if side == "HIGH":
            valid = value >= max(left) and value >= max(right)
        else:
            valid = value <= min(left) and value <= min(right)
        if not valid:
            continue
        output.append(
            {
                "price": value,
                "source": f"M15_SWING_{side}",
                "time": rows[index]["time"],
            }
        )
    return output


def _cluster_levels(
    levels: Sequence[dict[str, Any]],
    *,
    tolerance: float,
    side: str,
) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(row) for row in levels if _f(dict(row).get("price")) is not None),
        key=lambda row: float(row["price"]),
    )
    if not ordered:
        return []

    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = [ordered[0]]
    for row in ordered[1:]:
        centre = mean(float(item["price"]) for item in current)
        if abs(float(row["price"]) - centre) <= tolerance:
            current.append(row)
        else:
            clusters.append(current)
            current = [row]
    clusters.append(current)

    result: list[dict[str, Any]] = []
    for cluster in clusters:
        prices = [float(item["price"]) for item in cluster]
        latest = max(
            (item.get("time") for item in cluster if isinstance(item.get("time"), datetime)),
            default=None,
        )
        repeated = len(cluster) >= 2
        source = f"M15_EQUAL_{side}S" if repeated else f"M15_SWING_{side}"
        representative = max(prices) if side == "HIGH" else min(prices)
        result.append(
            {
                "price": representative,
                "pool_low": min(prices) - tolerance * 0.25,
                "pool_high": max(prices) + tolerance * 0.25,
                "touch_count": len(cluster),
                "source": source,
                "latest_at": None if latest is None else latest.isoformat(),
            }
        )
    return result


def _recent_extreme(
    rows: Sequence[dict[str, Any]],
    *,
    side: str,
    count: int,
) -> dict[str, Any] | None:
    sample = list(rows)[-count:]
    if not sample:
        return None
    if side == "HIGH":
        row = max(sample, key=lambda item: float(item["high"]))
        price = float(row["high"])
    else:
        row = min(sample, key=lambda item: float(item["low"]))
        price = float(row["low"])
    return {
        "price": price,
        "pool_low": price,
        "pool_high": price,
        "touch_count": 1,
        "source": f"RECENT_{count}_M15_{side}",
        "latest_at": row["time"].isoformat(),
    }


def _round_levels(
    *,
    boundary: float,
    direction: str,
    extension: float,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for step in (5.0, 10.0):
        if direction == "SHORT":
            level = (int(boundary / step) + 1) * step
            if level <= boundary + 1e-9:
                level += step
        else:
            level = int(boundary / step) * step
            if level >= boundary - 1e-9:
                level -= step
        if direction == "SHORT" and level > boundary + extension + 1e-9:
            continue
        if direction == "LONG" and level < boundary - extension - 1e-9:
            continue
        output.append(
            {
                "price": float(level),
                "pool_low": float(level),
                "pool_high": float(level),
                "touch_count": 1,
                "source": f"ROUND_{int(step)}",
                "latest_at": None,
            }
        )
    return output


def _dedupe_pools(
    rows: Iterable[dict[str, Any]],
    *,
    tolerance: float,
    direction: str,
) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(row) for row in rows if _f(dict(row).get("price")) is not None),
        key=lambda row: float(row["price"]),
    )
    merged: list[dict[str, Any]] = []
    for row in ordered:
        price = float(row["price"])
        match = None
        for item in merged:
            if abs(price - float(item["price"])) <= tolerance:
                match = item
                break
        if match is None:
            merged.append(
                {
                    "price": price,
                    "low": float(row.get("pool_low") if row.get("pool_low") is not None else price),
                    "high": float(row.get("pool_high") if row.get("pool_high") is not None else price),
                    "sources": [str(row.get("source") or "LIQUIDITY")],
                    "touch_count": int(row.get("touch_count") or 1),
                    "latest_at": row.get("latest_at"),
                }
            )
            continue
        match["low"] = min(float(match["low"]), float(row.get("pool_low") if row.get("pool_low") is not None else price))
        match["high"] = max(float(match["high"]), float(row.get("pool_high") if row.get("pool_high") is not None else price))
        match["touch_count"] = int(match.get("touch_count") or 0) + int(row.get("touch_count") or 1)
        source = str(row.get("source") or "LIQUIDITY")
        if source not in match["sources"]:
            match["sources"].append(source)
        latest = _dt(row.get("latest_at"))
        current_latest = _dt(match.get("latest_at"))
        if latest is not None and (current_latest is None or latest > current_latest):
            match["latest_at"] = latest.isoformat()

    for item in merged:
        # Equal highs/lows and multi-source pools are stronger context, but this
        # score never authorizes execution.
        source_count = len(item.get("sources") or [])
        touches = int(item.get("touch_count") or 0)
        item["confluence_score"] = min(100, 20 * source_count + 15 * min(touches, 4))
        item["side"] = "ABOVE_SUPPLY" if direction == "SHORT" else "BELOW_DEMAND"

    merged.sort(
        key=lambda row: (
            float(row["price"]) if direction == "SHORT" else -float(row["price"]),
            -int(row.get("confluence_score") or 0),
        )
    )
    return merged


def build_liquidity_pool_envelope(
    *,
    atlas_evaluation: dict[str, Any],
    style_path: dict[str, Any] | None = None,
    price_now: float | None = None,
) -> dict[str, Any]:
    """Add causal M15 liquidity pools to the V317 structural sweep envelope.

    The map is deliberately a danger/reversal-validation layer. It does not
    predict that every pool must be swept and never grants entry authority.
    """
    atlas = dict(atlas_evaluation or {})
    style = dict(style_path or {})
    base = build_v317_map(
        atlas_evaluation=atlas,
        style_path=style,
        price_now=price_now,
    )
    decision = dict(base.get("decision_zone") or {})
    if not decision:
        return {
            **base,
            "contract": CONTRACT,
            "state": "NO_DECISION_ZONE",
            "liquidity_pools": [],
            "primary_liquidity_pool": None,
            "execution_influence": False,
            "execution_authority": False,
            "promotion_authority": False,
        }

    direction = str(decision.get("direction") or "").upper()
    low = float(decision["low"])
    high = float(decision["high"])
    atr = _f(decision.get("atr_points"))
    if atr is None:
        atr = max(high - low, 1.0)
    boundary = high if direction == "SHORT" else low
    extension = max(2.0, MAX_SWEEP_EXTENSION_ATR * atr)
    tolerance = max(0.50, min(2.50, 0.07 * atr))

    rows = _bars(atlas)
    side = "HIGH" if direction == "SHORT" else "LOW"
    pivots = _pivot_levels(rows, side=side)
    pools = _cluster_levels(pivots, tolerance=tolerance, side=side)

    recent_24h = _recent_extreme(rows, side=side, count=96)
    recent_12h = _recent_extreme(rows, side=side, count=48)
    extras = [row for row in (recent_24h, recent_12h) if row is not None]
    extras.extend(
        _round_levels(
            boundary=boundary,
            direction=direction,
            extension=extension,
        )
    )

    # Preserve V317 parent-zone/liquidity evidence as additional pool sources.
    for raw in list(base.get("liquidity_levels") or []):
        row = dict(raw or {})
        price = _f(row.get("price"))
        if price is None:
            continue
        extras.append(
            {
                "price": price,
                "pool_low": price,
                "pool_high": price,
                "touch_count": 1,
                "source": str(row.get("source") or "V317_LIQUIDITY"),
                "latest_at": None,
            }
        )
    for raw in list(base.get("same_direction_parent_zones") or []):
        zone = dict(raw or {})
        if direction == "SHORT":
            price = _f(zone.get("high"))
            source = f"{str(zone.get('timeframe') or 'HTF')}_PARENT_HIGH"
        else:
            price = _f(zone.get("low"))
            source = f"{str(zone.get('timeframe') or 'HTF')}_PARENT_LOW"
        if price is None:
            continue
        extras.append(
            {
                "price": price,
                "pool_low": price,
                "pool_high": price,
                "touch_count": 1,
                "source": source,
                "latest_at": None,
            }
        )

    relevant: list[dict[str, Any]] = []
    for row in pools + extras:
        price = float(row["price"])
        if direction == "SHORT":
            if price < high - tolerance or price > boundary + extension + 1e-9:
                continue
        else:
            if price > low + tolerance or price < boundary - extension - 1e-9:
                continue
        relevant.append(row)

    merged = _dedupe_pools(
        relevant,
        tolerance=tolerance,
        direction=direction,
    )

    # Sort from zone edge outward; the first meaningful pool is the immediate
    # liquidity objective, while the farthest admitted pool defines the maximum
    # structural danger envelope.
    if direction == "SHORT":
        merged.sort(key=lambda row: (abs(float(row["price"]) - high), -int(row["confluence_score"])))
    else:
        merged.sort(key=lambda row: (abs(float(row["price"]) - low), -int(row["confluence_score"])))

    primary = merged[0] if merged else None
    band = dict(base.get("sweep_band") or {"low": low, "high": high})
    band_low = float(band.get("low") or low)
    band_high = float(band.get("high") or high)
    if merged:
        if direction == "SHORT":
            far = max(float(row["high"]) for row in merged)
            band_high = min(boundary + extension, max(band_high, far))
        else:
            far = min(float(row["low"]) for row in merged)
            band_low = max(boundary - extension, min(band_low, far))

    depth = max(0.0, band_high - high) if direction == "SHORT" else max(0.0, low - band_low)
    confluence = max(
        int(base.get("liquidity_confluence_count") or 0),
        max((len(row.get("sources") or []) for row in merged), default=0),
    )
    parent_extension = bool(
        base.get("parent_extension_present")
        or (direction == "SHORT" and band_high > high + 1e-9)
        or (direction == "LONG" and band_low < low - 1e-9)
    )

    # A repeated/clustered pool beyond the narrow zone is itself a warning,
    # even when the atlas has no explicit parent-zone liquidity metadata.
    clustered = any(
        int(row.get("touch_count") or 0) >= 2
        or len(row.get("sources") or []) >= 2
        for row in merged
    )
    depth_atr = depth / max(atr, 1e-12)
    risk_score = 0
    if parent_extension:
        risk_score += 2
    if clustered:
        risk_score += 2
    if depth_atr >= 0.25:
        risk_score += 2
    elif depth_atr > 0:
        risk_score += 1
    risk_grade = "HIGH" if risk_score >= 4 else "MEDIUM" if risk_score >= 2 else "LOW"

    price = _f(price_now)
    relation = "UNKNOWN"
    if price is not None:
        if low <= price <= high:
            relation = "INSIDE_DECISION_ZONE"
        elif band_low <= price <= band_high:
            relation = "INSIDE_LIQUIDITY_SWEEP_BAND"
        elif price < band_low:
            relation = "BELOW_MAP"
        else:
            relation = "ABOVE_MAP"

    return {
        **base,
        "contract": CONTRACT,
        "state": "LIQUIDITY_POOL_ENVELOPE_AVAILABLE",
        "liquidity_pools": merged[:10],
        "primary_liquidity_pool": primary,
        "pool_tolerance_usd": tolerance,
        "pool_detection": {
            "bars_used": len(rows),
            "pivot_left": PIVOT_LEFT,
            "pivot_right": PIVOT_RIGHT,
            "lookback_bars": BAR_LOOKBACK,
            "max_extension_atr": MAX_SWEEP_EXTENSION_ATR,
            "sources": [
                "M15_SWING_HIGH_LOW",
                "M15_EQUAL_HIGH_LOW_CLUSTER",
                "RECENT_12H_24H_EXTREME",
                "ROUND_5_10",
                "V317_PARENT_AND_ZONE_LIQUIDITY",
            ],
        },
        "sweep_band": {
            "low": band_low,
            "high": band_high,
            "depth_usd": depth,
            "depth_atr": depth_atr,
        },
        "liquidity_confluence_count": confluence,
        "parent_extension_present": parent_extension,
        "clustered_liquidity_present": clustered,
        "risk_grade": risk_grade,
        "price_relation": relation,
        "first_touch_warning": bool(
            risk_grade in {"HIGH", "MEDIUM"}
            and (parent_extension or clustered)
        ),
        "confirmation_required": (
            "DO_NOT_FADE_ZONE_EDGE; WAIT_LIQUIDITY_SWEEP_EXHAUSTION_AND_"
            "M5_M15_RECLAIM_MSS_DISPLACEMENT"
        ),
        "interpretation": (
            "V328 expands the structural decision zone into a causal liquidity-pool "
            "danger envelope using recent M15 swing/equal-high-low clusters, recent "
            "extremes, round levels and parent zones. It maps where a stop-run may "
            "extend before reversal; it does not predict an exact reversal price."
        ),
        "policy_effect": POLICY_EFFECT,
        "execution_influence": EXECUTION_INFLUENCE,
        "execution_authority": EXECUTION_AUTHORITY,
        "promotion_authority": PROMOTION_AUTHORITY,
    }
