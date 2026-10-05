from __future__ import annotations

from typing import Any

import streamlit as st

from fx_scanner.xau_public_hot_v362 import fetch_public_hot_snapshot
from fx_scanner.xau_simple_reversal_engine_v390 import evaluate_simple_reversal


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


def heartbeat(snapshot: dict[str, Any], worker: str) -> dict[str, Any]:
    for raw in list(snapshot.get("heartbeats") or []):
        row = d(raw)
        if row.get("worker_name") == worker:
            return row
    return {}


def evaluation(hb: dict[str, Any]) -> dict[str, Any]:
    return d(d(hb.get("details")).get("evaluation"))


def zone_text(zone: dict[str, Any], side: str) -> str:
    if not zone:
        return "BELUM TERSEDIA"
    return f"{side} {px(zone.get('low'))}–{px(zone.get('high'))}"


def readiness_label(value: Any) -> str:
    labels = {
        "READY_EARLY": "READY",
        "WATCH_REACTION": "WATCH REACTION",
        "PREPARE": "PREPARE",
        "WAIT": "WAIT",
        "NONE": "NONE",
    }
    raw = str(value or "NONE").upper()
    return labels.get(raw, raw.replace("_", " "))


st.set_page_config(page_title="RIZAN XAU Reversal", page_icon="🎯", layout="wide")
st.title("RIZAN — XAUUSD Reversal Decision")
st.caption(
    "Tujuan halaman ini hanya satu: tunjukkan zona reversal lokal terdekat dan arah reversal-nya. "
    "H4/H1 yang jauh tetap disimpan sebagai struktur/fallback, tetapi tidak lagi memaksa user menunggu harga ke sana."
)

try:
    snapshot = fetch_public_hot_snapshot()
except Exception as exc:
    st.error(f"Snapshot scanner belum tersedia: {type(exc).__name__}: {exc}")
    st.stop()

sd_hb = heartbeat(snapshot, "ctrader_demo_xau_sd_liquidity_v342")
sd = evaluation(sd_hb)
if not sd:
    st.warning("Data S/D XAUUSD belum tersedia. Scanner tetap fail-closed sampai heartbeat valid masuk.")
    st.stop()

plan = evaluate_simple_reversal(sd)
state = str(plan.get("state") or "UNAVAILABLE")
direction = str(plan.get("direction") or "WAIT")
long_zone = d(plan.get("long_zone"))
short_zone = d(plan.get("short_zone"))
selected = d(plan.get("selected_zone"))
entry = d(plan.get("entry"))
local_range = d(plan.get("range"))
deep = d(plan.get("deep_htf_fallback"))

st.markdown("## Keputusan sekarang")
a, b, c = st.columns(3)
a.metric("State", state.replace("_", " "))
b.metric("Arah", direction)
c.metric("Harga", px(plan.get("price_now")))

if state == "READY_LONG":
    st.success("**LONG REVERSAL READY** — harga berada di demand lokal dengan evidence reversal awal.")
elif state == "READY_SHORT":
    st.error("**SHORT REVERSAL READY** — harga berada di supply lokal dengan evidence reversal awal.")
elif state in {"WATCH_LONG", "PREPARE_LONG"}:
    st.warning("**LONG WATCH** — fokus ke demand lokal; jangan menunggu H4 supply jauh.")
elif state in {"WATCH_SHORT", "PREPARE_SHORT"}:
    st.warning("**SHORT WATCH** — fokus ke supply lokal; jangan menunggu H4 supply/demand jauh.")
elif state == "RANGE_WAIT":
    st.info("**RANGE / WAIT** — harga berada di antara demand lokal dan supply lokal. Entry di tengah range dihindari.")
else:
    st.info("Belum ada trigger lokal yang cukup kuat. Zona terdekat tetap ditampilkan supaya scanner tidak kosong.")

st.write(str(plan.get("action") or ""))

st.markdown("## Zona reversal terdekat")
z1, z2 = st.columns(2)
with z1:
    st.markdown("### 🟢 Demand → LONG")
    st.metric("Zona LONG", zone_text(long_zone, "DEMAND"))
    st.metric("Status", readiness_label(plan.get("long_readiness")))
    if long_zone:
        st.caption(
            "Distance=" + f"{float(long_zone.get('distance_atr') or 0):.2f} ATR"
            + " • source=" + str(long_zone.get("source_type") or "—")
            + " • lifecycle=" + str(long_zone.get("lifecycle_state") or "—")
        )

with z2:
    st.markdown("### 🔴 Supply → SHORT")
    st.metric("Zona SHORT", zone_text(short_zone, "SUPPLY"))
    st.metric("Status", readiness_label(plan.get("short_readiness")))
    if short_zone:
        st.caption(
            "Distance=" + f"{float(short_zone.get('distance_atr') or 0):.2f} ATR"
            + " • source=" + str(short_zone.get("source_type") or "—")
            + " • lifecycle=" + str(short_zone.get("lifecycle_state") or "—")
        )

if local_range:
    st.markdown("## Local range")
    r1, r2, r3 = st.columns(3)
    r1.metric("Floor / demand", px(local_range.get("floor")))
    r2.metric("Mid", px(local_range.get("mid")))
    r3.metric("Ceiling / supply", px(local_range.get("ceiling")))
    st.caption(
        "Aturan baca: dekat floor → cari LONG reversal; dekat ceiling → cari SHORT reversal; "
        "di tengah → WAIT. Breakout yang bertahan membatalkan range dan engine akan memetakan zona berikutnya."
    )

st.markdown("## Entry plan aktif")
if selected:
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Arah", direction)
    e2.metric("Entry zone", f"{px(entry.get('low'))}–{px(entry.get('high'))}")
    e3.metric("Invalidation", px(entry.get("invalidation")))
    e4.metric("TP1 opposing local zone", px(entry.get("tp1_opposite_local_zone")))
    st.caption("Entry adalah zone-based reference. Jangan chase jika harga sudah meninggalkan band.")
else:
    st.info("Belum ada entry aktif karena harga belum berada/dekat salah satu reversal zone. Ini bukan blank: dua zona keputusan tetap ada di atas.")

st.markdown("## Liquidity di zona")
for side, zone in (("LONG", long_zone), ("SHORT", short_zone)):
    liquidity = list(zone.get("liquidity") or []) if zone else []
    if liquidity:
        st.write(
            f"**{side}:** "
            + " | ".join(f"{row.get('side', '—')} {px(row.get('price'))}" for row in liquidity[:4])
        )

with st.expander("Struktur HTF / audit"):
    st.caption(
        "Bagian ini bukan trigger entry utama. H4/H1 jauh dipakai sebagai context, fallback, dan destination conditional."
    )
    st.write(
        {
            "deep_htf_zone": deep,
            "deep_htf_is_entry_trigger": bool(plan.get("deep_htf_is_entry_trigger")),
            "candidate_counts": plan.get("candidate_counts"),
            "atr_reference": plan.get("atr_reference"),
            "contract": plan.get("contract"),
            "validation_status": plan.get("validation_status"),
        }
    )

st.caption(
    "V390 saat ini decision-support/shadow: LIVE tidak diberi auto-execution authority dan DEMO auto-order belum dipromosikan sebelum replay validation."
)
