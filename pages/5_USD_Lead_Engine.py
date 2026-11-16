"""ForexScanner XAU/USD Lead research page — read-only, no trading authority."""
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
from fx_scanner.xau_decision_checklist_v1 import evaluate_checklist, obj, stamp
from fx_scanner.xau_decision_candle_feed_v1 import fetch_decision_candles
from fx_scanner.xau_runtime_decision_v404 import evaluate_runtime_decision_v404
from fx_scanner.xau_turso_hot_snapshot_v407 import fetch_public_hot_snapshot
from fx_scanner.usd_lead_bund_2y_v1 import fetch_bundesbank_2y, pair_with_treasury_2y
from fx_scanner.usd_lead_decision_v1 import evaluate_usd_lead
from fx_scanner.xau_yield_pressure_nowcast_v1 import evaluate_yield_pressure
def _load_intraday_market_helpers():
    """Lazy import: dashboard must render even if optional Yahoo transport fails.

    The two local evaluators are used only for secondary market-data quotes.
    Existing validated macro snapshots remain available without this package.
    """
    from fx_scanner.xau_intraday_macro_v398 import (
        fetch_yahoo_chart, evaluate_dxy_pressure,
        evaluate_fed_funds_futures_pressure,
    )
    return fetch_yahoo_chart, evaluate_dxy_pressure, evaluate_fed_funds_futures_pressure


def fresh(t, now, seconds=150):
    at = stamp(t)
    return at is not None and 0 <= (now-at).total_seconds() <= seconds


@st.cache_data(ttl=120, show_spinner=False)
def fallback_market(symbol: str) -> dict:
    """Secondary quote, NOT official CME/ICE or a FedWatch probability."""
    if symbol == "ZQ":
        endpoint = "https://query1.finance.yahoo.com/v8/finance/chart/ZQ=F"
    elif symbol == "DXY":
        endpoint = "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB"
    else:
        raise ValueError("UNSUPPORTED_USD_LEAD_SYMBOL")
    fetch_yahoo_chart, _, _ = _load_intraday_market_helpers()
    points = fetch_yahoo_chart(
        base_url=endpoint, allowed_host="query1.finance.yahoo.com",
        timeout_seconds=5., interval="5m", range_name="1d",
    )
    # Use original timestamp of the LAST quote to evaluate staleness at view time.
    return {"observations": list(points), "symbol": symbol}


@st.cache_data(ttl=1800, show_spinner=False)
def bundesbank_snapshot() -> dict:
    return fetch_bundesbank_2y(now=datetime.now(UTC), timeout_seconds=7.)


def supplemental_quotes(evaluation: dict, now: datetime) -> tuple[dict, dict]:
    """Only use fallback for a missing original source; never paper over stale data."""
    out = dict(evaluation)
    notes = {}
    try:
        _, evaluate_dxy_pressure, evaluate_fed_funds_futures_pressure = (
            _load_intraday_market_helpers()
        )
    except ModuleNotFoundError as exc:
        if exc.name != "curl_cffi":
            raise
        # Never crash the page because a secondary quote transport is missing.
        # Pure USD Lead guards will mark absent/stale evidence UNKNOWN/WAIT.
        unavailable = "Transport Yahoo curl_cffi belum terpasang; gunakan feed makro tervalidasi"
        return out, {"fed_funds_futures": unavailable, "dxy_intraday": unavailable}
    for key, name, f in (
        ("fed_funds_futures", "ZQ", evaluate_fed_funds_futures_pressure),
        ("dxy_intraday", "DXY", evaluate_dxy_pressure),
    ):
        existing = obj(out.get(key))
        # A stale available=True flag is NOT a current quote; fetch the
        # secondary source when original observation has aged out.
        if (existing.get("available") is True
                and fresh(existing.get("current_at"), now, 900)):
            notes[key] = "Sumber makro ForexScanner, original timestamp valid"
            continue
        try:
            data = fallback_market(name)
            out[key] = f(data["observations"], now=now, max_age_seconds=900)
            notes[key] = "Yahoo Finance proxy; bukan kuotasi ICE/CME langsung"
        except Exception as exc:
            # Third-party HTTP libraries may raise a RequestException not derived
            # from OSError; a failed fallback is UNKNOWN, never a page-wide crash.
            notes[key] = "Feed cadangan tidak tersedia: " + type(exc).__name__
    return out, notes


