from __future__ import annotations

"""Canonical XAU dashboard with a simple AFIQ-style decision card first.

V393 keeps the detailed V376/C4 and legacy diagnostics available for audit, but
moves them behind an expander. The first screen now answers the questions the
trader actually needs: where is the nearest reversal zone, which direction is
expected from it, what is the entry/invalidation/target geometry, and why DEMO
execution is READY/WAIT/BLOCKED.
"""

from math import isfinite
from typing import Any

from . import xau_dual_engine_dashboard_v344_legacy as _legacy
from .xau_dual_engine_dashboard_v344_legacy import *  # noqa: F401,F403
from .xau_public_hot_v362 import fetch_public_hot_snapshot
from .xau_simple_reversal_engine_v390 import evaluate_simple_reversal

C4_DASHBOARD_BUILD = "V393_SIMPLE_ROOT_V390_PLUS_V376"
EXECUTOR_WORKER = "ctrader_demo_xau_v351_executor"


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
    status = str(micro.get("label") or micro.get("stage") or micro.get("state") or "WAIT")
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


def _read_executor_hot() -> dict[str, Any]:
    try:
        hot = fetch_public_hot_snapshot()
    except Exception:
        return {}
    rows = [dict(row or {}) for row in list(hot.get("heartbeats") or [])]
    candidates = [row for row in rows if row.get("worker_name") == EXECUTOR_WORKER]
    if not candidates:
        return {}
    candidates.sort(key=lambda row: str(row.get("observed_at") or ""), reverse=True)
    return candidates[0]


def _readiness(value: Any) -> str:
    raw = str(value or "NONE").upper()
    return {
        "READY_EARLY": "READY",
        "WATCH_REACTION": "WATCH",
        "PREPARE": "PREPARE",
        "WAIT": "WAIT",
        "NONE": "NONE",
    }.get(raw, raw.replace("_", " "))


def _render_simple_root(sd_heartbeat: dict[str, Any] | None) -> None:
    import streamlit as st

    hb = dict(sd_heartbeat or {})
    sd = dict(dict(hb.get("details") or {}).get("evaluation") or {})
    st.markdown("## 🎯 Keputusan XAUUSD sekarang")
    st.caption(
        "Baca dari atas ke bawah: harga → zona reversal lokal → arah → entry/invalidation/target → status executor DEMO. "
        "Supply/demand HTF jauh hanya konteks/destination, bukan alasan menunggu tanpa entry."
    )
    if not sd:
        st.warning("Snapshot engine XAUUSD belum tersedia.")
        return

    plan = dict(evaluate_simple_reversal(sd) or {})
    state = str(plan.get("state") or "UNAVAILABLE").upper()
    direction = str(plan.get("direction") or "WAIT").upper()
    long_zone = dict(plan.get("long_zone") or {})
    short_zone = dict(plan.get("short_zone") or {})
    selected = dict(plan.get("selected_zone") or {})
    entry = dict(plan.get("entry") or {})
    behavior = dict(sd.get("afiq_behavioral") or {})
    acceptance = dict(behavior.get("acceptance_rejection") or {})
    m30 = dict(behavior.get("m30_internal") or {})

    executor_hb = _read_executor_hot()
    executor_details = dict(executor_hb.get("details") or {})
    executor_state = str(executor_details.get("state") or "UNAVAILABLE").upper()
    executor_reason = str(executor_details.get("reason") or "NO_HEARTBEAT")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Harga", _price(plan.get("price_now")))
    c2.metric("Decision", state.replace("_", " "))
    c3.metric("Arah", direction)
    c4.metric("DEMO executor", executor_state)

    if state == "READY_LONG":
        st.success("**READY LONG** — demand lokal aktif dan evidence reversal awal sudah cukup.")
    elif state == "READY_SHORT":
        st.error("**READY SHORT** — supply lokal aktif dan evidence reversal awal sudah cukup.")
    elif state in {"WATCH_LONG", "PREPARE_LONG"}:
        st.warning("**PREPARE / WATCH LONG** — fokus demand lokal; tunggu reaksi, jangan entry di tengah range.")
    elif state in {"WATCH_SHORT", "PREPARE_SHORT"}:
        st.warning("**PREPARE / WATCH SHORT** — fokus supply lokal; tunggu reaksi, jangan entry di tengah range.")
    elif state == "RANGE_WAIT":
        st.info("**RANGE WAIT** — harga masih di antara demand dan supply lokal. Zona dua sisi tetap dipetakan di bawah.")
    else:
        st.info("Belum ada trigger aktif; scanner tetap menampilkan dua zona reversal terdekat.")

    z1, z2 = st.columns(2)
    with z1:
        st.markdown("### 🟢 Demand → LONG")
        st.metric("Zona", _band(long_zone))
        st.metric("Status", _readiness(plan.get("long_readiness")))
        if long_zone:
            st.caption(
                f"source={long_zone.get('source_type','—')} • lifecycle={long_zone.get('lifecycle_state','—')} • "
                f"distance={float(long_zone.get('distance_atr') or 0):.2f} ATR"
            )
    with z2:
        st.markdown("### 🔴 Supply → SHORT")
        st.metric("Zona", _band(short_zone))
        st.metric("Status", _readiness(plan.get("short_readiness")))
        if short_zone:
            st.caption(
                f"source={short_zone.get('source_type','—')} • lifecycle={short_zone.get('lifecycle_state','—')} • "
                f"distance={float(short_zone.get('distance_atr') or 0):.2f} ATR"
            )

    st.markdown("### Entry / invalidation / target")
    if selected:
        e1, e2, e3, e4 = st.columns(4)
        e1.metric("Arah", direction)
        e2.metric("Entry band", f"{_price(entry.get('low'))}–{_price(entry.get('high'))}")
        e3.metric("Invalidation", _price(entry.get("invalidation")))
        e4.metric("TP1 local", _price(entry.get("tp1_opposite_local_zone")))
    else:
        st.info("Belum ada entry band aktif karena harga belum dekat/masuk zona. Demand dan supply di atas adalah PRE-MAP, bukan blank.")

    local_range = dict(plan.get("range") or {})
    if local_range:
        r1, r2, r3 = st.columns(3)
        r1.metric("Local floor", _price(local_range.get("floor")))
        r2.metric("Local mid", _price(local_range.get("mid")))
        r3.metric("Local ceiling", _price(local_range.get("ceiling")))

    st.markdown("### AFIQ-style context")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Behavior", str(behavior.get("manual_decision_state") or "—").replace("_", " "))
    a2.metric("Acceptance / rejection", str(acceptance.get("state") or "—").replace("_", " "))
    a3.metric("M30 internal", str(m30.get("state") or "—").replace("_", " "))
    a4.metric("DEMO behavior gate", str(behavior.get("demo_entry_gate") or "—").replace("_", " "))

    current_leg = dict(sd.get("current_leg_forecast") or {})
    main_zone = dict(sd.get("main_reversal_zone") or sd.get("decision_zone") or {})
    if current_leg:
        now_dir = str(current_leg.get("direction") or "WAIT").upper()
        next_rev = str(current_leg.get("next_reversal_direction") or sd.get("expected_reversal_direction") or "WAIT").upper()
        st.caption(
            "HTF path context: "
            f"NOW {now_dir} → {_current_leg_target_text(current_leg, main_zone)} → lalu pantau {next_rev}. "
            "Ini context, bukan trigger entry lokal."
        )

    st.markdown("### Status auto-order DEMO")
    if executor_state == "ORDER_ACCEPTED":
        st.success(f"ORDER ACCEPTED • {executor_reason}")
    elif executor_state == "BLOCKED":
        st.error(f"BLOCKED • {executor_reason}")
    elif executor_state in {"WAIT", "DUPLICATE_BLOCK", "ORDER_NOT_ACCEPTED"}:
        st.warning(f"{executor_state} • {executor_reason}")
    else:
        st.info(f"{executor_state} • {executor_reason}")
    observed = str(executor_hb.get("observed_at") or "")
    if observed:
        st.caption(f"Executor heartbeat: {observed} • DEMO only • LIVE auto-execution OFF")


