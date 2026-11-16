"""One read-only XAU decision panel, with independent source/freshness audit."""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from fx_scanner.dashboard_independent_feeds import macro_input
from fx_scanner.pre_news_transport import fetch_pre_news_snapshot
from fx_scanner.xau_decision_candle_feed_v1 import fetch_decision_candles
from fx_scanner.xau_decision_checklist_v1 import evaluate_checklist, obj, stamp
from fx_scanner.xau_runtime_decision_v404 import evaluate_runtime_decision_v404
from fx_scanner.xau_turso_hot_snapshot_v407 import fetch_public_hot_snapshot
from fx_scanner.xau_technical_engine_v1 import evaluate_technical
from fx_scanner.xau_unified_decision_v1 import evaluate_unified
from fx_scanner.usd_lead_bund_2y_v1 import fetch_bundesbank_2y, pair_with_treasury_2y
from fx_scanner.usd_lead_decision_v1 import evaluate_usd_lead
from fx_scanner.xau_yield_pressure_nowcast_v1 import evaluate_yield_pressure
from fx_scanner.ui_terminal import render_condition, render_progress


def _fresh(value, now, seconds=150):
    at = stamp(value)
    return at is not None and 0 <= (now-at).total_seconds() <= seconds


@st.cache_data(ttl=120, show_spinner=False)
def _secondary_quotes(symbol):
    # Secondary proxy only. The original quote timestamp is never refreshed here.
    from fx_scanner.xau_intraday_macro_v398 import (
        fetch_yahoo_chart, evaluate_dxy_pressure, evaluate_fed_funds_futures_pressure,
    )
    urls = {
        "ZQ": "https://query1.finance.yahoo.com/v8/finance/chart/ZQ=F",
        "DXY": "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB",
    }
    values = fetch_yahoo_chart(base_url=urls[symbol], allowed_host="query1.finance.yahoo.com",
                               timeout_seconds=5., interval="5m", range_name="1d")
    return list(values)


@st.cache_data(ttl=1800, show_spinner=False)
def _bund():
    return fetch_bundesbank_2y(now=datetime.now(UTC), timeout_seconds=7.)


def _macro_and_notes(now):
    notes = {}
    try:
        evaluation = obj(macro_input(
            fetch_pre_news_snapshot(now=now, timeout_seconds=7.), now=now
        ).get("evaluation"))
        notes["macro"] = "V400 snapshot diperiksa; nilai yield resmi harian bukan nowcast"
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        evaluation = {}
        notes["macro"] = "WAIT DATA: " + type(exc).__name__
    for key, symbol in (("fed_funds_futures", "ZQ"), ("dxy_intraday", "DXY")):
        current = obj(evaluation.get(key))
        if current.get("available") is True and _fresh(current.get("current_at"), now, 900):
            continue
        try:
            from fx_scanner.xau_intraday_macro_v398 import (
                evaluate_dxy_pressure, evaluate_fed_funds_futures_pressure,
            )
            points = _secondary_quotes(symbol)
            fn = evaluate_dxy_pressure if symbol == "DXY" else evaluate_fed_funds_futures_pressure
            evaluation[key] = fn(points, now=now, max_age_seconds=900)
            notes[key] = "Yahoo Finance proxy, timestamp quote asli"
        except Exception as exc:
            # Missing optional transport must never blank the primary dashboard.
            notes[key] = "UNKNOWN: " + type(exc).__name__
    try:
        spread = pair_with_treasury_2y(
            _bund(), obj(obj(evaluation.get("components")).get("US2Y")), now=now
        )
        notes["spread"] = "Treasury + Bundesbank tanggal cocok" if spread else "UNKNOWN: tanggal tidak cocok"
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        spread = None
        notes["spread"] = "UNKNOWN: " + type(exc).__name__
    return evaluation, spread, notes


def _zone(now):
    """Only corroborated original price observations can contribute V404/risk."""
    try:
        snapshot = fetch_public_hot_snapshot(now=now, timeout_seconds=8.)
        workers = [
            obj(row) for row in (snapshot.get("heartbeats") or [])
            if obj(row).get("worker_name") == "ctrader_demo_xau_sd_liquidity_v342"
        ]
        workers.sort(key=lambda v: str(v.get("observed_at") or ""), reverse=True)
        hb = workers[0] if workers else {}
        sd = obj(obj(hb.get("details")).get("evaluation"))
        original_at = sd.get("price_observed_at") or obj(sd.get("market_context")).get("price_observed_at")
        verified = (hb.get("healthy") is True and _fresh(hb.get("observed_at"), now)
                    and _fresh(original_at, now) and sd.get("execution_authority") is not True)
        if verified:
            return evaluate_runtime_decision_v404(sd), obj(sd.get("broker_symbol_spec")), True, "V404 FRESH"
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
        return {}, {}, False, "V404 UNKNOWN: " + type(exc).__name__
    return {}, {}, False, "V404 UNKNOWN: heartbeat atau harga broker kedaluwarsa"


