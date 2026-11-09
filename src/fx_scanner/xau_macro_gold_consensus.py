"""Explainable, read-only XAU macro synthesis.

Treasury, DXY, Oil inflation, and a capped geopolitical/safe-haven
risk cluster contribute conservatively to a heuristic XAU score.
News reports and market proxies must be fresh and independently corroborated;
do not infer geopolitics from Oil, nor double-count Fed/real yield or gold.
Never authorize orders.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

from .xau_oil_macro_context import assess_oil_macro
from .xau_geopolitical_safehaven import assess_geopolitical_safehaven

YIELD_WEIGHTS = {"REAL_YIELD_10Y": 0.50, "US2Y": 0.30, "US10Y": 0.20}
YIELD_NAMES = {
    "REAL_YIELD_10Y": "Real yield 10Y",
    "US2Y": "US2Y",
    "US10Y": "US10Y",
}


def _num(value: Any) -> float | None:
    try:
        value = float(value)
        return value if isfinite(value) else None
    except (ValueError, TypeError):
        return None


def _dt(value: Any) -> datetime | None:
    try:
        observed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return observed.replace(tzinfo=UTC) if observed.tzinfo is None else observed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _valid(observed: Any, now: datetime, max_hours: float) -> bool:
    parsed = _dt(observed)
    if parsed is None:
        return False
    age = (now - parsed).total_seconds()
    return 0 <= age <= max_hours * 3600


def _sign(value: float, deadband: float) -> int:
    return (1 if value >= deadband else -1 if value <= -deadband else 0)


def explain_oil_component(macro_result: dict[str, Any] | None) -> dict[str, str | bool]:
    """Explain the WTI+Brent score cluster; 0-point valid != missing data.

    This is presentation-only. It never alters votes, weights or execution.
    """
    macro = macro_result or {}
    oil = macro.get("oil_assessment") or {}
    breakdown = macro.get("score_breakdown") or {}
    points = _num(breakdown.get("Oil"))
    counted = (macro.get("oil_score_counted") is True
               and points is not None and _num(macro.get("score")) is not None)
    if not counted:
        if _num(macro.get("score")) is None:
            headline = "BELUM MASUK INDEKS — Treasury/DXY belum memadai"
        else:
            headline = "BELUM VALID — bukan vote netral"
        detail = (
            "WTI/Brent tidak diberi arah atau poin sebelum pasangan sumber, "
            "timestamp, dan baseline perubahan lolos validasi. "
            "Bobot efektif 0% pada skor gabungan. "
            + str(oil.get("score_reason") or "")
        )
        return {"headline": headline, "detail": detail, "counted": False}

    trend = str(oil.get("trend") or "UNKNOWN")
    headline = {
        "NAIK": "BEARISH XAU BERSYARAT — risiko inflasi energi meningkat",
        "TURUN": "BULLISH XAU BERSYARAT — tekanan inflasi energi mereda",
        "MIXED/FLAT": "NETRAL — WTI/Brent mixed atau belum melewati ambang",
    }.get(trend, "TIDAK ADA ARAH OIL TERKONFIRMASI")
    values = []
    for name, key in (("WTI", "wti"), ("Brent", "brent")):
        pct = _num((oil.get(key) or {}).get("pct"))
        values.append(f"{name} {pct:+.2f}%" if pct is not None else f"{name} —")
    detail = (
        " | ".join(values)
        + f" · status {oil.get('status') or 'TIDAK TERSEDIA'}"
        + f" · bobot {int(macro.get('oil_weight_pct') or 0)}%"
        + f" · kontribusi {points:+.1f} poin ke skor makro."
        + " Minyak adalah satu cluster; bobotnya tidak dihitung ulang pada M15."
    )
    if trend in {"NAIK", "TURUN"}:
        detail += " Bias minyak melalui inflasi/Fed bersyarat konfirmasi yield/DXY; bukan sinyal entry."
    else:
        detail += " Kontribusi 0 poin berarti data valid tetapi belum directional."
    return {"headline": headline, "detail": detail, "counted": True}


def analyze_gold_macro(
    *,
    yields: dict[str, dict[str, Any]],
    dxy: dict[str, Any] | None,
    pce_yoy: float | None = None,
    cpi_yoy: float | None = None,
    oil: dict[str, dict[str, Any] | None] | None = None,
    metals: dict[str, dict[str, Any] | None] | None = None,
    fed_repricing: dict[str, Any] | None = None,
    geopolitical_articles: list[dict[str, Any]] | None = None,
    haven_markets: dict[str, dict[str, Any] | None] | None = None,
    geopolitical_news_error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return deterministic, provenance-aware macro context, never order permissions.

    + direction supports XAU, - direction pressures XAU. None = unavailable.
    Weights are *heuristic*, not probabilities or backtest-derived accuracy.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    details: list[dict[str, Any]] = []
    available = []
    weighted_yield_sum = 0.0
    available_yield_weight = 0.0

    for symbol, weight in YIELD_WEIGHTS.items():
        row = yields.get(symbol) or {}
        delta = _num(row.get("delta"))
        observed = row.get("observed_at")
        valid = (row.get("freshness") == "FRESH"
                 and delta is not None
                 and _valid(observed, now, 5 * 24))
        if valid:
            direction = -_sign(delta, 1.0)  # higher yield = headwind XAU
            available_yield_weight += weight
            weighted_yield_sum += weight * direction
            available.append(symbol)
            reason = f"Δ yield {delta:+.1f} bps"
        else:
            direction = None
            reason = "Data yield hilang atau stale"
        details.append({
            "name": YIELD_NAMES[symbol], "group": "Treasury",
            "direction": direction, "reason": reason,
            "observed_at": observed, "source": row.get("provider"),
            "counted": valid, "weight": weight,
        })

    treasury = (
        weighted_yield_sum / available_yield_weight
        if len(available) >= 2 and available_yield_weight >= 0.49 else None
    )
    dxy = dxy or {}
    dxy_pct = _num(dxy.get("pct"))
    dxy_valid = (dxy.get("fresh") is True
                 and dxy_pct is not None
                 and _valid(dxy.get("observed"), now, 5 / 60))
    dollar = -_sign(dxy_pct, 0.05) if dxy_valid else None
    details.append({
        "name": "DXY", "group": "Dollar",
        "direction": dollar,
        "reason": f"Δ DXY {dxy_pct:+.3f}% vs {dxy.get('basis') or 'referensi'}"
                  if dxy_valid else "DXY intraday tidak segar/valid",
        "observed_at": dxy.get("observed"),
        "source": dxy.get("source"),
        "counted": dxy_valid, "weight": 1.0,
    })
    # Oil is a separate, *small* inflation channel. Treat WTI+Brent as ONE
    # source cluster; never count oil twice or manufacture geopolitical signs.
    # Intraday DIA indicative spot is prioritized; daily FRED physical spot
    # receives a reduced allocation only while both are <=48h old.
    oil_assessment = assess_oil_macro(oil, now)
    oil_status = oil_assessment["status"]
    oil_trend = oil_assessment["trend"]
    oil_vote = {"TURUN": 1, "NAIK": -1, "MIXED/FLAT": 0}.get(oil_trend)
    daily_oil_recent = (
        oil_status == "HARIAN"
        and all(_valid((oil_assessment.get(name) or {}).get("observed"), now, 48)
                for name in ("wti", "brent"))
    )
    oil_weight = (0.15 if oil_status == "INTRADAY" and oil_vote is not None
                  else 0.05 if oil_status == "SPOT_MOMENTUM" and oil_vote is not None
                  else 0.08 if daily_oil_recent and oil_vote is not None
                  else 0.0)
    oil_counted = oil_weight > 0
    oil_assessment["score_influence"] = oil_counted
    oil_assessment["score_weight_pct"] = round(100 * oil_weight)
    oil_assessment["score_reason"] = (
        "Spot indikatif DIA WTI+Brent segar (≤5 menit) dengan baseline penutupan (bobot 15%)."
        if oil_status == "INTRADAY" and oil_counted
        else "Momentum spot DIA 10–20 menit (bobot indikatif 5%, bukan tren inflasi harian)."
        if oil_status == "SPOT_MOMENTUM" and oil_counted
        else "FRED spot harian WTI+Brent: bobot konservatif 8% (usia data maksimal 48 jam)."
        if oil_status == "HARIAN" and oil_counted
        else "Oil tidak lolos validasi kelengkapan/kesetaraan/freshness untuk skor; tetap konteks."
    )
    if oil_counted:
        details.append({
            "name": "Oil WTI+Brent (inflasi)", "group": "Oil",
            "direction": oil_vote,
            "reason": oil_assessment["summary"] + " " + oil_assessment["score_reason"],
            "observed_at": (oil_assessment["wti"] or {}).get("observed"),
            "source": (oil_assessment["wti"] or {}).get("source"),
            "counted": True, "weight": oil_weight,
        })
    geo_haven = assess_geopolitical_safehaven(
        articles=geopolitical_articles, markets=haven_markets, now=now,
        news_error=geopolitical_news_error,
    )
    geo_weight = geo_haven["geo_weight"]
    haven_weight = geo_haven["haven_weight"]
    risk_weight = geo_haven["total_weight"]
    for name, weight, vote in (
        ("Geopolitical risk (news + market)", geo_weight, geo_haven["geopolitical_vote"]),
        ("Safe haven demand (VIX + JPY/CHF)", haven_weight, geo_haven["safehaven_vote"]),
    ):
        if weight > 0:
            details.append({
                "name": name, "group": "Geo/Safe Haven",
                "direction": vote, "reason": geo_haven["status"],
                "observed_at": now.isoformat(), "source": (
                    "GDELT/publisher RSS reports + market proxy" if name.startswith("Geopolitical")
                    else "Yahoo Finance cross-asset proxies"),
                "counted": True, "weight": weight,
            })
    core_coverage_fraction = (
        0.55 * min(1, available_yield_weight) + 0.45 * int(dxy_valid)
    )
    # 75% core + up to 15% Oil (5% if delayed) + up to 10% risk cluster.
    # Missing independent feeds reduce coverage, not retroactively invent votes.
    coverage = round(100 * (0.75 * core_coverage_fraction + oil_weight + risk_weight))
    coverage_core_pct = round(100 * core_coverage_fraction)
    missing = []
    if treasury is None:
        missing.append("Treasury (minimal dua sumber yield valid)")
    if dollar is None:
        missing.append("DXY intraday (usia sumber maksimal 5 menit)")
    core_score = None
    # Keep a stable schema even when core feeds are unavailable. The Macro
    # panel renders Geo/Safe Haven breakdown during WAIT_DATA too.
    breakdown = {"Treasury": None, "DXY": None, "Oil": None,
                 "Geopolitical": None, "Safe Haven": None}
    if missing:
        score = None
        bias = "DATA TIDAK CUKUP"
        strength = "TIDAK DINILAI"
        rationale = "Data pasar utama belum memadai untuk kesimpulan arah."
        state = "WAIT_DATA"
    else:
        base = 0.55 * treasury + 0.45 * dollar
        core_score = round(100 * base)
        # Preserve Oil's 0/8/15% allocation; the risk group (max 10%)
        # reallocates only part of the remaining Treasury+DXY cluster.
        core_weight = 1 - oil_weight - risk_weight
        treasury_points = 100 * core_weight * 0.55 * treasury
        dollar_points = 100 * core_weight * 0.45 * dollar
        oil_points = 100 * oil_weight * oil_vote if oil_counted else 0.0
        geopolitical_points = 100 * geo_weight * (geo_haven["geopolitical_vote"] or 0)
        haven_points = 100 * haven_weight * (geo_haven["safehaven_vote"] or 0)
        breakdown = {
            "Treasury": round(treasury_points, 2),
            "DXY": round(dollar_points, 2),
            "Oil": round(oil_points, 2) if oil_counted else None,
            "Geopolitical": round(geopolitical_points, 2) if geo_weight else None,
            "Safe Haven": round(haven_points, 2) if haven_weight else None,
        }
        score = round(treasury_points + dollar_points + oil_points
                      + geopolitical_points + haven_points)
        core_conflict = treasury * dollar < 0
        oil_conflict = oil_counted and oil_vote != 0 and base * oil_vote < 0
        risk_conflict = any(
            v is not None and v * base < 0
            for v in (geo_haven["geopolitical_vote"], geo_haven["safehaven_vote"])
        )
        state = ("CONFLICT" if core_conflict else
                 "OIL_CONFLICT" if oil_conflict else
                 "RISK_CONFLICT" if risk_conflict else "ALIGNED_OR_FLAT")
        if score >= 25:
            bias = "BULLISH XAU"
        elif score <= -25:
            bias = "BEARISH XAU"
        else:
            bias = "NETRAL / MIXED"
        if state == "CONFLICT":
            strength = "TERBATAS · KONFLIK"
            rationale = "Treasury dan DXY saling bertentangan; keunggulan arah belum konsisten."
        elif state == "OIL_CONFLICT":
            strength = "TERBATAS · KONFLIK OIL"
            rationale = ("Jalur inflasi Oil berlawanan dengan Treasury/DXY; "
                         "skor gabungan telah memasukkan ketidakselarasan tersebut.")
        elif state == "RISK_CONFLICT":
            strength = "TERBATAS · KONFLIK SAFE HAVEN"
            rationale = ("Indikasi geopolitik/safe haven berlawanan dengan Treasury/DXY; "
                         "tunggu konfirmasi struktur harga.")
        elif abs(score) >= 65 and available_yield_weight >= 0.99 and dollar != 0 and treasury * dollar > 0:
            strength = "KONFLUENSI KUAT (HEURISTIK)"
            rationale = ("Yield dan DXY searah, dengan kontribusi Oil sesuai data "
                         "yang tersedia; tetap perlu validasi harga.")
        elif abs(score) >= 25:
            strength = "SEDANG (HEURISTIK)"
            rationale = "Arah makro dominan setelah pembobotan Oil bila valid; bukan jaminan harga."
        else:
            strength = "RENDAH / MIXED"
            rationale = "Gabungan yield, DXY, dan Oil belum memberi dominasi kuat."

    # An eligible Oil feed cannot contribute points if the core macro score
    # is WAIT_DATA. Keep Oil visible as context but do not call it counted.
    oil_scored = oil_counted and score is not None
    oil_assessment["score_influence"] = oil_scored
    if oil_counted and not oil_scored:
        oil_assessment["score_reason"] += " Core WAIT_DATA; kontribusi Oil ditangguhkan."

    context: list[str] = []
    pce, cpi = _num(pce_yoy), _num(cpi_yoy)
    if pce is not None:
        context.append(f"PCE headline {pce:.2f}% YoY vs target 2%; konteks rezim, bukan surprise/arah entry.")
    else:
        context.append("PCE headline belum tersedia; inflasi tidak diasumsikan.")
    if cpi is not None:
        context.append(f"CPI {cpi:.2f}% YoY: konteks inflasi pendamping.")

    fed = fed_repricing or {}
    fed_state = str(fed.get("state") or "").strip()
    fed_delta = _num(fed.get("delta_bps"))
    if fed_state:
        extra = f" ({fed_delta:+.1f} bps)" if fed_delta is not None else ""
        context.append("Fed repricing: " + fed_state + extra
                       + " — proksi berbasis yield; tidak dihitung lagi sebagai suara independen.")
    else:
        context.append("Probabilitas FOMC belum tersedia sebagai feed terverifikasi; tidak diasumsikan HOLD/HIKE.")

    context.append("Energi: " + oil_assessment["summary"] + " " +
                   oil_assessment["score_reason"] +
                   " Harga minyak sendiri bukan bukti geopolitik.")
    context.append("Geo + safe haven: " + geo_haven["status"] + " · " +
                   geo_haven["summary"])

    metals = metals or {}
    gold, silver = metals.get("Gold") or {}, metals.get("Silver") or {}
    if all(item.get("fresh") and _num(item.get("pct")) is not None for item in (gold, silver)):
        g, s = _num(gold["pct"]), _num(silver["pct"])
        context.append(f"Konfirmasi harga: spot XAU {g:+.2f}%, XAG {s:+.2f}%; tidak dipakai memberi suara makro.")
    else:
        context.append("Konfirmasi spot XAU/XAG belum komplet; tidak menjadi vote.")

    bullish = [item for item in details if item["direction"] == 1]
    bearish = [item for item in details if item["direction"] == -1]
    neutral = [item for item in details if item["direction"] == 0]
    return {
        "bias": bias, "strength": strength, "score": score,
        "core_score": core_score, "score_breakdown": breakdown,
        "oil_weight_pct": round(oil_weight * 100),
        "geo_weight_pct": round(geo_weight * 100),
        "haven_weight_pct": round(haven_weight * 100),
        "geo_haven_assessment": geo_haven,
        "oil_score_counted": oil_scored, "coverage_core_pct": coverage_core_pct,
        "coverage_pct": coverage, "state": state,
        "rationale": rationale, "missing": missing,
        "factors": details, "bullish": bullish, "bearish": bearish,
        "neutral": neutral, "context": context,
        "oil_assessment": oil_assessment,
        "model": "EXPLAINABLE_HEURISTIC_V3_OIL_GEO_HAVEN_NOT_CALIBRATED",
        "horizon": "intraday ke 1–3 sesi (konteks, bukan prediksi)",
        "as_of_utc": now.isoformat(),
        "execution_authority": False, "execution_influence": False,
    }
