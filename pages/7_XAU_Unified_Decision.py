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
from fx_scanner.xau_technical_engine_v1 import evaluate_technical
from fx_scanner.xau_unified_decision_v1 import evaluate_unified
from fx_scanner.xau_weighted_opportunity_v1 import evaluate_opportunity
from fx_scanner.usd_lead_bund_2y_v1 import fetch_bundesbank_2y, pair_with_treasury_2y
from fx_scanner.usd_lead_decision_v1 import evaluate_usd_lead
from fx_scanner.xau_yield_pressure_nowcast_v1 import evaluate_yield_pressure
from fx_scanner.ui_terminal import render_condition, render_progress


# Shared provider logic ensures identical macro interpretation in both panels.
from fx_scanner.xau_unified_inputs_v1 import macro_and_notes as _macro_and_notes


def _zone(now):
    """Never read retired DEMO V404 as evidence for the LIVE 7903 scanner.

    The LIVE source has no independently attested V404 zone contract yet.
    That is an optional unknown for research scoring, not a failed setup.
    """
    return {}, {}, False, "V404 LIVE 7903 belum tersedia; worker DEMO lama tidak dipakai"


@st.fragment(run_every="60s")
def render():
    now = datetime.now(UTC)
    st.subheader("XAUUSD — Analisis Terpadu · Skor Peluang")
    st.caption("BUY dan SELL dinilai terpisah. Data UNKNOWN tidak mendapat poin. Ini bukan prediksi probabilitas atau sinyal order Frozen V1.")
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

    opportunity = evaluate_opportunity(
        unified=unified, technical=technical, checklist=checklist
    )
    left, right, choice = st.columns(3)
    for widget, side in ((left, "BUY"), (right, "SELL")):
        score = opportunity[side]
        widget.metric(side + " · skor riset", f'{score["score"]:.1f}/100')
        widget.caption(score["state"])
    choice.metric("Fokus pemantauan", opportunity["preferred"])
    st.caption(
        "Bobot awal riset: SMC/ICT 40% · EMA/ADX/BOS 25% · USD Lead 15% · "
        "tekanan yield 10% · zona V404 10%. "
        "Ambang ini belum divalidasi out-of-sample; skor bukan peluang menang."
    )
    for side in ("BUY", "SELL"):
        scored = opportunity[side]
        with st.expander(
            f'{side} · {scored["state"]} · skor {scored["score"]:.1f}/100 · '
            f'cakupan {scored["coverage"]:.1f}%',
            expanded=(side == opportunity["preferred"]),
        ):
            for part in scored["components"]:
                st.write(
                    f'{part["name"].upper()}: {part["earned"]:.1f}/{part["weight"]:.0f} '
                    f'· PASS {part["passed"]} · FAIL {part["failed"]} '
                    f'· UNKNOWN {part["unknown"]}'
                )
            st.caption(
                "Risk LIVE: " + scored["risk"]
                + (" · konflik arah makro/yield" if scored["macro_conflict"] else "")
                + " · harga tertutup valid: " + str(scored["price_valid"])
            )
            if scored["missing"]:
                st.write("Masih perlu: " + ", ".join(scored["missing"]))
    st.divider()
    st.caption("Audit konfluensi 4/4 di bawah tetap tersedia untuk transparansi. "
               "Tidak lagi menentukan status peluang WATCH/ARMED.")
    buy, sell = unified["BUY"], unified["SELL"]
    a, b, c = st.columns(3)
    a.metric("BUY", str(buy["passed"]) + "/4 syarat")
    b.metric("SELL", str(sell["passed"]) + "/4 syarat")
    c.metric("Audit ketat 4/4", unified["decision"] + " SHADOW" if unified["decision"] != "WAIT" else "WAIT")
    st.caption("Diperiksa " + now.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%d/%m/%Y %H:%M:%S WIB")
               + " · status READY hanya berarti konfluensi riset, bukan izin transaksi.")
    for side, result in (("BUY", buy), ("SELL", sell)):
        if result["passed"] >= 3 and result["state"] != "READY_SHADOW":
            st.info(side + " mendekati konfluensi (" + str(result["passed"]) + "/4): "
                    + "; ".join(result["next_missing"][:2]))
    if any(not ok for ok in unified["sources_valid"].values()):
        missing = [k for k, ok in unified["sources_valid"].items() if not ok]
        st.warning("WAIT DATA · sumber belum terverifikasi: " + ", ".join(missing))

    buy_tab, sell_tab, usd_tab = st.tabs(["BUY · " + opportunity["BUY"]["state"], "SELL · " + opportunity["SELL"]["state"], "USD / Yield"])
    for side, tab in (("BUY", buy_tab), ("SELL", sell_tab)):
        with tab:
            row = unified[side]
            st.write("Audit ketat 4/4: " + row["state"] + " · bukan pemicu order")
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
            "equity": "Equity LIVE terverifikasi belum tersedia di sumber V404; USD100 tidak dipakai sebagai equity aktual",
            "weighted_opportunity": opportunity,
            "native_frozen_v1_signal": unified["frozen_v1_native_signal"],
            "missed_order_verdict": unified["missed_order_verdict"],
            "execution_authority": False,
        })
    st.caption("SHADOW ONLY · cBot V1, order path, bridge dan VPS tidak diubah. "
               "Alarm missed order perlu bukti intent native, guard, Journal dan history broker.")


render()