@st.fragment(run_every="60s")
def render():
    now = datetime.now(UTC)
    st.subheader("XAUUSD — Checklist + Teknikal + USD Lead")
    st.caption("Satu keputusan riset dengan checklist terpisah per sumber; tidak mengirim order atau mengubah Frozen V1.")
    notes = {}
    # Independent read-only feeds are fetched concurrently, then evaluated
    # against ONE now timestamp; no papering over stale originals.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            "candles": pool.submit(fetch_decision_candles, now=now, timeout_seconds=6.),
            "macro": pool.submit(_macro_and_notes, now),
            "zone": pool.submit(_zone, now),
        }
        try:
            candles = futures["candles"].result()
            notes["candles"] = "CLOSED LIVE 7903; " + str(candles.get("as_of"))
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
            candles = {}
            notes["candles"] = "WAIT DATA: " + type(exc).__name__
        try:
            evaluation, spread, macro_notes = futures["macro"].result()
            notes.update(macro_notes)
        except Exception as exc:
            evaluation, spread = {}, None
            notes["macro"] = "WAIT DATA: " + type(exc).__name__
        try:
            zone, spec, zone_fresh, zone_note = futures["zone"].result()
            notes["zone"] = zone_note
        except Exception as exc:
            zone, spec, zone_fresh = {}, {}, False
            notes["zone"] = "UNKNOWN: " + type(exc).__name__

    technical = evaluate_technical(candles, now=now)
    checklist = evaluate_checklist(
        decision=zone, macro_evaluation=evaluation,
        candle_feed=candles, broker_spec=spec, equity_usd=100.,
        structure_fresh=zone_fresh, now=now,
    )
    yield_pressure = evaluate_yield_pressure(
        evaluation, now=now, fed_funds=evaluation.get("fed_funds_futures"),
    )
    usd = evaluate_usd_lead(
        evaluation, now=now, spread=spread, xau_checklist=checklist,
        yield_nowcast=yield_pressure,
    )
    unified = evaluate_unified(
        technical=technical, checklist=checklist, usd=usd,
        yield_pressure=yield_pressure, now=now,
    )

    buy, sell = unified["BUY"], unified["SELL"]
    a, b, c = st.columns(3)
    a.metric("BUY", str(buy["passed"]) + "/4 syarat")
    b.metric("SELL", str(sell["passed"]) + "/4 syarat")
    c.metric("Keputusan", unified["decision"] + " SHADOW" if unified["decision"] != "WAIT" else "WAIT")
    st.caption("Diperiksa " + now.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%d/%m/%Y %H:%M:%S WIB")
               + " · status READY hanya berarti konfluensi riset, bukan izin transaksi.")
    for side, result in (("BUY", buy), ("SELL", sell)):
        if result["passed"] >= 3 and result["state"] != "READY_SHADOW":
            st.info(side + " mendekati konfluensi (" + str(result["passed"]) + "/4): "
                    + "; ".join(result["next_missing"][:2]))
    if any(not ok for ok in unified["sources_valid"].values()):
        missing = [k for k, ok in unified["sources_valid"].items() if not ok]
        st.warning("WAIT DATA · sumber belum terverifikasi: " + ", ".join(missing))

    buy_tab, sell_tab, usd_tab = st.tabs(["BUY · " + buy["state"], "SELL · " + sell["state"], "USD / Yield"])
    for side, tab in (("BUY", buy_tab), ("SELL", sell_tab)):
        with tab:
            row = unified[side]
            st.write("Konfluensi: " + row["state"])
            render_progress(st, passed=row["passed"],
                            failed=row["total"]-row["passed"]-row["unknown"],
                            unknown=row["unknown"], total=row["total"])
            for g in row["gates"]:
                render_condition(st, title=g["name"], state=g["state"], detail=g["detail"])
            p = row.get("technical_plan")
            if p:
                st.write("Setup teknikal: close %.2f · SL struktural %.2f · target %.2f · RR bruto %.2fR"
                         % (p["reference_close"], p["invalidation"],
                            p["target_liquidity"], p["rr_before_costs"]))
                st.caption("FVG %.2f–%.2f · berlaku sampai %s; spread/slippage belum dihitung."
                           % (*p["fvg"], p["valid_until"]))
            with st.expander("Rincian seluruh syarat Teknikal SMC/ICT dan Checklist"):
                st.markdown("**Teknikal · 6 syarat**")
                for item in technical[side]["items"]:
                    render_condition(st, title=item["name"], state=item["state"], detail=item["why"])
                st.markdown("**Checklist keputusan · 6 syarat**")
                for item in checklist[side]["items"]:
                    render_condition(st, title=item["name"], state=item["state"], detail=item["why"])
    with usd_tab:
        st.write("USD Lead: " + usd["usd_direction"] + " · yield pressure: "
                 + yield_pressure["yield_direction"] + " (" + yield_pressure["state"] + ")")
        st.caption("Proxy ZN/ZQ hanya hipotesis 15–60 menit; US2Y, real yield dan spread harian adalah konteks.")
        for side, key in (("USD NAIK → evaluasi SELL XAU", "usd_up"),
                          ("USD TURUN → evaluasi BUY XAU", "usd_down")):
            with st.expander(side):
                for item in usd[key]["rows"]:
                    render_condition(st, title=item["label"], state=item["state"],
                                     detail=item["detail"], meta=item["category"])
    with st.expander("Audit sumber dan batas interpretasi"):
        st.json({
            "feed": notes,
            "source_validity": unified["sources_valid"],
            "technical_errors": technical["errors"],
            "macro_quality": obj(evaluation.get("attribution_quality")).get("quality_state"),
            "candle_original_as_of": candles.get("as_of"),
            "equity": "Gunakan equity LIVE terverifikasi; USD100 bukan nilai akun sekarang",
            "native_frozen_v1_signal": unified["frozen_v1_native_signal"],
            "missed_order_verdict": unified["missed_order_verdict"],
            "execution_authority": False,
        })
    st.caption("SHADOW ONLY · cBot V1, order path, bridge dan VPS tidak diubah. "
               "Alarm missed order perlu bukti intent native, guard, Journal dan history broker.")


render()