def current_xau_technical(now, macro_evaluation):
    candles = {}
    try:
        candles = fetch_decision_candles(now=now, timeout_seconds=6.)
    except (OSError, ValueError, TypeError) as exc:
        candle_note = "Candle XAU belum valid: " + type(exc).__name__
    else:
        candle_note = "H1/M15/M5 closed cTrader LIVE 7903"

    decision = None
    v404_fresh = False
    try:
        snapshot = fetch_public_hot_snapshot(now=now, timeout_seconds=6.)
        workers = [obj(h) for h in (snapshot.get("heartbeats") or [])
                   if obj(h).get("worker_name") == "ctrader_demo_xau_sd_liquidity_v342"]
        workers.sort(key=lambda h: str(h.get("observed_at") or ""), reverse=True)
        h = workers[0] if workers else {}
        ev = obj(obj(h.get("details")).get("evaluation"))
        original_at = ev.get("price_observed_at") or obj(ev.get("market_context")).get("price_observed_at")
        v404_fresh = bool(h.get("healthy") is True
                           and fresh(h.get("observed_at"), now)
                           and fresh(original_at, now)
                           and ev.get("execution_authority") is not True)
        if v404_fresh:
            decision = evaluate_runtime_decision_v404(ev)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        pass
    checklist = evaluate_checklist(
        decision=decision, macro_evaluation=macro_evaluation,
        candle_feed=candles, broker_spec=None,
        equity_usd=100., structure_fresh=v404_fresh, now=now,
    )
    return checklist, candle_note, v404_fresh


