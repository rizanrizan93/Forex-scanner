from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_scanner.xau_public_hot_v362 import fetch_public_hot_snapshot  # noqa: E402
from fx_scanner.xau_runtime_decision_v404 import evaluate_runtime_decision_v404  # noqa: E402
from fx_scanner.xau_simple_reversal_engine_v390 import evaluate_simple_reversal  # noqa: E402
from fx_scanner.xau_whalezone_reconstruction_v405 import (  # noqa: E402
    evaluate_whalezone_reconstruction_v405,
)


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


def direction_badge(direction: str) -> str:
    return {"LONG": "🟢 LONG", "SHORT": "🔴 SHORT"}.get(direction, "⚪ WAIT")


def render_tier(zone: dict[str, Any], *, side: str) -> None:
    label = str(zone.get("label") or side)
    low = px(zone.get("low"))
    high = px(zone.get("high"))
    readiness = readiness_label(zone.get("readiness"))
    tf = str(zone.get("timeframe") or "—")
    source = str(zone.get("source_type") or "—")
    distance = f(zone.get("distance_atr"))
    distance_text = "—" if distance is None else f"{distance:.2f} ATR"
    if side == "SELL":
        st.error(f"**🔴 {label}**  •  {low}–{high}")
    else:
        st.info(f"**⚪ {label}**  •  {low}–{high}")
    st.caption(
        f"{readiness} • {tf}/{source} • distance {distance_text} • "
        f"lifecycle={zone.get('lifecycle_state', '—')}"
    )
    liquidity = list(zone.get("liquidity") or [])
    if liquidity:
        st.caption(
            "Liquidity: "
            + " | ".join(
                f"{row.get('side', '—')} {px(row.get('price'))}" for row in liquidity[:3]
            )
        )


