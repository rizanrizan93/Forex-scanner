from __future__ import annotations

from typing import Any

import streamlit as st

from fx_scanner.xau_public_hot_v362 import fetch_public_hot_snapshot
from fx_scanner.xau_scanner_summary_v373 import build_scanner_summary


def d(value: Any) -> dict[str, Any]:
    return dict(value or {})


def f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def px(value: Any) -> str:
    number = f(value)
    return "—" if number is None else f"{number:,.2f}"


def zone_label(zone: dict[str, Any]) -> str:
    if not zone:
        return "—"
    direction = str(zone.get("direction") or "").upper()
    kind = "DEMAND" if direction == "LONG" else "SUPPLY" if direction == "SHORT" else "ZONE"
    return f"{zone.get('timeframe', 'HTF')} {kind} {px(zone.get('low'))}–{px(zone.get('high'))}"


def heartbeat(snapshot: dict[str, Any], worker: str) -> dict[str, Any]:
    for raw in list(snapshot.get("heartbeats") or []):
        row = d(raw)
        if row.get("worker_name") == worker:
            return row
    return {}


def evaluation(hb: dict[str, Any]) -> dict[str, Any]:
    return d(d(hb.get("details")).get("evaluation"))


def event_risk(hb: dict[str, Any]) -> dict[str, Any]:
    return d(d(hb.get("details")).get("risk"))


def direction_label(value: Any) -> str:
    raw = str(value or "WAIT").upper()
    if raw in {"LONG", "BUY"}:
        return "BUY"
    if raw in {"SHORT", "SELL"}:
        return "SELL"
    return "WAIT"


def entry_band(entry: dict[str, Any]) -> tuple[Any, Any, str]:
    early_low = entry.get("reaction_early_low")
    early_high = entry.get("reaction_early_high")
    if early_low is not None and early_high is not None:
        return early_low, early_high, "Reaction / refined"
    return entry.get("prepared_low"), entry.get("prepared_high"), "Main prepared"


def first_target(entry: dict[str, Any]) -> Any:
    targets = list(entry.get("targets") or [])
    if not targets:
        return None
    return d(targets[0]).get("price")


st.set_page_config(page_title="Pusat Keputusan XAUUSD", page_icon="🎯", layout="wide")
st.title("Pusat Keputusan XAUUSD")
st.caption(
    "Baca dari atas ke bawah: keputusan → zona → entry/SL/TP → alasan. "
    "Detail engine, macro, dan validasi dipindahkan ke bagian riset agar halaman utama tetap sederhana."
)

try:
    snapshot = fetch_public_hot_snapshot()
except Exception as exc:
    st.error(f"Snapshot scanner belum tersedia: {type(exc).__name__}: {exc}")
    st.stop()

sd_hb = heartbeat(snapshot, "ctrader_demo_xau_sd_liquidity_v342")
friend_hb = heartbeat(snapshot, "ctrader_demo_xau_friend_entry_v343")
event_hb = heartbeat(snapshot, "ctrader_demo_xau_event_risk_v192")
macro_hb = heartbeat(snapshot, "ctrader_demo_xau_macro_attribution_v357")

sd = evaluation(sd_hb)
friend = evaluation(friend_hb)
event = event_risk(event_hb)
macro = evaluation(macro_hb)

if not sd:
    st.warning("Data struktural XAUUSD belum tersedia. Decision Center tetap fail-closed sampai snapshot valid masuk.")
    st.stop()

summary = build_scanner_summary(sd_eval=sd, friend_eval=friend, event_risk=event, macro_eval=macro)
decision = d(summary.get("decision"))
confidence = d(summary.get("decision_confidence"))
main_zone = d(summary.get("main_zone"))
reaction = d(summary.get("reaction_interceptor"))
active_zone = d(summary.get("active_reversal_candidate"))
entry = d(summary.get("entry"))
destination = d(summary.get("destination"))
primary_destination = d(destination.get("primary"))
terminal_destination = d(destination.get("terminal"))
sr = d(summary.get("support_resistance"))
macro_summary = d(summary.get("macro"))
event_summary = d(summary.get("event"))
behavior = d(sd.get("afiq_behavioral"))

state = str(decision.get("state") or "WAIT").upper()
direction = direction_label(decision.get("direction"))
label = str(decision.get("label") or direction)
action = str(decision.get("action") or "Tunggu setup yang valid.")
entry_gate = str(decision.get("entry_gate") or "WAIT")
low, high, entry_source = entry_band(entry)
sl = entry.get("reaction_invalidation")
if sl is None:
    sl = entry.get("invalidation")
tp1 = first_target(entry)
if tp1 is None:
    tp1 = d(sr.get("resistance" if direction == "BUY" else "support")).get("price")
terminal = primary_destination.get("low") if direction == "SELL" else primary_destination.get("high")
if terminal is None:
    terminal = terminal_destination.get("low") if direction == "SELL" else terminal_destination.get("high")

st.markdown("## Keputusan sekarang")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Keputusan", label)
k2.metric("Arah", direction)
k3.metric("Harga", px(summary.get("price")))
k4.metric("Entry gate", entry_gate)

