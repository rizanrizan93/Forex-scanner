from __future__ import annotations

"""V408 mobile-first XAUUSD tiered zone visualisation.

The visual layer intentionally consumes the existing causal V405 reconstruction
instead of inventing chart levels.  It presents the two nearest mapped supply
and demand tiers in the same visual hierarchy traders commonly use: SELL 2,
SELL 1, current price, BUY 1, BUY 2.

This module is display-only.  It has no broker execution authority and does not
claim to reproduce a proprietary indicator formula.
"""

from math import isfinite
from typing import Any

from .xau_whalezone_reconstruction_v405 import evaluate_whalezone_reconstruction_v405

CONTRACT = "XAU_RIZAN_WHALEZONE_VISUAL_V408"
MODE = "TIERED_ZONE_VISUAL_MAP"
MAX_VISUAL_TIERS = 2


def _d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _f(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _zone(raw: dict[str, Any], *, side: str, tier: int) -> dict[str, Any]:
    row = _d(raw)
    low = _f(row.get("low"))
    high = _f(row.get("high"))
    if low is None or high is None:
        return {}
    if high < low:
        low, high = high, low
    if high <= low:
        return {}
    item = dict(row)
    item.update(
        {
            "low": low,
            "high": high,
            "center": (low + high) / 2.0,
            "tier": tier,
            "visual_label": f"RIZAN {side} {tier}",
        }
    )
    return item


def build_whalezone_visual_v408(sd_eval: dict[str, Any] | None) -> dict[str, Any]:
    """Build a deterministic display payload from the current V405 zone map."""
    sd = _d(sd_eval)
    base = _d(evaluate_whalezone_reconstruction_v405(sd))
    price = _f(base.get("price_now"))

    buy_zones: list[dict[str, Any]] = []
    for index, raw in enumerate(list(base.get("buy_zones") or [])[:MAX_VISUAL_TIERS], start=1):
        item = _zone(_d(raw), side="BUY", tier=index)
        if item:
            buy_zones.append(item)

    sell_zones: list[dict[str, Any]] = []
    for index, raw in enumerate(list(base.get("sell_zones") or [])[:MAX_VISUAL_TIERS], start=1):
        item = _zone(_d(raw), side="SELL", tier=index)
        if item:
            sell_zones.append(item)

    current_leg = _d(sd.get("current_leg_forecast"))
    leg_direction = str(current_leg.get("direction") or "").upper()
    target_price = _f(current_leg.get("target_price"))
    target_source = "CURRENT_LEG_FORECAST" if target_price is not None else ""

    # Fallback path is intentionally simple: when the runtime does not publish a
    # leg target, point to the nearest opposing tier rather than fabricating a
    # precise forecast level.
    if target_price is None:
        focus = str(base.get("direction") or "WAIT").upper()
        if leg_direction not in {"LONG", "SHORT"}:
            leg_direction = focus
        if leg_direction == "LONG" and sell_zones:
            target_price = float(sell_zones[0]["low"])
            target_source = "NEAREST_SELL_1_EDGE"
        elif leg_direction == "SHORT" and buy_zones:
            target_price = float(buy_zones[0]["high"])
            target_source = "NEAREST_BUY_1_EDGE"

    return {
        "contract": CONTRACT,
        "mode": MODE,
        "state": str(base.get("state") or "UNAVAILABLE"),
        "direction": str(base.get("direction") or "WAIT"),
        "reason": str(base.get("reason") or ""),
        "price_now": price,
        "atr_reference": _f(base.get("atr_reference")),
        "sell_zones": sell_zones,
        "buy_zones": buy_zones,
        "path": {
            "direction": leg_direction or "WAIT",
            "target_price": target_price,
            "target_source": target_source or "UNAVAILABLE",
        },
        "execution_authority": False,
        "proprietary_formula_claimed": False,
        "source_contract": base.get("contract"),
    }


def _price(value: Any) -> str:
    parsed = _f(value)
    return "—" if parsed is None else f"{parsed:,.2f}"


def _band(zone: dict[str, Any]) -> str:
    if not zone:
        return "—"
    return f"{_price(zone.get('low'))}–{_price(zone.get('high'))}"


def render_whalezone_visual_v408(sd_heartbeat: dict[str, Any] | None) -> None:
    """Render the V408 tiered zone map inside the canonical Streamlit dashboard."""
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    import streamlit as st

    hb = _d(sd_heartbeat)
    sd = _d(_d(hb.get("details")).get("evaluation"))

    st.markdown("## 🐳 RIZAN Zone Map")
    st.caption(
        "Peta otomatis SELL 1/2 dan BUY 1/2 dari S/D + S/R + liquidity geometry scanner. "
        "Tier 1 = zona aktif terdekat; Tier 2 = zona berikutnya. Level selalu mengikuti snapshot runtime, bukan angka hard-code."
    )

    if not sd:
        st.info("Zone Map menunggu heartbeat XAUUSD V342.")
        return

    payload = build_whalezone_visual_v408(sd)
    price = _f(payload.get("price_now"))
    sell_zones = [_d(row) for row in list(payload.get("sell_zones") or [])]
    buy_zones = [_d(row) for row in list(payload.get("buy_zones") or [])]
    path = _d(payload.get("path"))

    if price is None or not (sell_zones or buy_zones):
        st.warning("Belum ada geometry zona yang cukup untuk digambar.")
        return

    values: list[float] = [price]
    for row in sell_zones + buy_zones:
        values.extend([float(row["low"]), float(row["high"])])
    target = _f(path.get("target_price"))
    if target is not None:
        values.append(target)

    lo = min(values)
    hi = max(values)
    atr = _f(payload.get("atr_reference")) or 0.0
    span = max(hi - lo, atr, 10.0)
    padding = max(span * 0.08, atr * 0.25, 2.0)
    ymin, ymax = lo - padding, hi + padding

    fig, ax = plt.subplots(figsize=(7.0, 8.0))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#fffdfd")
    ax.set_xlim(0.0, 1.0)
    ax.set_ylim(ymin, ymax)
    ax.set_xticks([])
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:,.2f}"))
    ax.tick_params(axis="y", labelsize=10, colors="#303030", length=4)
    for side in ("left", "top", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["right"].set_color("#d0d0d0")

    # Draw farther tiers first so Tier 1 remains visually dominant when bands
    # are close or partially overlap.
    for row in reversed(sell_zones):
        tier = int(row.get("tier") or 1)
        alpha = 0.42 if tier == 1 else 0.26
        ax.axhspan(float(row["low"]), float(row["high"]), 0.03, 0.96, color="#f238a0", alpha=alpha, zorder=1)
        ax.text(
            0.53,
            float(row["center"]),
            str(row.get("visual_label") or f"RIZAN SELL {tier}"),
            ha="center",
            va="center",
            fontsize=14 if tier == 1 else 13,
            fontweight="bold",
            color="#1f1f1f",
            zorder=3,
        )
        ax.text(
            0.035,
            float(row["center"]),
            f"{row.get('timeframe','—')}  {_band(row)}",
            ha="left",
            va="center",
            fontsize=8.5,
            color="#4d2040",
            zorder=3,
        )

    for row in reversed(buy_zones):
        tier = int(row.get("tier") or 1)
        alpha = 0.78 if tier == 1 else 0.58
        ax.axhspan(float(row["low"]), float(row["high"]), 0.03, 0.96, color="#e2e2e2", alpha=alpha, zorder=1)
        ax.text(
            0.53,
            float(row["center"]),
            str(row.get("visual_label") or f"RIZAN BUY {tier}"),
            ha="center",
            va="center",
            fontsize=14 if tier == 1 else 13,
            fontweight="bold",
            color="#ec168c",
            zorder=3,
        )
        ax.text(
            0.035,
            float(row["center"]),
            f"{row.get('timeframe','—')}  {_band(row)}",
            ha="left",
            va="center",
            fontsize=8.5,
            color="#555555",
            zorder=3,
        )

    ax.axhline(price, color="#f0008c", linestyle=(0, (2, 3)), linewidth=1.8, zorder=4)
    ax.annotate(
        f" NOW  {_price(price)} ",
        xy=(0.965, price),
        xycoords="data",
        xytext=(6, 0),
        textcoords="offset points",
        ha="left",
        va="center",
        fontsize=10,
        color="white",
        bbox={"boxstyle": "round,pad=0.25", "fc": "#f0008c", "ec": "#f0008c"},
        zorder=6,
        annotation_clip=False,
    )

    if target is not None and abs(target - price) > 0.05:
        direction = str(path.get("direction") or "WAIT").upper()
        ax.annotate(
            "",
            xy=(0.75, target),
            xytext=(0.75, price),
            arrowprops={"arrowstyle": "-|>", "lw": 2.3, "color": "#686868", "mutation_scale": 16},
            zorder=5,
        )
        ax.text(
            0.77,
            (price + target) / 2.0,
            f"PATH {direction}",
            ha="left",
            va="center",
            fontsize=9,
            fontweight="bold",
            color="#5d5d5d",
            rotation=90 if abs(target - price) > span * 0.20 else 0,
            zorder=5,
        )

    ax.set_title("XAUUSD  •  RIZAN TIERED ZONE MAP", loc="left", fontsize=15, fontweight="bold", pad=12)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    sell1 = sell_zones[0] if len(sell_zones) >= 1 else {}
    sell2 = sell_zones[1] if len(sell_zones) >= 2 else {}
    buy1 = buy_zones[0] if len(buy_zones) >= 1 else {}
    buy2 = buy_zones[1] if len(buy_zones) >= 2 else {}

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("SELL 2", _band(sell2))
    c2.metric("SELL 1", _band(sell1))
    c3.metric("BUY 1", _band(buy1))
    c4.metric("BUY 2", _band(buy2))

    def meta(row: dict[str, Any]) -> str:
        if not row:
            return "—"
        return (
            f"{row.get('timeframe','—')} • {row.get('source_type','—')} • "
            f"{row.get('lifecycle_state','—')}"
        )

    st.caption(
        f"SELL1: {meta(sell1)} | BUY1: {meta(buy1)} | "
        f"Path target: {_price(path.get('target_price'))} ({path.get('target_source','UNAVAILABLE')}). "
        "Visual map = decision support; trigger entry tetap divalidasi M15 dan refinement M5."
    )


__all__ = [
    "CONTRACT",
    "MODE",
    "build_whalezone_visual_v408",
    "render_whalezone_visual_v408",
]