@st.fragment(run_every="60s")
def render_usd_lead():
    now = datetime.now(UTC)
    st.subheader("USD Lead Checklist — sinyal pendahulu dan konfirmasi")
    evaluation, notes = {}, {}
    try:
        macro_snapshot = fetch_pre_news_snapshot(now=now, timeout_seconds=7.)
        evaluation = obj(macro_input(macro_snapshot, now=now).get("evaluation"))
        notes["macro"] = "ForexScanner macro heartbeat valid; setiap quote diperiksa ulang"
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        notes["macro"] = "Snapshot makro belum valid: " + type(exc).__name__

    evaluation, quotes_notes = supplemental_quotes(evaluation, now)
    notes.update(quotes_notes)

    spread = None
    try:
        bund = bundesbank_snapshot()
        spread = pair_with_treasury_2y(
            bund, obj(obj(evaluation.get("components")).get("US2Y")), now=now
        )
        notes["spread"] = (
            "US2Y Treasury + DE2Y Bundesbank; observasi tanggal sama"
            if spread else "Tanggal Treasury dan Bundesbank tidak cocok / belum rilis"
        )
    except (OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        notes["spread"] = "Bundesbank belum dapat diverifikasi: " + type(exc).__name__

    xau, candle_note, zone_fresh = current_xau_technical(now, evaluation)
    notes["xau"] = candle_note
    notes["v404"] = "Original V404 broker price FRESH" if zone_fresh else "V404 not fresh/unknown"

    # Yield pressure is a qualitative 15–60m projection. It uses fresh
    # market pressure, NOT the old daily Treasury release as a prediction.
    yield_projection = evaluate_yield_pressure(
        evaluation, now=now, fed_funds=evaluation.get("fed_funds_futures")
    )
    report = evaluate_usd_lead(
        evaluation, spread=spread, xau_checklist=xau,
        yield_nowcast=yield_projection, now=now,
    )
    up, down = report["usd_up"], report["usd_down"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("USD Menguat", str(up["passed"]) + "/" + str(len(up["rows"])))
    c2.metric("USD Melemah", str(down["passed"]) + "/" + str(len(down["rows"])))
    c3.metric("USD Direction", report["usd_direction"])
    c4.metric(
        "Yield 15–60m (proxy)",
        yield_projection["yield_direction"]
        if yield_projection["state"] in {"CONCORDANT_PROXY", "ZN_PROXY_ONLY"}
        else "WAIT",
    )
    st.caption(
        "Prediksi yield = hipotesis tekanan arah dari ZN futures dan perubahan "
        "ekspektasi Fed ZQ. Bukan proyeksi angka yield, belum tervalidasi sebagai "
        "forecast, dan tidak menggantikan data US2Y/real yield harian."
    )
    st.caption(
        "DXY adalah KONFIRMASI, bukan indikator pendahulu. Fed futures intraday "
        "dan perubahan yield harian TIDAK boleh diperlakukan sebagai satu frekuensi."
    )

    tab_up, tab_down = st.tabs([
        "USD NAIK + Yield NAIK → Periksa SELL XAU",
        "USD TURUN + Yield TURUN → Periksa BUY XAU",
    ])
    mapping = {"PASS": "✅ TERPENUHI", "FAIL": "❌ BELUM TERPENUHI",
               "UNKNOWN": "⏳ BELUM VALID"}
    for side, parent, direction_key in (
        (up, tab_up, "UP"), (down, tab_down, "DOWN"),
    ):
        with parent:
            st.caption(
                str(side["passed"]) + " terpenuhi • " +
                str(side["failed"]) + " belum terpenuhi • " +
                str(side["unknown"]) + " belum valid • " +
                str(side["leading_votes"]) + " bukti awal selaras"
            )
            for r in side["rows"]:
                with st.container(border=True):
                    st.checkbox(
                        r["label"], value=(r["state"] == "PASS"),
                        disabled=True,
                        key="usd_lead_" + r["key"] + "_" +
                            direction_key + "_" + r["state"],
                    )
                    st.caption(mapping[r["state"]] + " — " + r["detail"])
                    st.caption(
                        "Jenis: " + r["category"] +
                        (" • data " + str(r["observed_at"]) if r["observed_at"] else "")
                    )
            if side["status"].endswith("SHADOW_WATCH"):
                st.warning(
                    side["status"] + ": struktur XAU dan bukti USD selaras. "
                    "Tetap BUKAN rekomendasi order; periksa risiko, berita dan likuiditas."
                )
            elif side["status"] == "USD_DIRECTION_WATCH_ONLY":
                st.info(
                    "USD direction WATCH: yield 15–60m, real yield atau struktur "
                    "XAU belum semuanya terkonfirmasi. BUY/SELL hanya watchlist, "
                    "bukan perintah transaksi."
                )
            elif side["status"] == "USD_DAILY_RATES_WATCH_ONLY":
                st.info(
                    "US2Y dan spread harian mendukung dolar, tetapi futures Fed "
                    "belum tervalidasi. Ini konteks yield, bukan sinyal intraday."
                )
            else:
                st.info("WAIT: belum ada bukti cukup untuk mengambil keputusan berbasis USD.")

    with st.expander("Audit input, sumber, dan risiko"):
        st.json({
            "as_of_utc": report["as_of_utc"],
            "macro_quality": obj(evaluation.get("attribution_quality")).get("quality_state"),
            "provider_notes": notes,
            "spread": spread,
            "yield_pressure_nowcast": yield_projection,
            "xau_SMC_SELL_items": xau["SELL"]["items"],
            "xau_SMC_BUY_items": xau["BUY"]["items"],
            "risk": (
                "Akun $100 adalah referensi; lot, equity aktual, margin broker belum "
                "diverifikasi, jadi panel tidak memberi otoritas entry."
            ),
            "live_trade_order_enabled": False,
            "prediction_accuracy_validated": False,
        })
        st.markdown(
            "Rujukan resmi: [CME FedWatch](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool) • "
            "[US Treasury](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics) • "
            "[Bundesbank 2Y](https://www.bundesbank.de/en/statistics/money-and-capital-markets/interest-rates-and-yields/daily-yields-of-current-federal-securities-772220)"
        )
    st.caption(
        "USD LEAD V2 • BUY/SELL simetris + yield pressure proxy, refresh ±60 detik • "
        "tidak mengubah Frozen V1, cBot, bridge, atau posisi LIVE."
    )


st.title("RIZAN — USD Lead Engine V2 · BUY & SELL + Yield")
st.warning(
    "Alat bantu keputusan, BUKAN algoritma profit yang sudah tervalidasi. "
    "Tidak ada probabilitas akurasi 15 menit/1 jam/6 jam yang diklaim."
)
render_usd_lead()
