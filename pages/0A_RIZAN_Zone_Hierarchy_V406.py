from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fx_scanner.xau_turso_hot_snapshot_v407 import fetch_public_hot_snapshot  # noqa: E402
from fx_scanner.xau_zone_hierarchy_v406 import evaluate_zone_hierarchy_v406  # noqa: E402


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


def band(zone: dict[str, Any]) -> str:
    if not zone:
        return "BELUM TERSEDIA"
    return f"{px(zone.get('low'))}–{px(zone.get('high'))}"


def heartbeat(snapshot: dict[str, Any], worker: str) -> dict[str, Any]:
    for raw in list(snapshot.get("heartbeats") or []):
        row = d(raw)
        if row.get("worker_name") == worker:
            return row
    return {}


def evaluation(hb: dict[str, Any]) -> dict[str, Any]:
    return d(d(hb.get("details")).get("evaluation"))


st.set_page_config(page_title="RIZAN Zone Hierarchy V406", page_icon="🧭", layout="wide")
st.title("RIZAN — Zone Hierarchy V406")
st.caption(
    "Peta sederhana: MAIN BUY → TRANSITION / DECISION → MAIN SELL → structural extension. "
    "Break decision zone mengubah internal leg; major reversal baru dianggap lebih kuat setelah opposite MAIN zone diterima."
)

try:
    snapshot = fetch_public_hot_snapshot()
except Exception as exc:
    st.error(f"Snapshot scanner belum tersedia: {type(exc).__name__}: {exc}")
    st.stop()

sd = evaluation(heartbeat(snapshot, "ctrader_demo_xau_sd_liquidity_v342"))
if not sd:
    st.warning("Data S/D XAUUSD belum tersedia. V406 tetap fail-closed sampai heartbeat valid masuk.")
    st.stop()

hier = evaluate_zone_hierarchy_v406(sd)
phase = str(hier.get("phase") or "UNAVAILABLE")
state = str(hier.get("state") or "UNAVAILABLE")

m1, m2, m3 = st.columns(3)
m1.metric("State", state.replace("_", " "))
m2.metric("Phase", phase.replace("_", " "))
m3.metric("Harga", px(hier.get("price_now")))

main_buy = d(hier.get("main_buy"))
decision = d(hier.get("decision_zone"))
main_sell = d(hier.get("main_sell"))
next_sell = d(hier.get("next_sell"))
next_buy = d(hier.get("next_buy"))

st.markdown("## Hierarki zona")
z1, z2, z3, z4 = st.columns(4)
with z1:
    st.success("**MAIN BUY**")
    st.metric("Demand utama", band(main_buy))
    if main_buy:
        st.caption(f"{main_buy.get('timeframe', '—')} / {main_buy.get('source_type', '—')}")
with z2:
    st.warning("**TRANSITION / DECISION**")
    st.metric("Decision band", band(decision))
    if decision:
        st.caption(
            f"{decision.get('timeframe', '—')} / {decision.get('source_type', '—')} • "
            f"side={decision.get('direction', '—')}"
        )
with z3:
    st.error("**MAIN SELL**")
    st.metric("Supply utama", band(main_sell))
    if main_sell:
        st.caption(f"{main_sell.get('timeframe', '—')} / {main_sell.get('source_type', '—')}")
with z4:
    st.info("**NEXT STRUCTURAL**")
    if next_sell:
        st.metric("Next sell", band(next_sell))
    elif next_buy:
        st.metric("Next buy", band(next_buy))
    else:
        st.metric("Next zone", "BELUM TERSEDIA")

transition = d(hier.get("transition_gate"))
structural = d(hier.get("structural_gate"))
path = d(hier.get("path"))

st.markdown("## Gate perubahan arah")
g1, g2, g3, g4 = st.columns(4)
g1.metric("Internal bullish >", px(transition.get("bullish_acceptance_above")))
g2.metric("Internal bearish <", px(transition.get("bearish_acceptance_below")))
g3.metric("Major bullish >", px(structural.get("bullish_major_reversal_above")))
g4.metric("Major bearish <", px(structural.get("bearish_major_reversal_below")))
st.caption(
    "Internal gate memakai acceptance M15. Major structural gate tetap opposite MAIN zone; wick/sweep sendiri tidak otomatis dihitung sebagai perubahan struktur penuh."
)

st.markdown("## Path saat ini")
primary = str(path.get("primary_if_rejected") or "WAIT_FOR_DECISION")
alternative = str(
    path.get("alternative_if_accepted_above")
    or path.get("alternative_if_accepted_below")
    or "WAIT_FOR_ACCEPTANCE"
)
p1, p2 = st.columns(2)
with p1:
    st.markdown("### Primary")
    st.write(primary.replace("_", " "))
    st.metric("Target", px(path.get("primary_target")))
with p2:
    st.markdown("### Alternative")
    st.write(alternative.replace("_", " "))
    st.metric("Target", px(path.get("alternative_target")))

if phase == "TESTING_DECISION_ZONE":
    st.warning("Harga sedang menguji decision zone. Fokus pada M15 acceptance/rejection; jangan menyamakan rebound dengan major reversal.")
elif phase == "INTERNAL_BULLISH_TRANSITION":
    st.info("Decision zone sudah diterima ke atas: internal leg bullish, tetapi MAIN SELL masih menjadi major reversal gate.")
elif phase == "BEARISH_REJECTION_FROM_DECISION":
    st.error("Decision zone ditolak: path utama kembali menuju MAIN BUY.")
elif phase == "AT_MAIN_BUY":
    st.success("Harga berada di MAIN BUY. Cari validasi reversal M15 dan refinement M5.")
elif phase == "AT_MAIN_SELL":
    st.error("Harga berada di MAIN SELL. Cari validasi rejection/reversal M15 dan refinement M5.")
else:
    st.info("Belum ada acceptance/rejection yang cukup kuat; gunakan hierarchy sebagai reference geometry.")

with st.expander("Audit V406"):
    st.write(
        {
            "contract": hier.get("contract"),
            "reason": hier.get("reason"),
            "m15_close": hier.get("m15_close"),
            "transition_gate": transition,
            "structural_gate": structural,
            "validation_status": hier.get("validation_status"),
            "execution_authority": hier.get("execution_authority"),
            "proprietary_formula_claimed": hier.get("proprietary_formula_claimed"),
        }
    )

st.caption("V406 adalah decision-support / calibration layer. LIVE auto-execution tetap OFF.")
