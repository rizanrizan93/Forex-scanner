"""Explainable, read-only XAU macro synthesis.

Treasury (real yield/US2Y/US10Y as ONE cluster), DXY and quality-gated
WTI+Brent (as ONE small inflation channel) contribute to a heuristic XAU score.
Do not separately vote Fed/inflation again: those overlap with yield and Oil.
Oil cannot infer geopolitics from price alone. Never authorize orders.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

from .xau_oil_macro_context import assess_oil_macro

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


def analyze_gold_macro(
    *,
    yields: dict[str, dict[str, Any]],
    dxy: dict[str, Any] | None,
    pce_yoy: float | None = None,
    cpi_yoy: float | None = None,
    oil: dict[str, dict[str, Any] | None] | None = None,
    metals: dict[str, dict[str, Any] | None] | None = None,
    fed_repricing: dict[str, Any] | None = None,
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
                 and _valid(dxy.get("observed"), now, 1.5))
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
    # Intraday futures are prioritized; daily FRED observations receive a
    # reduced allocation only while both are <=48h old.
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
                  else 0.08 if daily_oil_recent and oil_vote is not None
                  else 0.0)
    oil_counted = oil_weight > 0
    oil_assessment["score_influence"] = oil_counted
    oil_assessment["score_weight_pct"] = round(100 * oil_weight)
    oil_assessment["score_reason"] = (
        "Futures intraday WTI+Brent dinilai sebagai satu kanal inflasi (bobot 15%)."
        if oil_status == "INTRADAY" and oil_counted
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
    core_coverage_fraction = (
        0.55 * min(1, available_yield_weight) + 0.45 * int(dxy_valid)
    )
    # Published coverage covers all three clusters (Oil max 15%). Daily oil
    # counts as partial coverage; stale Oil does not masquerade as live.
    coverage = round(100 * (0.85 * core_coverage_fraction + oil_weight))
    coverage_core_pct = round(100 * core_coverage_fraction)
    missing = []
    if treasury is None:
        missing.append("Treasury (minimal dua sumber yield valid)")
    if dollar is None:
        missing.append("DXY intraday (<90 menit)")
    core_score = None
    breakdown = {"Treasury": None, "DXY": None, "Oil": None}
    if missing:
        score = None
        bias = "DATA TIDAK CUKUP"
        strength = "TIDAK DINILAI"
        rationale = "Data pasar utama belum memadai untuk kesimpulan arah."
        state = "WAIT_DATA"
    else:
        base = 0.55 * treasury + 0.45 * dollar
        core_score = round(100 * base)
        # Oil off => preserve exact legacy 55/45 model. Oil on => shrink
        # existing core pro-rata and dedicate only 8%/15% to the energy vote.
        treasury_points = 100 * (1 - oil_weight) * 0.55 * treasury
        dollar_points = 100 * (1 - oil_weight) * 0.45 * dollar
        oil_points = 100 * oil_weight * oil_vote if oil_counted else 0.0
        breakdown = {
            "Treasury": round(treasury_points, 2),
            "DXY": round(dollar_points, 2),
            "Oil": round(oil_points, 2) if oil_counted else None,
        }
        score = round(treasury_points + dollar_points + oil_points)
        core_conflict = treasury * dollar < 0
        oil_conflict = oil_counted and oil_vote != 0 and base * oil_vote < 0
        state = ("CONFLICT" if core_conflict else
                 "OIL_CONFLICT" if oil_conflict else "ALIGNED_OR_FLAT")
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
                         "skor gabungan sudah memasukkan perbedaan ini, belum ada konfirmasi geopolitik.")
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
                   " Jalur geopolitik tidak pernah otomatis menjadi vote.")

    metals = metals or {}
    gold, silver = metals.get("Gold") or {}, metals.get("Silver") or {}
    if all(item.get("fresh") and _num(item.get("pct")) is not None for item in (gold, silver)):
        g, s = _num(gold["pct"]), _num(silver["pct"])
        context.append(f"Konfirmasi harga: futures Gold {g:+.2f}%, Silver {s:+.2f}%; tidak dipakai memberi suara makro.")
    else:
        context.append("Konfirmasi Gold/Silver futures belum komplet; tidak menjadi vote.")

    bullish = [item for item in details if item["direction"] == 1]
    bearish = [item for item in details if item["direction"] == -1]
    neutral = [item for item in details if item["direction"] == 0]
    return {
        "bias": bias, "strength": strength, "score": score,
        "core_score": core_score, "score_breakdown": breakdown,
        "oil_weight_pct": round(oil_weight * 100),
        "oil_score_counted": oil_counted, "coverage_core_pct": coverage_core_pct,
        "coverage_pct": coverage, "state": state,
        "rationale": rationale, "missing": missing,
        "factors": details, "bullish": bullish, "bearish": bearish,
        "neutral": neutral, "context": context,
        "oil_assessment": oil_assessment,
        "model": "EXPLAINABLE_HEURISTIC_V2_OIL_WEIGHTED_NOT_CALIBRATED",
        "horizon": "intraday ke 1–3 sesi (konteks, bukan prediksi)",
        "as_of_utc": now.isoformat(),
        "execution_authority": False, "execution_influence": False,
    }
