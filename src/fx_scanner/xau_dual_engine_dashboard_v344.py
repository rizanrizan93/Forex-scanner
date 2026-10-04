from __future__ import annotations

"""Canonical V344 dashboard with a compact V376 C4 champion decision path.

The previous V344 dashboard is preserved in the sibling legacy module. This
wrapper adds one decision-first strip above it and then renders all existing
diagnostics unchanged.
"""

from math import isfinite
from typing import Any

from . import xau_dual_engine_dashboard_v344_legacy as _legacy
from .xau_dual_engine_dashboard_v344_legacy import *  # noqa: F401,F403


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _price(value: Any) -> str:
    parsed = _num(value)
    return "—" if parsed is None else f"{parsed:,.2f}"


def _band(row: dict[str, Any]) -> str:
    if not row:
        return "—"
    return f"{_price(row.get('low'))}–{_price(row.get('high'))}"


def _zone_text(zone: dict[str, Any]) -> str:
    if not zone:
        return "—"
    direction = str(zone.get("direction") or "").upper()
    kind = "DEMAND" if direction == "LONG" else "SUPPLY" if direction == "SHORT" else "ZONE"
    path = dict(zone.get("next_zone_path") or {})
    rank = path.get("path_rank")
    rank_text = f" • path #{rank}" if rank is not None else ""
    return f"{zone.get('timeframe','—')} {kind} {_band(zone)}{rank_text}"


def _micro_text(micro: dict[str, Any]) -> str:
    if not micro:
        return "WAIT / belum tersedia"
    tf = str(micro.get("timeframe") or "M5/M15")
    status = str(
        micro.get("label")
        or micro.get("stage")
        or micro.get("state")
        or "WAIT"
    )
    return f"{tf} • {status}"


def _destination_text(destination: dict[str, Any]) -> str:
    if not destination:
        return "—"
    tf = destination.get("timeframe") or "HTF"
    kind = destination.get("type") or destination.get("zone_type") or "OPPOSING"
    return f"{tf} {kind} {_band(destination)}"


def _render_c4_summary(sd_heartbeat: dict[str, Any] | None) -> None:
    import streamlit as st

    hb = dict(sd_heartbeat or {})
    details = dict(hb.get("details") or {})
    sd = dict(details.get("evaluation") or {})

    st.markdown("### C4 CHAMPION — XAUUSD DECISION PATH")
    st.caption(
        "Frozen V376 C4 path-rank selector • urutan baca: arah → next main zone → "
        "liquidity → reversal prior → M15/M5 → opposing target."
    )
    if not sd:
        st.info("Snapshot C4/V342 belum tersedia dari runtime.")
        return

    direction = str(sd.get("expected_reversal_direction") or "WAIT").upper()
    main_zone = dict(sd.get("main_reversal_zone") or sd.get("decision_zone") or {})
    liquidity = dict(sd.get("liquidity_map") or {})
    probability = dict(sd.get("reversal_probability") or {})
    micro = dict(sd.get("micro_confirmation") or {})
    destination = dict(sd.get("structural_destination") or {})
    champion = dict(sd.get("champion") or {})

    prob = _num(probability.get("value"))
    # Backward-compatible display while the first promoted worker heartbeat rolls in.
    if prob is None and main_zone:
        prob = 0.8006734006734006
    prob_text = "—" if prob is None else f"{prob * 100.0:.1f}%*"

    liquidity_side = str(liquidity.get("side") or liquidity.get("descriptor") or "LIQUIDITY")
    liquidity_text = (
        f"{liquidity_side} {_band(liquidity)}" if liquidity else "—"
    )
    zone_text = _zone_text(main_zone)
    micro_text = _micro_text(micro)
    target_text = _destination_text(destination)

    st.markdown(
        "**"
        + direction
        + "** → **"
        + zone_text
        + "** → **"
        + liquidity_text
        + "** → **"
        + prob_text
        + "** → **"
        + micro_text
        + "** → **"
        + target_text
        + "**"
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Arah", direction)
    c2.metric("Next main zone", zone_text)
    c3.metric("Liquidity area", liquidity_text)
    c4, c5, c6 = st.columns(3)
    c4.metric("Reversal probability", prob_text)
    c5.metric("M15/M5 status", micro_text)
    c6.metric("Opposing target", target_text)

    champion_id = str(champion.get("id") or "V376_C4_NEXT_ZONE_PATH")
    sample = int(probability.get("sample_size") or champion.get("replay_episodes") or 1485)
    st.caption(
        f"* {prob_text} adalah prior replay C4 2025–2026 (n={sample}, reaction ≥0.50 ATR), "
        "bukan probabilitas live yang sudah dikalibrasi untuk setup saat ini. "
        f"Champion: {champion_id}."
    )


def render_xau_dual_engine_dashboard(
    *,
    sd_heartbeat: dict[str, Any] | None,
    friend_heartbeat: dict[str, Any] | None,
    event_heartbeat: dict[str, Any] | None = None,
    macro_heartbeat: dict[str, Any] | None = None,
) -> None:
    _render_c4_summary(sd_heartbeat)
    _legacy.render_xau_dual_engine_dashboard(
        sd_heartbeat=sd_heartbeat,
        friend_heartbeat=friend_heartbeat,
        event_heartbeat=event_heartbeat,
        macro_heartbeat=macro_heartbeat,
    )


def __getattr__(name: str) -> Any:
    return getattr(_legacy, name)
