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


def row_payload(zone: dict[str, Any]) -> dict[str, Any]:
    acceptance = d(zone.get("m15_acceptance"))
    return {
        "Tier": zone.get("tier"),
        "Zona": zone.get("label"),
        "Low": f(zone.get("low")),
        "High": f(zone.get("high")),
        "TF": zone.get("timeframe"),
        "State": zone.get("state"),
        "Lifecycle": zone.get("lifecycle_state"),
        "Distance ATR": f(zone.get("distance_atr")),
        "Score": f(zone.get("structural_score")),
        "M15 solid close": acceptance.get("status"),
        "Liquidity": len(list(zone.get("liquidity") or [])),
    }


st.set_page_config(page_title="RIZAN Whalezone V405", page_icon="🐋", layout="wide")
st.title("RIZAN — Whalezone Reconstruction V405")
st.caption(
    "Rekonstruksi perilaku box BUY/SELL bertingkat dari struktur H4/H1 + local S/R + liquidity. "
    "Ini bukan klaim formula proprietary dan bukan pembacaan whale order-flow langsung."
)

try:
    snapshot = fetch_public_hot_snapshot()
except Exception as exc:
    st.error(f"Snapshot scanner belum tersedia: {type(exc).__name__}: {exc}")
    st.stop()

sd_hb = heartbeat(snapshot, "ctrader_demo_xau_sd_liquidity_v342")
sd = evaluation(sd_hb)
if not sd:
    st.warning("Data S/D XAUUSD belum tersedia; V405 fail-closed.")
    st.stop()

mapping = evaluate_whalezone_reconstruction_v405(sd)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Harga XAUUSD", px(mapping.get("price_now")))
m2.metric("Struktur", str(mapping.get("state") or "UNAVAILABLE").replace("_", " "))
m3.metric("Active side", str(mapping.get("active_side") or "WAIT"))
m4.metric("ATR reference", px(mapping.get("atr_reference")))

active = d(mapping.get("active_zone"))
if active:
    side = str(active.get("side") or "WAIT")
    text = f"{active.get('label', side)} • {px(active.get('low'))}–{px(active.get('high'))}"
    if side == "BUY":
        st.success(f"🐋 ACTIVE BUY BOX — {text}")
    elif side == "SELL":
        st.error(f"🐋 ACTIVE SELL BOX — {text}")
else:
    st.info("Harga belum berada di box aktif; gunakan tier terdekat sebagai peta reaksi, bukan market-order trigger.")

st.markdown("## 🩶 BUY boxes")
buys = [row_payload(d(row)) for row in list(mapping.get("buy_zones") or [])]
if buys:
    st.dataframe(buys, use_container_width=True, hide_index=True)
else:
    st.info("Belum ada BUY box valid pada snapshot saat ini.")

st.markdown("## 🩷 SELL boxes")
sells = [row_payload(d(row)) for row in list(mapping.get("sell_zones") or [])]
if sells:
    st.dataframe(sells, use_container_width=True, hide_index=True)
else:
    st.info("Belum ada SELL box valid pada snapshot saat ini.")

st.markdown("## Cara membaca")
st.write(
    "SELL 1/BUY 1 adalah structural reaction box terdekat. Tier berikutnya adalah zona struktur berikutnya, "
    "bukan TP/entry otomatis. Wick/sweep tidak otomatis membatalkan box; bila upstream menyediakan bukti "
    "M15 solid-close acceptance, statusnya ditampilkan pada kolom M15 solid close."
)

with st.expander("Audit / basis rekonstruksi"):
    st.write(
        {
            "contract": mapping.get("contract"),
            "mode": mapping.get("mode"),
            "candidate_count": mapping.get("candidate_count"),
            "mapping_basis": mapping.get("mapping_basis"),
            "validation_status": mapping.get("validation_status"),
            "execution_authority": mapping.get("execution_authority"),
            "demo_auto_execution": mapping.get("demo_auto_execution"),
            "live_execution_enabled": mapping.get("live_execution_enabled"),
            "note": mapping.get("reconstruction_note"),
        }
    )

st.caption(
    "V405 = research/mapping. DEMO/LIVE execution authority = OFF. "
    "Forward calibration harus dilakukan oleh sampler DEMO terpisah dengan SL/TP struktural dan idempotency."
)