def _render_c4_summary(sd_heartbeat: dict[str, Any] | None) -> None:
    import streamlit as st

    hb = dict(sd_heartbeat or {})
    details = dict(hb.get("details") or {})
    sd = dict(details.get("evaluation") or {})

    st.success("🏆 C4 CHAMPION AKTIF • V376_C4_NEXT_ZONE_PATH • FROZEN")
    st.markdown("### C4 HTF PATH / AUDIT")
    st.caption(
        f"Dashboard {C4_DASHBOARD_BUILD} • NOW leg → zona tujuan HTF → next reversal."
    )
    if not sd:
        st.warning("Snapshot runtime V342/C4 belum tersedia.")
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
    now_direction = str(current_leg.get("direction") or "WAIT").upper()
    target_text_now = _current_leg_target_text(current_leg, main_zone)
    checkpoint_text = _checkpoint_text(current_leg)

    st.markdown(
        f"**NOW {now_direction}** → **{checkpoint_text}** → **{target_text_now}** → lalu pantau **{reversal_direction}**"
    )
    n1, n2, n3 = st.columns(3)
    n1.metric("Jarak HTF", _distance_text(current_leg))
    n2.metric("Horizon", str(current_leg.get("horizon") or "UNKNOWN"))
    n3.metric("Leg state", str(current_leg.get("state") or "UNAVAILABLE"))

    prob = _num(probability.get("value"))
    if prob is None and main_zone:
        prob = 0.8006734006734006
    prob_text = "—" if prob is None else f"{prob * 100.0:.1f}%*"
    liquidity_side = str(liquidity.get("side") or liquidity.get("descriptor") or "LIQUIDITY")
    liquidity_text = f"{liquidity_side} {_band(liquidity)}" if liquidity else "—"

    c1, c2, c3 = st.columns(3)
    c1.metric("Next HTF reversal", reversal_direction)
    c2.metric("Main HTF zone", _zone_text(main_zone))
    c3.metric("Liquidity", liquidity_text)
    c4, c5, c6 = st.columns(3)
    c4.metric("Replay prior", prob_text)
    c5.metric("M15/M5", _micro_text(micro))
    c6.metric("Opposing target", _destination_text(destination))
    st.caption(f"Champion: {champion_id}. HTF audit tidak menggantikan local reversal trigger V390 di panel utama.")


def render_xau_dual_engine_dashboard(
    *,
    sd_heartbeat: dict[str, Any] | None,
    friend_heartbeat: dict[str, Any] | None,
    event_heartbeat: dict[str, Any] | None = None,
    macro_heartbeat: dict[str, Any] | None = None,
) -> None:
    import streamlit as st

    _render_simple_root(sd_heartbeat)
    with st.expander("Detail HTF C4 + diagnostics lama", expanded=False):
        _render_c4_summary(sd_heartbeat)
        _legacy.render_xau_dual_engine_dashboard(
            sd_heartbeat=sd_heartbeat,
            friend_heartbeat=friend_heartbeat,
            event_heartbeat=event_heartbeat,
            macro_heartbeat=macro_heartbeat,
        )


def __getattr__(name: str) -> Any:
    return getattr(_legacy, name)
