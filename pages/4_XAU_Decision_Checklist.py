"""RIZAN XAUUSD — standalone, auto-refreshing non-executing decision checklist."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fx_scanner.dashboard_independent_feeds import macro_input
from fx_scanner.pre_news_transport import fetch_pre_news_snapshot
from fx_scanner.xau_decision_checklist_v1 import evaluate_checklist, stamp, obj
from fx_scanner.xau_decision_candle_feed_v1 import fetch_decision_candles
from fx_scanner.xau_runtime_decision_v404 import evaluate_runtime_decision_v404
from fx_scanner.xau_turso_hot_snapshot_v407 import fetch_public_hot_snapshot


def freshness(t, now, limit=150) -> bool:
    at = stamp(t)
    return at is not None and 0 <= (now-at).total_seconds() <= limit


@st.fragment(run_every="60s")
def render_checklist() -> None:
    """Read only. On each refresh, independently retrieve latest public inputs."""
    now = datetime.now(UTC)
    st.subheader("Checklist keputusan XAUUSD — refresh otomatis ±60 detik")
    st.caption(
        "Kondisi dinilai terpisah untuk BUY dan SELL. ✅ Terpenuhi; ❌ Belum terpenuhi; "
        "⏳ Data belum cukup/tidak valid. Penuh berarti SHADOW, bukan perintah entry."
    )

    sd = {}
    decision = {}
    market_fresh = False
    market_reason = ""
    try:
        snapshot = fetch_public_hot_snapshot(now=now, timeout_seconds=10.0)
        workers = [
            obj(h) for h in (snapshot.get("heartbeats") or [])
            if obj(h).get("worker_name") == "ctrader_demo_xau_sd_liquidity_v342"
        ]
        workers.sort(key=lambda h: str(h.get("observed_at") or ""), reverse=True)
        hb = workers[0] if workers else {}
        sd = obj(obj(hb.get("details")).get("evaluation"))
        # Heartbeat alone is insufficient. Original price observation MUST be fresh.
        price_at = (
            sd.get("price_observed_at")
            or obj(sd.get("market_context")).get("price_observed_at")
        )
        market_fresh = (
            hb.get("healthy") is True
            and freshness(hb.get("observed_at"), now)
            and freshness(price_at, now)
            and sd.get("execution_authority") is not True
        )
        market_reason = (
            "Turso heartbeat + original price timestamp valid"
            if market_fresh else
            "Turso heartbeat atau original timestamp harga broker tidak tersedia/segar"
        )
        if market_fresh:
            decision = evaluate_runtime_decision_v404(sd)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        market_reason = "Sumber V404 belum dapat diverifikasi: " + type(exc).__name__

    macro_result = {}
    macro_reason = ""
    try:
        payload = fetch_pre_news_snapshot(now=now, timeout_seconds=10.0)
        macro_result = obj(macro_input(payload, now=now).get("evaluation"))
        macro_reason = "V400 data makro dan timestamp diperiksa"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        macro_reason = "Makro V400 belum dapat diverifikasi: " + type(exc).__name__

    # Independent, read-only LIVE 7903 closed H1/M15/M5 collector; never use
    # stale historical public CSV for real-time ADX/DI, EMA or BOS/MSS.
    candle_feed = {}
    candle_reason = "Belum ada data candle tervalidasi"
    try:
        candle_feed = fetch_decision_candles(now=now, timeout_seconds=6.0)
        candle_reason = "Candle CLOSED H1/M15/M5 diverifikasi dari LIVE 7903"
    except (OSError, ValueError, TypeError, KeyError) as exc:
        candle_reason = "Feed candle broker belum tersedia: " + type(exc).__name__
    broker_spec = obj(sd.get("broker_symbol_spec")) if market_fresh else {}

    report = evaluate_checklist(
        decision=decision, macro_evaluation=macro_result,
        candle_feed=candle_feed, broker_spec=broker_spec,
        equity_usd=100., now=now, structure_fresh=market_fresh,
    )
    statuses = {"PASS": "✅ TERPENUHI", "FAIL": "❌ BELUM TERPENUHI",
                "UNKNOWN": "⏳ DATA BELUM VALID"}
    b, s, w = st.columns([1, 1, 2])
    b.metric("BUY", str(report["BUY"]["passed"]) + "/6 terpenuhi")
    s.metric("SELL", str(report["SELL"]["passed"]) + "/6 terpenuhi")
    w.metric("Keputusan", "WAIT" if (
        report["BUY"]["state"] != "ALL_CONDITIONS_MET_SHADOW_ONLY" and
        report["SELL"]["state"] != "ALL_CONDITIONS_MET_SHADOW_ONLY"
    ) else "SETUP LENGKAP (SHADOW)")
    st.caption("Penilaian per " + now.strftime("%d/%m/%Y %H:%M:%S UTC") + " • Akun riset USD100, leverage referensi 1:200")
    buy_tab, sell_tab = st.tabs([
        "🟢 BUY: " + str(report["BUY"]["passed"]) + "/6",
        "🔴 SELL: " + str(report["SELL"]["passed"]) + "/6",
    ])
    for side, container in (("BUY", buy_tab), ("SELL", sell_tab)):
        with container:
            data = report[side]
            st.caption(
                str(data["passed"]) + " terpenuhi • " +
                str(data["failed"]) + " belum terpenuhi • " +
                str(data["unknown"]) + " belum terverifikasi"
            )
            for criterion in data["items"]:
                with st.container(border=True):
                    st.checkbox(
                        criterion["name"],
                        value=(criterion["state"] == "PASS"), disabled=True,
                        key="checklist_v1_" + side + "_" + criterion["key"] + "_" + criterion["state"],
                    )
                    st.caption(statuses[criterion["state"]] + " — " + criterion["why"])
            if data["state"] == "ALL_CONDITIONS_MET_SHADOW_ONLY":
                st.warning(
                    "Semua syarat evaluasi telah terpenuhi, tetapi belum ada "
                    "validasi profit out-of-sample dan panel ini tidak mengirim order."
                )
            else:
                st.info(
                    "WAIT: entry belum memenuhi seluruh checklist. "
                    "Jangan memaksa sinyal atau menaikkan lot."
                )

    with st.expander("Audit sumber dan keterbatasan indikator"):
        st.write({
            "status_market": market_reason,
            "status_macro": macro_reason,
            "status_candle_broker": candle_reason,
            "macro_v400_quality_state": obj(macro_result.get("attribution_quality")).get("quality_state"),
            "v404_state": decision.get("state", "UNAVAILABLE"),
            "v404_direction": decision.get("direction", "WAIT"),
            "candle_series_contract": candle_feed.get("contract", "UNAVAILABLE"),
            "symbol_contract": broker_spec.get("contract", "UNAVAILABLE"),
            "last_checked_utc": report["as_of_utc"],
            "order_enabled": False,
        })
        st.caption(
            "ADX14 dan EMA200 H1 memerlukan rangkaian candle tertutup yang memadai. "
            "Data dari feed cTrader read-only dicek setiap ±60 detik; publisher GitHub "
            "berjadwal sekitar 5 menit. Jika feed belum jalan/stale status UNKNOWN. "
            "Minimum volume, biaya serta estimasi margin broker belum diberikan, "
            "jadi risiko tidak akan dicentang dari asumsi."
        )

    st.caption(
        "RIZAN XAU DECISION CHECKLIST V1 • SHADOW ONLY • Tidak mengubah Frozen V1, "
        "tidak mengirim order, tidak menyentuh bridge atau VPS."
    )


st.title("RIZAN — Checklist Entry XAUUSD")
render_checklist()