if state.startswith("READY_"):
    st.success("**READY — " + action + "**")
elif state.startswith("EARLY_\"):
    st.warning("**EARLY — " + action + "**")
elif state in {"WAIT_NEWS", "NO_CHASE", "REBUILD"}:
    st.warning("**" + state.replace("_", " ") + " — " + action + "**")
else:
    st.info("**WAIT — " + action + "**")

score = f(confidence.get("evidence_score"))
band = str(confidence.get("confidence_band") or "BELUM TERSEDIA")
if score is not None:
    st.caption(f"Confidence evidence: {score:.1f}/100 • {band}. Ini kualitas evidence, bukan probabilitas menang.")

st.markdown("## Peta harga")
z1, z2, z3 = st.columns(3)
z1.metric("Zona reversal aktif", zone_label(active_zone) if active_zone else zone_label(main_zone))
z2.metric("MAIN HTF fallback", zone_label(main_zone))
z3.metric("Status reaction", str(reaction.get("state") or ("PROMOTED" if reaction.get("promoted") else "NORMAL")))

liq = list(summary.get("liquidity") or [])
if liq:
    st.caption("Liquidity terdekat • " + " | ".join(f"{row.get('side', '—')} {px(row.get('price'))}" for row in liq[:4]))

path = list(behavior.get("expected_path") or [])
if path:
    path_text: list[str] = []
    for raw in path[:4]:
        row = d(raw)
        if row.get("low") is not None and row.get("high") is not None:
            level = f"{px(row.get('low'))}–{px(row.get('high'))}"
        else:
            level = px(row.get("price"))
        path_text.append(f"{row.get('role', 'PATH')} → {level}")
    st.write("**Expected path:** " + " → ".join(path_text))

st.markdown("## Entry, SL & TP")
e1, e2, e3, e4 = st.columns(4)
e1.metric("Entry", f"{px(low)}–{px(high)}" if low is not None and high is not None else "—")
e2.metric("SL struktural", px(sl))
e3.metric("TP1", px(tp1))
e4.metric("TP terminal", px(terminal))
st.caption(f"Entry source: {entry_source} • TP mengikuti struktur/liquidity menuju opposing H1/H4.")

published_targets = list(entry.get("targets") or [])
if published_targets:
    st.write("**TP ladder:** " + " → ".join(px(d(row).get("price")) for row in published_targets[:4]))

st.markdown("## Kenapa keputusan ini")
reasons = [str(reason) for reason in list(summary.get("reasons") or []) if str(reason).strip()]
if not reasons:
    st.write("• Belum ada alasan terstruktur pada snapshot ini; scanner tetap WAIT/fail-closed.")
else:
    for reason in reasons[:4]:
        st.write("• " + reason)

next_event = d(event_summary.get("next_event"))
if next_event:
    st.caption(
        "Event berikutnya • "
        + str(next_event.get("title") or "—")
        + " • "
        + str(next_event.get("scheduled_at_wib") or next_event.get("scheduled_at") or "—")
    )

with st.expander("Riset & validasi engine"):
    st.caption(
        "Bagian ini untuk audit. V388 belum menjadi execution authority sampai kalibrasi 2025 H1/H2 lolos. "
        "Policy internal C60/C120/EC60/EC120 tidak perlu dibaca untuk keputusan harian."
    )
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Evidence score", "—" if score is None else f"{score:.1f}/100")
    r2.metric("Confidence band", band)
    r3.metric("Context", str(decision.get("context_alignment") or "UNAVAILABLE"))
    r4.metric("Execution policy", "V388 PENDING VALIDATION")

    st.write(
        {
            "H4": d(summary.get("structure")).get("H4"),
            "H1": d(summary.get("structure")).get("H1"),
            "market_regime": d(behavior.get("regime")).get("state"),
            "zone_role": d(behavior.get("active_zone_role")).get("role"),
            "acceptance_rejection": d(behavior.get("acceptance_rejection")).get("state"),
            "m30_internal": d(behavior.get("m30_internal")).get("state"),
            "response_timer": d(behavior.get("response_timer")).get("state"),
            "macro_bias": macro_summary.get("broader_bias"),
        }
    )

    components = list(confidence.get("components") or [])
    if components:
        st.dataframe(
            [
                {
                    "Komponen": row.get("name"),
                    "Bobot": row.get("weight"),
                    "Score": row.get("score"),
                    "State": row.get("state"),
                }
                for row in components
            ],
            use_container_width=True,
            hide_index=True,
        )

    friend_evidence = d(summary.get("friend_evidence"))
    st.write(
        {
            "micro_direction": friend_evidence.get("direction"),
            "micro_state": friend_evidence.get("state"),
            "micro_primary_entry": friend_evidence.get("primary_entry"),
            "micro_stop_loss": friend_evidence.get("stop_loss"),
            "micro_targets": friend_evidence.get("targets"),
            "micro_authority": friend_evidence.get("authority"),
        }
    )

st.caption(
    "LIVE: decision support/manual. DEMO: hanya execution policy yang telah lolos validasi dan gate runtime yang boleh mengirim order."
)
