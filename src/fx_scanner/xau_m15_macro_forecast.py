"""Read-only, candle-aligned XAUUSD M15 directional forecast.

The existing macro consensus contains Treasury, DXY, oil, geopolitics and
safe-haven votes. This module adds a small, same-source M15 price confirmation.
Weights are deterministic heuristics, NOT calibrated probabilities. No broker
or trading APIs are imported or called.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from .xau_macro_gold_consensus import explain_oil_component

WIB = ZoneInfo("Asia/Jakarta")
SNAPSHOT_CONTRACT = "RIZAN_XAU_MANUAL_REVERSAL_MAP_V2"
SNAPSHOT_SOURCE = "CTRADER_MARKET_DATA_READ_ONLY"
MAX_PRICE_AGE_SECONDS = 150
MAX_PUBLICATION_AGE_SECONDS = 180


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo else None


def _wib(value: Any) -> str:
    stamp = _utc(value)
    return stamp.astimezone(WIB).strftime("%d/%m %H:%M:%S WIB") if stamp else "—"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if isfinite(number) else None


def _fresh(timestamp: Any, now: datetime, max_age: int) -> bool:
    observed = _utc(timestamp)
    if observed is None:
        return False
    age = (now - observed).total_seconds()
    return 0 <= age <= max_age



FAST_CONTRACT = "RIZAN_XAU_M15_BROKER_READONLY_V1"
M15_BUILD = "M15-R2-20261109-RELOAD"


def validate_fast_m15_snapshot(snapshot: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Strict broker-only closed-bar contract. Publication time is never price time."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    if (not isinstance(snapshot, dict)
            or set(snapshot) != {
                "contract", "symbol", "source", "account_suffix", "as_of",
                "price_observed_at", "price", "latest_closed_m15",
                "timeframe_fresh", "execution_authority", "execution_influence"
            }
            or snapshot["contract"] != FAST_CONTRACT
            or snapshot["symbol"] != "XAUUSD"
            or snapshot["account_suffix"] != "7903"
            or snapshot["source"] != SNAPSHOT_SOURCE
            or snapshot["execution_authority"] is not False
            or snapshot["execution_influence"] is not False):
        raise ValueError("XAU_M15_FAST_CONTRACT_INVALID")
    published_at = _utc(snapshot.get("as_of"))
    price_at = _utc(snapshot.get("price_observed_at"))
    m15 = snapshot.get("latest_closed_m15")
    closed = _utc(m15.get("closed_at")) if isinstance(m15, dict) else None
    start = now.replace(minute=15 * (now.minute // 15), second=0, microsecond=0)
    quote = _number(snapshot.get("price"))
    close = _number(m15.get("close")) if isinstance(m15, dict) else None
    if (not _fresh(published_at, now, MAX_PUBLICATION_AGE_SECONDS)
            or not _fresh(price_at, now, MAX_PRICE_AGE_SECONDS)
            or closed != start
            or price_at is None or price_at < closed
            or not isinstance(m15, dict) or set(m15) != {"close", "closed_at"}
            or snapshot.get("timeframe_fresh") != {"M15": True}
            or quote is None or close is None or quote <= 0 or close <= 0):
        raise ValueError("XAU_M15_FAST_CANDLE_STALE_OR_INVALID")
    if abs(100 * (quote / close - 1)) > 1.5:
        raise ValueError("XAU_M15_FAST_PRICE_GAP_GT_1P5_PCT")
    return snapshot


def forecast_m15_xau(
    macro_result: dict[str, Any] | None,
    candle_snapshot: dict[str, Any] | None,
    *,
    event_risk: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Estimate the sign of the currently forming M15 candle.

    Uses last CLOSED broker M15 close as the reference, not an invented
    current-candle open. A prediction is only eligible in the candle interval
    immediately after that close; a stale or future bar is rejected.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    now = now.astimezone(UTC)
    start = now.replace(minute=15 * (now.minute // 15), second=0, microsecond=0)
    end = start + timedelta(minutes=15)
    macro = macro_result or {}
    snapshot = candle_snapshot or {}
    result: dict[str, Any] = {
        "status": "WAIT_DATA",
        "direction": "BELUM ADA PREDIKSI",
        "confluence": "TIDAK DINILAI",
        "index": None,
        "macro_index": None,
        "candle_index": None,
        "price": None,
        "reference_close": None,
        "delta_pct": None,
        "candle_start": start.isoformat(),
        "candle_end": end.isoformat(),
        "seconds_remaining": max(0, int((end - now).total_seconds())),
        "reason": "",
        "score_breakdown": dict(macro.get("score_breakdown") or {}),
        "geo_status": str((macro.get("geo_haven_assessment") or {}).get("status") or "TIDAK TERSEDIA"),
        "execution_authority": False,
        "execution_influence": False,
        "model": "M15_CANDLE_MACRO_CONFIRMATION_V1_UNCALIBRATED",
    }

    fast = snapshot.get("contract") == FAST_CONTRACT
    if fast:
        try:
            validate_fast_m15_snapshot(snapshot, now=now)
        except ValueError as exc:
            result["reason"] = "Feed broker M15 khusus belum valid: " + str(exc)
            return result

    if (snapshot.get("contract") not in (SNAPSHOT_CONTRACT, FAST_CONTRACT)
            or snapshot.get("symbol") != "XAUUSD"
            or snapshot.get("source") != SNAPSHOT_SOURCE
            or snapshot.get("execution_authority") is not False
            or snapshot.get("execution_influence") is not False):
        result["reason"] = "Snapshot candle cTrader read-only tidak tersedia/kontrak tidak valid."
        return result
    if not fast and snapshot.get("fresh") is not True:
        result["reason"] = "Snapshot cTrader M15 stale; pasar mungkin tutup atau feed berhenti."
        return result
    if (not _fresh(snapshot.get("as_of"), now, MAX_PUBLICATION_AGE_SECONDS)
            or not _fresh(snapshot.get("price_observed_at"), now, MAX_PRICE_AGE_SECONDS)):
        result["reason"] = "Harga atau publikasi M15 melewati batas freshness."
        return result

    last_bar = snapshot.get("latest_closed_m15") or {}
    closed_at = _utc(last_bar.get("closed_at"))
    price = _number(snapshot.get("price"))
    last_close = _number(last_bar.get("close"))
    if (closed_at != start or price is None or last_close is None
            or price <= 0 or last_close <= 0
            or not (snapshot.get("timeframe_fresh") or {}).get("M15")):
        result["reason"] = "Menunggu penutupan M15 yang tepat pada awal candle berjalan."
        return result

    result["data_source"] = "cTrader LIVE 7903 · M1 + M15 closed" if fast else "cTrader reversal/legacy"
    result["price"] = price
    result["reference_close"] = last_close
    delta_pct = 100.0 * (price / last_close - 1.0)
    result["delta_pct"] = delta_pct
    if abs(delta_pct) > 1.5:
        result["reason"] = "Perubahan harga >1,5% dalam satu candle; periksa gap/ketidaksesuaian feed."
        return result

    # Price-only fallback is intentionally restricted to the dedicated,
    # validated LIVE broker source; legacy reversal snapshots cannot qualify.
    # Momentum is an observed technical bias, not an invented macro forecast.
    candle_score = max(-100.0, min(100.0, delta_pct / 0.05 * 100))
    result["technical_index"] = round(candle_score, 1)
    event_state = str((event_risk or {}).get("state") or "UNAVAILABLE").upper()
    if event_state not in {"CLEAR", "UNAVAILABLE", "NONE"}:
        result["status"] = "EVENT_RISK"
        result["reason"] = "Risiko rilis berita aktif (" + event_state + "); prediksi arah ditangguhkan."
        return result

    macro_score = _number(macro.get("score"))
    core_coverage = _number(macro.get("coverage_core_pct"))
    if (macro_score is None or abs(macro_score) > 100
            or core_coverage is None or core_coverage < 75
            or str(macro.get("state")) == "WAIT_DATA"):
        if fast:
            # Min. ~0.02% movement limits flip-flopping on tick-sized noise.
            # No numerical probability or macro contribution is asserted.
            result["status"] = "TECHNICAL_ONLY"
            result["confluence"] = "TERBATAS · TANPA KONFIRMASI MAKRO"
            if delta_pct >= 0.02:
                result["direction"] = "BIAS TEKNIKAL BULLISH M15"
            elif delta_pct <= -0.02:
                result["direction"] = "BIAS TEKNIKAL BEARISH M15"
            else:
                result["direction"] = "NETRAL · BELUM ADA EDGE M15"
            result["reason"] = (
                "Arah sementara berdasarkan pergerakan harga broker pada candle M15 "
                "yang sedang terbentuk; Treasury/DXY belum lengkap. "
                "Bukan prediksi gabungan atau sinyal eksekusi."
            )
        else:
            result["reason"] = "Data Treasury/DXY untuk skor gabungan makro belum memadai."
        return result

    # Macro already incorporates non-duplicated Oil, geopolitical and safe
    # haven votes. Same-source M15 reference acts only as 20% confirmation.
    # +/-0.05% is a heuristic momentum scale, not a measured volatility model.
    combined = 0.80 * macro_score + 0.20 * candle_score
    result.update(
        status="READY",
        macro_index=round(macro_score, 1),
        candle_index=round(candle_score, 1),
        index=round(combined, 1),
    )
    if combined >= 25:
        result["direction"] = "PREDIKSI BULLISH M15"
    elif combined <= -25:
        result["direction"] = "PREDIKSI BEARISH M15"
    else:
        result["direction"] = "NETRAL / TIDAK ADA EDGE"

    if abs(combined) >= 65:
        result["confluence"] = "KUAT (HEURISTIK)"
    elif abs(combined) >= 40:
        result["confluence"] = "SEDANG (HEURISTIK)"
    else:
        result["confluence"] = "RENDAH (HEURISTIK)"
    if str(macro.get("state")) in {"CONFLICT", "OIL_CONFLICT", "RISK_CONFLICT"}:
        result["confluence"] = "TERBATAS — KONFLIK FAKTOR"
    result["reason"] = (
        "80% skor makro terverifikasi + 20% konfirmasi arah harga XAU "
        "terhadap close M15 sebelumnya. Bobot tidak terkalibrasi terhadap "
        "akurasi historis dan tidak merupakan probabilitas naik/turun."
    )
    return result


def render_macro_m15_forecast(
    macro_result: dict[str, Any],
    *,
    snapshot_loader: Any,
    event_risk: dict[str, Any] | None = None,
) -> None:
    """Minimal, mobile-friendly Streamlit panel; entirely display-only."""
    import streamlit as st

    snapshot, error = None, None
    try:
        snapshot = snapshot_loader()
    except Exception as exc:
        # Our own sanitized source error codes are useful diagnostics.
        # Do not print network exception bodies or credentials.
        error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    forecast = forecast_m15_xau(macro_result, snapshot, event_risk=event_risk)
    start = _utc(forecast["candle_start"]).astimezone(WIB)
    end = _utc(forecast["candle_end"]).astimezone(WIB)

    st.subheader("PREDIKSI ARAH XAUUSD · CANDLE M15")
    st.caption("Engine " + M15_BUILD + " · pembacaan cTrader LIVE 7903, read-only")
    st.caption(
        f"Interval candle {start:%d/%m/%Y %H:%M}–{end:%H:%M} WIB · "
        f"tersisa {forecast['seconds_remaining'] // 60:02d}:"
        f"{forecast['seconds_remaining'] % 60:02d} · pembaruan dashboard ±60 detik."
    )
    # A 4-minute-old candle should never appear blank when broker evidence is
    # already usable. Keep the primary value compact for mobile screens.
    if forecast["status"] == "TECHNICAL_ONLY":
        headline = forecast["direction"].replace("BIAS TEKNIKAL ", "")
        strength = "TERBATAS"
        heading = "Bias harga sementara"
    elif forecast["status"] == "EVENT_RISK":
        headline, strength, heading = "DITAHAN: NEWS", "RISIKO EVENT", "Status prediksi"
    elif forecast["status"] == "WAIT_DATA":
        headline, strength, heading = "MENUNGGU FEED", "DATA BELUM VALID", "Status prediksi"
    else:
        headline = forecast["direction"].replace("PREDIKSI ", "")
        strength = forecast["confluence"]
        heading = "Perkiraan candle"
    if isinstance(snapshot, dict):
        st.caption(
            "cTrader 7903 · harga M1 " + _wib(snapshot.get("price_observed_at"))
            + " · close M15 " + _wib(
                (snapshot.get("latest_closed_m15") or {}).get("closed_at")
            )
        )
    a, b, c = st.columns(3)
    a.metric(heading, headline)
    b.metric("Indeks gabungan", "—" if forecast["index"] is None else f"{forecast['index']:+.1f} / 100")
    c.metric("Konfirmasi", strength)
    if forecast["status"] != "READY":
        if forecast["status"] == "TECHNICAL_ONLY":
            st.info("BIAS TEKNIKAL SEMENTARA · makro belum terkonfirmasi. Bukan sinyal entry.")
            st.caption(forecast["reason"])
            st.caption(
                f"Indeks momentum harga M15: {forecast['technical_index']:+.1f}/100 "
                "(heuristik, bukan probabilitas). "
                "Indeks konfluensi gabungan tetap tidak tersedia."
            )
        else:
            st.warning(f"{forecast['status']} · {forecast['reason']}")
        if isinstance(snapshot, dict):
            broker = snapshot.get("contract") == FAST_CONTRACT
            st.caption(
                ("Feed cTrader LIVE 7903" if broker else "Feed reversal lama")
                + " · publikasi: " + _wib(snapshot.get("as_of"))
                + " · harga M1: " + _wib(snapshot.get("price_observed_at"))
                + " · close M15 terakhir: "
                + _wib((snapshot.get("latest_closed_m15") or {}).get("closed_at"))
            )
        if forecast.get("price") is not None:
            st.caption(
                "Momentum candle yang sedang terbentuk (bukan prediksi): "
                + ("NAIK" if forecast["delta_pct"] > 0 else
                   "TURUN" if forecast["delta_pct"] < 0 else "DATAR")
                + f" {forecast['delta_pct']:+.3f}% dari close M15 sebelumnya."
            )
        missing = (macro_result or {}).get("missing") or []
        if missing:
            st.caption("Penghalang makro: " + "; ".join(str(x) for x in missing[:4]))
        if error:
            st.caption("Diagnosis snapshot M15: " + error)
    else:
        st.caption(
            f"Broker XAUUSD {forecast['price']:,.2f} · close M15 sebelumnya "
            f"{forecast['reference_close']:,.2f} · Δ {forecast['delta_pct']:+.3f}% "
            f"(sumber yang sama: cTrader read-only)."
        )
        st.caption(
            f"Skor makro {forecast['macro_index']:+.1f}/100 (80%) · "
            f"konfirmasi pergerakan candle {forecast['candle_index']:+.1f}/100 (20%)."
        )
    contributions = forecast["score_breakdown"]
    labels = [("Treasury", "Yield/real yield"), ("DXY", "Dolar AS"),
              ("Oil", "WTI + Brent"), ("Geopolitical", "Geopolitik"),
              ("Safe Haven", "Safe haven")]
    parts = [
        f"{label}: {float(contributions[key]):+.1f} poin"
        if _number(contributions.get(key)) is not None else f"{label}: belum valid"
        for key, label in labels
    ]
    st.caption("Kontribusi faktor makro — " + " | ".join(parts))
    oil_component = explain_oil_component(macro_result)
    st.write("**WTI + Brent → arah XAU (komponen skor makro):** " + oil_component["headline"])
    st.caption(oil_component["detail"])
    st.caption("Status geopolitik: " + forecast["geo_status"] + ". " + forecast["reason"])
    st.caption(
        "CPI/PCE, kebijakan Fed, dan oil menjadi konteks; Fed yang tercermin "
        "pada yield tidak dihitung dua kali. Geopolitik hanya dihitung apabila "
        "berita dan safe haven memenuhi validasi sumber. Prediksi ini bukan "
        "probabilitas statistik, bukan sinyal order, dan dapat salah."
    )
