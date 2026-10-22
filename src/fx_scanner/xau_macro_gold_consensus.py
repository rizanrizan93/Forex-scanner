"""Explainable, read-only XAU macro synthesis.

Two independently interpreted near-term drivers vote: Treasury rate pressure
(real yield/US2Y/US10Y within ONE cluster) and DXY. Inflation, FOMC proxies,
energy and metal futures are explicitly context/confirmation, not extra votes.
This avoids correlated yield double counting and spurious certainty.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

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
        if available_yield_weight >= 0.49 else None
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
    coverage = round(100 * (0.55 * min(1, available_yield_weight)
                            + 0.45 * int(dxy_valid)))
    missing = []
    if treasury is None:
        missing.append("Treasury (minimal dua sumber yield valid)")
    if dollar is None:
        missing.append("DXY intraday (<90 menit)")
    if missing:
        score = None
        bias = "DATA TIDAK CUKUP"
        strength = "TIDAK DINILAI"
        rationale = "Data pasar utama belum memadai untuk kesimpulan arah."
        state = "WAIT_DATA"
    else:
        score = round(100 * (0.55 * treasury + 0.45 * dollar))
        state = "CONFLICT" if treasury * dollar < 0 else "ALIGNED_OR_FLAT"
        if score >= 25:
            bias = "BULLISH XAU"
        elif score <= -25:
            bias = "BEARISH XAU"
        else:
            bias = "NETRAL / MIXED"
        if state == "CONFLICT":
            strength = "TERBATAS · KONFLIK"
            rationale = "Treasury dan DXY saling bertentangan; keunggulan arah belum konsisten."
        elif abs(score) >= 65 and available_yield_weight >= 0.99 and dollar != 0 and treasury * dollar > 0:
            strength = "KONFLUENSI KUAT (HEURISTIK)"
            rationale = "Tekanan yield dan DXY mendukung arah yang sama; tetap perlu validasi harga."
        elif abs(score) >= 25:
            strength = "SEDANG (HEURISTIK)"
            rationale = "Arah makro dominan, tetapi bukan jaminan harga akan mengikuti."
        else:
            strength = "RENDAH / MIXED"
            rationale = "Dorongan makro dominan belum cukup besar dibanding faktor penentang."

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

    oil = oil or {}
    wti, brent = oil.get("WTI") or {}, oil.get("Brent") or {}
    if all(item.get("fresh") and _num(item.get("pct")) is not None for item in (wti, brent)):
        w, b = _num(wti["pct"]), _num(brent["pct"])
        trend = ("keduanya naik" if w > 0 and b > 0 else
                 "keduanya turun" if w < 0 and b < 0 else "tidak searah")
        context.append(f"Energi: WTI {w:+.2f}%, Brent {b:+.2f}% ({trend}); risiko inflasi dua arah, bukan suara otomatis.")
    else:
        context.append("Energi: observasi WTI/Brent belum cukup segar/komplet.")

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
        "coverage_pct": coverage, "state": state,
        "rationale": rationale, "missing": missing,
        "factors": details, "bullish": bullish, "bearish": bearish,
        "neutral": neutral, "context": context,
        "model": "EXPLAINABLE_HEURISTIC_V1_NOT_CALIBRATED",
        "horizon": "intraday ke 1–3 sesi (konteks, bukan prediksi)",
        "as_of_utc": now.isoformat(),
        "execution_authority": False, "execution_influence": False,
    }
