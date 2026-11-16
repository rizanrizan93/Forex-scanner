"""Independent read-only XAU consensus; frozen Bootstrap125 V1 remains primary.

Never publishes cBot entry signals, native order entitlement, or overrides
frozen risk, execution, VPS or bridge state.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import streamlit as st

from .cbot_v1_dashboard import MARKET_URL, SOURCE_URL, evaluate_snapshot, fetch_json, fetch_snapshot, wib
from .frozen_v1_directional_score import evaluate_bias
from .xau_v1_primary_consensus import evaluate_consensus
from .xau_unified_inputs_v1 import macro_and_notes
from .xau_decision_candle_feed_v1 import fetch_decision_candles
from .xau_decision_checklist_v1 import evaluate_checklist
from .xau_technical_engine_v1 import evaluate_technical
from .xau_yield_pressure_nowcast_v1 import evaluate_yield_pressure
from .usd_lead_decision_v1 import evaluate_usd_lead
from .xau_unified_decision_v1 import evaluate_unified
from .xau_weighted_opportunity_v1 import evaluate_opportunity


def _metric(value):
    return "—" if value is None else f"{value:.1f}/100"


@st.cache_data(ttl=10, show_spinner=False)
def _broker_snapshot(kind: str, slot: int):
    if kind == "status":
        return fetch_snapshot(slot)
    return fetch_json(MARKET_URL, slot)


def _read_broker(kind: str):
    try:
        slot = int(datetime.now(UTC).timestamp() // 10)
        return _broker_snapshot(kind, slot)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return None


@st.cache_data(ttl=30, show_spinner=False)
def _research_snapshot(slot: int):
    now = datetime.now(UTC)
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        candle_future = pool.submit(fetch_decision_candles, now=now, timeout_seconds=6.)
        macro_future = pool.submit(macro_and_notes, now)
        try:
            candles = candle_future.result()
        except (OSError, ValueError, TypeError, KeyError, TimeoutError) as exc:
            candles = {}
            errors.append("candles=" + type(exc).__name__)
        try:
            macro, spread, notes = macro_future.result()
        except (OSError, ValueError, TypeError, KeyError, TimeoutError) as exc:
            macro, spread, notes = {}, None, {}
            errors.append("macro=" + type(exc).__name__)
    technical = evaluate_technical(candles, now=now)
    # The retired V404 DEMO worker must NOT be treated as LIVE evidence.
    checklist = evaluate_checklist(
        decision={}, macro_evaluation=macro, candle_feed=candles,
        broker_spec={}, structure_fresh=False, equity_usd=100., now=now,
    )
    yield_pressure = evaluate_yield_pressure(
        macro, now=now, fed_funds=macro.get("fed_funds_futures")
    )
    usd = evaluate_usd_lead(
        macro, now=now, spread=spread,
        xau_checklist=checklist, yield_nowcast=yield_pressure,
    )
    unified = evaluate_unified(
        technical=technical, checklist=checklist, usd=usd,
        yield_pressure=yield_pressure, now=now,
    )
    opportunity = evaluate_opportunity(
        unified=unified, technical=technical, checklist=checklist,
    )
    return {"candles": candles, "opportunity": opportunity,
            "notes": notes, "errors": errors,
            "as_of_utc": now.isoformat(),
            "usd": usd.get("usd_direction"),
            "yield": yield_pressure.get("yield_direction"),
            "sources_valid": unified.get("sources_valid")}


def _render():
    now = datetime.now(UTC)
    st.subheader("Konsensus XAUUSD · Frozen V1 Utama")
    st.caption(
        "Strategi utama: RIZAN_BOOTSTRAP125_V1_FROZEN_20261114 · "
        "LIVE ••••7903 · sumber independen, candle tertutup, tanpa mengubah cBot."
    )
    with ThreadPoolExecutor(max_workers=3) as pool:
        status_future = pool.submit(_read_broker, "status")
        market_future = pool.submit(_read_broker, "market")
        research_future = pool.submit(_research_snapshot, int(now.timestamp() // 30))
        status = status_future.result()
        market = market_future.result()
        try:
            research = research_future.result()
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, TimeoutError) as exc:
            research = {"candles": {}, "opportunity": {}, "notes": {},
                        "errors": ["research=" + type(exc).__name__]}
    model = None
    try:
        if status:
            model = evaluate_snapshot(status, now=now)
    except (ValueError, TypeError, KeyError):
        pass
    phase = model["phase"] if model else "UNKNOWN"
    report = evaluate_bias(market, phase=phase, now=now)
    consensus = evaluate_consensus(
        v1_report=report, research_report=research.get("opportunity"),
        v1_market=market, research_candles=research.get("candles"),
        phase=phase, now=now,
        bridge_ready=bool(model and model["bridge_ready"]),
    )
    v1 = report["symbols"]["XAUUSD"]
    opportunity = research.get("opportunity") or {}

    st.markdown("### Keputusan pembanding")
    st.write("**" + consensus["state"].replace("_", " ") + "**")
    st.write(consensus["explanation"])
    st.caption("Ini label riset, bukan perintah entry. Prioritas native Frozen V1 tidak berubah.")
    a, b = st.columns(2)
    a.metric("Frozen V1 · bias pola", consensus["v1_direction"])
    b.metric("Analisis Terpadu · bias riset", consensus["research_direction"])
    st.caption("Keduanya tidak menggunakan bobot yang sama; skor tidak dapat dibandingkan langsung.")
    st.markdown("#### Skor BUY dan SELL")
    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Frozen V1 · pola (parsial)**")
        st.metric("BUY", _metric(v1["BUY"]["score"]))
        st.metric("SELL", _metric(v1["SELL"]["score"]))
        st.caption("Keluarga BUY: " + str(v1["BUY"]["family"] or "—"))
        st.caption("Keluarga SELL: " + str(v1["SELL"]["family"] or "—"))
    with cols[1]:
        st.markdown("**Analisis Terpadu · konfluensi**")
        st.metric("BUY", _metric((opportunity.get("BUY") or {}).get("score")))
        st.metric("SELL", _metric((opportunity.get("SELL") or {}).get("score")))
        st.caption("BUY: " + str((opportunity.get("BUY") or {}).get("state", "WAIT DATA")))
        st.caption("SELL: " + str((opportunity.get("SELL") or {}).get("state", "WAIT DATA")))

    st.markdown("#### Kesiapan eksekusi Frozen V1")
    st.write("**" + consensus["native_entry_readiness"] + "** — bukti lengkap native belum tersedia.")
    st.caption(
        "Skor pola tidak memverifikasi warmup, bias H1, filter yield/news bawaan, "
        "Guard47, risiko, margin, cooldown, intent, atau respons broker."
    )
    if not consensus["v1_bridge_connected"]:
        st.warning("Bridge/lease native V1 belum terverifikasi baru. "
                   "Tidak boleh mengartikan skor pola sebagai kesiapan order.")
    st.caption("Fase: " + phase + " · keluarga terpilih: " + str(consensus["v1_family"] or "—")
               + " · status jam keluarga: " + consensus["v1_session"])

    with st.expander("Audit keselarasan candle H1/M5", expanded=False):
        st.write("Status: " + consensus["alignment"])
        for tf, row in consensus["candle_comparison"].items():
            st.write("**" + tf + "** · " + str(row.get("status")))
            st.caption(
                "V1 close: " + str(row.get("v1_closed_at", "—"))
                + " · Riset close: " + str(row.get("research_closed_at", "—"))
                + " · harga V1: " + str(row.get("v1_close", "—"))
                + " · harga riset: " + str(row.get("research_close", "—"))
                + " · gap: " + str(row.get("price_gap", "—"))
            )
        st.caption("Perbedaan harga di luar batas sanity-check atau timestamp berbeda "
                   "membatalkan konsensus, bukan menghapus sinyal V1.")
    with st.expander("Audit data dan sumber", expanded=False):
        st.json({
            "now_utc": now.isoformat(),
            "v1_snapshot_observed_at": status.get("observed_at") if isinstance(status, dict) else None,
            "market_observed_at": market.get("observed_at") if isinstance(market, dict) else None,
            "research_observed_at": research.get("as_of_utc"),
            "research_candle_as_of": (research.get("candles") or {}).get("as_of"),
            "usd_direction": research.get("usd"),
            "yield_direction": research.get("yield"),
            "source_validity": research.get("sources_valid"),
            "errors": research.get("errors"),
            "macro_notes": research.get("notes"),
            "frozen_profile": consensus["primary_strategy"],
            "missed_order_verdict": consensus["missed_order_verdict"],
            "order_enabled": False,
        })
    st.caption("Diperiksa " + wib(now.isoformat()) + " · refresh 60 detik")
    st.markdown("[Kontrak strategi Frozen V1](" + SOURCE_URL + ")")


def render_xau_v1_primary_consensus():
    st.fragment(run_every="60s")(_render)()