st.set_page_config(page_title="RIZAN XAU Decision", page_icon="🎯", layout="wide")
st.title("RIZAN — Pusat Keputusan XAUUSD")
st.caption(
    "V404 menggabungkan reversal lokal V390 dengan challenger/liquidity V403 menjadi satu keputusan fail-closed. "
    "V405 menambahkan peta tiered BUY/SELL berbasis struktur kausal; bukan klaim formula proprietary."
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
decision = evaluate_runtime_decision_v404(sd)
whale = evaluate_whalezone_reconstruction_v405(sd)

v404_state = str(decision.get("state") or "UNAVAILABLE")
v404_direction = str(decision.get("direction") or "WAIT")
v404_grade = str(decision.get("grade") or "NONE")

st.markdown("## Keputusan terpadu V404")
a, b, c, dcol = st.columns(4)
a.metric("State", v404_state.replace("_", " "))
b.metric("Arah", direction_badge(v404_direction))
c.metric("Grade", v404_grade)
dcol.metric("Harga", px(decision.get("price_now")))

if v404_state == "READY_CONFIRMED":
    st.success("**SETUP A — CONFIRMED** • V390 ready dan V403 mengonfirmasi arah yang sama.")
elif v404_state == "READY_EARLY":
    st.warning("**SETUP B — EARLY / TAKE-RISK CANDIDATE** • arah selaras dan liquidity gate terpenuhi, tetapi masih mode riset/shadow.")
elif v404_state == "WAIT_CONFLICT":
    st.error("**WAIT — KONFLIK ENGINE** • V390 dan V403 tidak searah. Tidak ada entry yang dipaksakan.")
elif v404_state == "BLOCKED_EVENT":
    st.error("**EVENT BLOCK** • setup ditahan karena event risk.")
elif v404_state in {"INVALIDATED", "WAIT_V403_UNAVAILABLE"}:
    st.error("**FAIL-CLOSED** • input challenger invalid/tidak tersedia.")
elif v404_state.startswith("WATCH"):
    st.info("**WATCH** • geometri/arah ada, tetapi kualitas consensus belum cukup untuk READY.")
else:
    st.info("**WAIT** • belum ada consensus entry yang memenuhi aturan V404.")

st.caption(
    f"Reason: {decision.get('reason', '—')} • V390={decision.get('v390_state', '—')} "
    f"({decision.get('v390_direction', 'WAIT')}) • V403={decision.get('v403_state', '—')} "
    f"({decision.get('v403_direction', 'WAIT')})"
)

entry_band = d(decision.get("entry_band"))
targets = list(decision.get("targets") or [])
g1, g2, g3, g4 = st.columns(4)
g1.metric("Entry band", f"{px(entry_band.get('low'))}–{px(entry_band.get('high'))}")
g2.metric("Invalidation", px(decision.get("structural_invalidation")))
g3.metric("Validation level", px(decision.get("validation_level")))
g4.metric("Target 1", px(targets[0] if targets else None))

if decision.get("rr_first_target") is not None:
    st.caption(f"RR target pertama (V403): {float(decision.get('rr_first_target')):.2f}R")

if decision.get("research_candidate"):
    st.warning(
        "V404 menandai setup ini sebagai kandidat kalibrasi A/B. Engine keputusan tetap tidak mempunyai otoritas broker langsung; LIVE selalu OFF."
    )
else:
    st.caption("Execution decision layer: SHADOW • LIVE auto-order OFF.")

st.markdown("---")
st.markdown("## V405 — RIZAN Tiered Reaction Map")
st.caption(
    "Rekonstruksi perilaku dari pola visual yang dibagikan: zona reaksi disusun bertingkat dari yang terdekat ke struktur berikutnya. "
    "H4/H1 = struktur, M15 = validasi, M5 = refinement. Exact formula indikator pihak lain tidak diklaim."
)

w1, w2, w3, w4 = st.columns(4)
w1.metric("V405 State", str(whale.get("state") or "UNAVAILABLE").replace("_", " "))
w2.metric("Focus", direction_badge(str(whale.get("direction") or "WAIT")))
w3.metric("BUY side", str(whale.get("buy_state") or "UNAVAILABLE").replace("_", " "))
w4.metric("SELL side", str(whale.get("sell_state") or "UNAVAILABLE").replace("_", " "))
st.caption(f"Reason: {whale.get('reason', '—')} • ATR reference: {px(whale.get('atr_reference'))}")

buy_zones = [d(row) for row in list(whale.get("buy_zones") or [])]
sell_zones = [d(row) for row in list(whale.get("sell_zones") or [])]
left, right = st.columns(2)
with left:
    st.markdown("### ⚪ BUY zones")
    if buy_zones:
        for row in buy_zones:
            render_tier(row, side="BUY")
    else:
        st.caption("Tidak ada BUY zone valid pada snapshot saat ini.")
with right:
    st.markdown("### 🩷 SELL zones")
    if sell_zones:
        for row in sell_zones:
            render_tier(row, side="SELL")
    else:
        st.caption("Tidak ada SELL zone valid pada snapshot saat ini.")

whale_range = d(whale.get("range"))
if whale_range.get("state") == "LOCAL_RANGE":
    st.markdown("### Struktur sideways / local range")
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Floor", px(whale_range.get("floor")))
    q2.metric("Mid", px(whale_range.get("mid")))
    q3.metric("Ceiling", px(whale_range.get("ceiling")))
    q4.metric("Posisi harga", str(whale_range.get("price_location") or "—").replace("_", " "))
    st.caption(
        "Tier 1 adalah reaction edge terdekat. Jika M15 menerima harga secara solid di luar edge, fokus bergeser ke tier berikutnya; "
        "wick/sweep saja tidak otomatis membatalkan zona pada hipotesis V405."
    )

st.markdown("---")
st.markdown("## Peta reversal V390")
state = str(plan.get("state") or "UNAVAILABLE")
direction = str(plan.get("direction") or "WAIT")
long_zone = d(plan.get("long_zone"))
short_zone = d(plan.get("short_zone"))
selected = d(plan.get("selected_zone"))
entry = d(plan.get("entry"))
local_range = d(plan.get("range"))
deep = d(plan.get("deep_htf_fallback"))

v1, v2, v3 = st.columns(3)
v1.metric("V390 State", state.replace("_", " "))
v2.metric("V390 Arah", direction)
v3.metric("Harga", px(plan.get("price_now")))

st.write(str(plan.get("action") or ""))

st.markdown("### Zona reversal terdekat")
z1, z2 = st.columns(2)
with z1:
    st.markdown("#### 🟢 Demand → LONG")
    st.metric("Zona LONG", zone_text(long_zone, "DEMAND"))
    st.metric("Status", readiness_label(plan.get("long_readiness")))
    if long_zone:
        st.caption(
            "Distance=" + f"{float(long_zone.get('distance_atr') or 0):.2f} ATR"
            + " • source=" + str(long_zone.get("source_type") or "—")
            + " • lifecycle=" + str(long_zone.get("lifecycle_state") or "—")
        )

with z2:
    st.markdown("#### 🔴 Supply → SHORT")
    st.metric("Zona SHORT", zone_text(short_zone, "SUPPLY"))
    st.metric("Status", readiness_label(plan.get("short_readiness")))
    if short_zone:
        st.caption(
            "Distance=" + f"{float(short_zone.get('distance_atr') or 0):.2f} ATR"
            + " • source=" + str(short_zone.get("source_type") or "—")
            + " • lifecycle=" + str(short_zone.get("lifecycle_state") or "—")
        )

if local_range:
    st.markdown("### Local range")
    r1, r2, r3 = st.columns(3)
    r1.metric("Floor / demand", px(local_range.get("floor")))
    r2.metric("Mid", px(local_range.get("mid")))
    r3.metric("Ceiling / supply", px(local_range.get("ceiling")))
    st.caption(
        "Dekat floor → cari LONG reversal; dekat ceiling → cari SHORT reversal; di tengah → WAIT. "
        "Breakout yang bertahan membatalkan range dan engine memetakan zona berikutnya."
    )

st.markdown("### Entry plan V390")
if selected:
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Arah", direction)
    e2.metric("Entry zone", f"{px(entry.get('low'))}–{px(entry.get('high'))}")
    e3.metric("Invalidation", px(entry.get("invalidation")))
    e4.metric("TP1 opposing local zone", px(entry.get("tp1_opposite_local_zone")))
    st.caption("Entry adalah zone-based reference. Jangan chase jika harga sudah meninggalkan band.")
else:
    st.info("Belum ada entry aktif V390; demand dan supply lokal tetap ditampilkan untuk reference geometry.")

st.markdown("### Liquidity di zona")
for side, zone in (("LONG", long_zone), ("SHORT", short_zone)):
    liquidity = list(zone.get("liquidity") or []) if zone else []
    if liquidity:
        st.write(
            f"**{side}:** "
            + " | ".join(f"{row.get('side', '—')} {px(row.get('price'))}" for row in liquidity[:4])
        )

with st.expander("Audit V404/V405 + struktur HTF"):
    st.write(
        {
            "v404_contract": decision.get("contract"),
            "v404_validation_status": decision.get("validation_status"),
            "v404_research_gates": decision.get("required_research_gates"),
            "v403_reason": decision.get("v403_reason"),
            "v405_contract": whale.get("contract"),
            "v405_validation_status": whale.get("validation_status"),
            "v405_reconstruction_basis": whale.get("reconstruction_basis"),
            "v405_proprietary_formula_claimed": whale.get("proprietary_formula_claimed"),
            "v405_confirmation_model": whale.get("confirmation_model"),
            "deep_htf_zone": deep,
            "deep_htf_is_entry_trigger": bool(plan.get("deep_htf_is_entry_trigger")),
            "candidate_counts": plan.get("candidate_counts"),
            "atr_reference": plan.get("atr_reference"),
            "v390_contract": plan.get("contract"),
            "v390_validation_status": plan.get("validation_status"),
        }
    )

st.caption(
    "V404/V405 adalah decision-support dan reconstruction research. LIVE auto-execution = OFF. "
    "DEMO forward calibration tetap harus melalui jalur eksekusi DEMO terpisah dengan broker-side SL/TP dan audit order."
)
