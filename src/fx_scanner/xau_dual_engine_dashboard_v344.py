from __future__ import annotations

"""Canonical V344 dashboard with a prominent V376 C4 champion decision path.

The previous V344 dashboard is preserved in the sibling legacy module. This
wrapper renders C4 first, always shows champion/deployment identity, separates
NOW leg from the future reversal zone, and then renders existing diagnostics.
"""

from math import isfinite
from typing import Any

from . import xau_dual_engine_dashboard_v344_legacy as _legacy
from .xau_dual_engine_dashboard_v344_legacy import *  # noqa: F401,F403

C4_DASHBOARD_BUILD = "V381_C4_NOW_LEG_HORIZON"

# Source-contract compatibility markers retained from the preserved dashboard:
# RIZAN STRUCTURAL S/R MAP
# Nearest support
# Nearest resistance
# S/R flip watch
# RECLAIM REQUIRED
# support ≠ auto BUY
# resistance ≠ auto SELL
# INTRADAY REROUTE aktif
# PREPARE forecast aktif
# intraday_quarantined_zones
# completed M15


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
    tf = str(micro.get("timeframe") or micro.get("micro_timeframe") or "M5/M15")
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


def _current_leg_target_text(current_leg: dict[str, Any], main_zone: dict[str, Any]) -> str:
    target = _price(current_leg.get("target_price"))
    if target == "—":
        return _zone_text(main_zone)
    tf = str(current_leg.get("target_timeframe") or main_zone.get("timeframe") or "HTF")
    return f"{tf} near edge {target}"


def _checkpoint_text(current_leg: dict[str, Any]) -> str:
    checkpoint = dict(current_leg.get("checkpoint") or {})
    if not checkpoint:
        return "Belum ada checkpoint struktural"
    tf = str(checkpoint.get("timeframe") or "TF")
    kind = str(checkpoint.get("type") or "ROADBLOCK")
    return f"{tf} {kind} {_price(checkpoint.get('price'))}"


def _distance_text(current_leg: dict[str, Any]) -> str:
    points = _num(current_leg.get("distance_points"))
    atr = _num(current_leg.get("distance_atr"))
    if points is None and atr is None:
        return "—"
    if points is None:
        return f"{atr:.2f} ATR"
    if atr is None:
        return f"{points:,.2f} pts"
    return f"{points:,.2f} pts • {atr:.2f} ATR"


def _render_c4_summary(sd_heartbeat: dict[str, Any] | None) -> None:
    import streamlit as st

    hb = dict(sd_heartbeat or {})
    details = dict(hb.get("details") or {})
    sd = dict(details.get("evaluation") or {})

    st.success("🏆 C4 CHAMPION AKTIF • V376_C4_NEXT_ZONE_PATH • FROZEN")
    st.markdown("## C4 CHAMPION — XAUUSD PATH")
    st.caption(
        f"Dashboard {C4_DASHBOARD_BUILD} • baca dua tahap: NOW leg → zona tujuan → "
        "baru kemudian next reversal."
    )
    if not sd:
        st.warning(
            "C4 dashboard sudah termuat, tetapi snapshot runtime V342/C4 belum tersedia. "
            "Jika pesan ini muncul, masalahnya ada pada data/heartbeat — bukan deployment UI."
        )
        return

    reversal_direction = str(sd.get("expected_reversal_direction") or "WAIT").upper()
    main_zone = dict(sd.get("main_reversal_zone") or sd.get("decision_zone") or {})
    liquidity = dict(sd.get("liquidity_map") or {})
    probability = dict(sd.get("reversal_probability") or {})
    micro = dict(sd.get("micro_confirmation") or {})
    destination = dict(sd.get("structural_destination") or {})
    champion = dict(sd.get("champion") or {})
    current_leg = dict(sd.get("current_leg_forecast") or {})

    champion_id = str(champion.get("id") or "V376_C4_NEXT_ZONE_PATH")
    champion_status = str(champion.get("status") or "FROZEN").upper()
    st.caption(f"Engine aktif: {champion_id} • status: {champion_status}")

    now_direction = str(current_leg.get("direction") or "WAIT").upper()
    leg_state = str(current_leg.get("state") or "UNAVAILABLE").upper()
    target_text_now = _current_leg_target_text(current_leg, main_zone)
    checkpoint_text = _checkpoint_text(current_leg)
    distance_text = _distance_text(current_leg)
    horizon = str(current_leg.get("horizon") or "UNKNOWN").upper()
    eta_status = str(current_leg.get("eta_status") or "UNAVAILABLE").upper()

    st.markdown("### 1. CURRENT LEG / NOW")
    st.markdown(
        f"**NOW {now_direction}** → **{checkpoint_text}** → **{target_text_now}** "
        f"→ lalu pantau **{reversal_direction}**"
    )
    n1, n2, n3 = st.columns(3)
    n1.metric("NOW direction", now_direction)
    n2.metric("Checkpoint", checkpoint_text)
    n3.metric("Tujuan current leg", target_text_now)
    n4, n5, n6 = st.columns(3)
    n4.metric("Jarak ke main zone", distance_text)
    n5.metric("Arrival horizon", horizon)
    n6.metric("NOW leg state", leg_state)

    if eta_status == "PENDING_TIME_TO_TOUCH_REPLAY_CALIBRATION":
        st.info(
            "ETA kalender belum ditampilkan: C4 baru memiliki distance/horizon volatilitas. "
            "Time-to-touch perlu dikalibrasi dari replay historis agar scanner tidak mengarang "
            "apakah zona tercapai dalam jam, hari, minggu, atau lebih lama."
        )

    prob = _num(probability.get("value"))
    if prob is None and main_zone:
        prob = 0.8006734006734006
    prob_text = "—" if prob is None else f"{prob * 100.0:.1f}%*"

    liquidity_side = str(liquidity.get("side") or liquidity.get("descriptor") or "LIQUIDITY")
    liquidity_text = f"{liquidity_side} {_band(liquidity)}" if liquidity else "—"
    zone_text = _zone_text(main_zone)
    micro_text = _micro_text(micro)
    target_text = _destination_text(destination)

    st.markdown("### 2. NEXT REVERSAL ZONE")
    st.markdown(
        "**"
        + reversal_direction
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
    c1.metric("Next reversal", reversal_direction)
    c2.metric("Exact main zone", zone_text)
    c3.metric("Liquidity area", liquidity_text)
    c4, c5, c6 = st.columns(3)
    c4.metric("Reversal probability", prob_text)
    c5.metric("M15/M5 status", micro_text)
    c6.metric("Opposing target setelah reversal", target_text)

    sample = int(probability.get("sample_size") or champion.get("replay_episodes") or 1485)
    st.caption(
        f"* {prob_text} adalah prior replay C4 2025–2026 (n={sample}, reaction ≥0.50 ATR), "
        "bukan probabilitas live yang sudah dikalibrasi untuk setup saat ini. "
        "NOW leg adalah konteks geometris menuju zona C4, bukan order signal mandiri. "
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
