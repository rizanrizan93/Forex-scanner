"""Read-only oil context for XAU macro synthesis (not a trading vote).

Oil is an inflation input and a possible geopolitical shock proxy, not an
unconditional XAU buy/sell signal. Reject stale and incomparable observations.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

OIL_INTRADAY_MAX_AGE_SECONDS = 5 * 60  # quote timestamp, NOT freshness claim
# CNBC explicitly marks exchange-delayed futures. They can be a low-weight
# macro context for up to 15 minutes, NEVER live intraday confirmation.
OIL_DELAYED_FUTURES_MAX_AGE_SECONDS = 15 * 60


def _num(value: Any) -> float | None:
    try:
        n = float(value)
        return n if isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _date(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def _validated(row: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    if not row:
        return None
    pct, value = _num(row.get("pct")), _num(row.get("value"))
    observed = _date(row.get("observed"))
    source = str(row.get("source") or "")
    basis = str(row.get("basis") or "")
    if pct is None or value is None or value <= 0 or observed is None:
        return None
    age_s = (now - observed).total_seconds()
    if age_s < 0:
        return None

    if source.startswith("DIA RWA"):
        if (row.get("instrument_type") != "SPOT"
                or row.get("fresh") is not True
                or basis != "penutupan sebelumnya"
                or age_s > OIL_INTRADAY_MAX_AGE_SECONDS):
            return None
        cadence = "INTRADAY"
    elif source.startswith("FRED"):
        if row.get("fresh") is not True or age_s > 7 * 86400:
            return None
        cadence = "HARIAN"
    elif (source.startswith("CNBC Quote Cache · futures exchange-delayed")
          and row.get("instrument_type") == "FUTURES"
          and row.get("provider_realtime") is False
          and basis == "penutupan sebelumnya"
          and age_s <= OIL_DELAYED_FUTURES_MAX_AGE_SECONDS):
        # The vendor explicitly labels exchange-delay: score with lower
        # confidence, never as a live five-minute confirmation.
        cadence = "FUTURES_DELAYED"
    elif ((source.startswith("Yahoo Finance") or
           source.startswith("CNBC Quote Cache"))
          and row.get("fresh") is True
          and age_s <= OIL_INTRADAY_MAX_AGE_SECONDS):
        cadence = "INTRADAY"
    else:
        return None

    return {"value": value, "pct": pct, "observed": observed.isoformat(),
            "source": source, "basis": basis, "cadence": cadence}


def oil_quote_status(row: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    """Keep a delayed last quote visible, never relabel it as live."""
    row = row or {}
    date = _date(row.get("observed"))
    age = (now.astimezone(UTC) - date).total_seconds() if date else None
    source = str(row.get("source") or "")
    value, pct = _num(row.get("value")), _num(row.get("pct"))
    is_intraday = (source.startswith("DIA RWA") or
                   source.startswith("Yahoo Finance") or
                   source.startswith("CNBC Quote Cache"))
    is_daily = source.startswith("FRED")
    if not row or age is None or value is None or value <= 0:
        status = "UNAVAILABLE"
    elif age < 0:
        status = "INVALID_TIMESTAMP"
    elif source.startswith("DIA RWA"):
        if not row.get("fresh") or age > OIL_INTRADAY_MAX_AGE_SECONDS:
            status = "STALE_SPOT"
        else:
            status = "SPOT_FRESH_5M" if pct is not None else "SPOT_NO_BASELINE"
    elif pct is None:
        status = "NO_CHANGE_BASELINE"
    elif is_daily:
        status = "DAILY_CONTEXT" if age <= 48 * 3600 else "STALE_DAILY_CONTEXT"
    elif not is_intraday:
        status = "UNVERIFIED"
    elif (source.startswith("CNBC Quote Cache · futures exchange-delayed")
          and row.get("instrument_type") == "FUTURES"
          and row.get("provider_realtime") is False
          and str(row.get("basis") or "") == "penutupan sebelumnya"
          and age <= OIL_DELAYED_FUTURES_MAX_AGE_SECONDS):
        status = "DELAYED_15M_LOW_WEIGHT"
    elif row.get("fresh") is True and age <= OIL_INTRADAY_MAX_AGE_SECONDS:
        status = "FRESH_5M"
    else:
        status = "DELAYED"
    return {
        "value": value, "pct": pct,
        "observed": date.isoformat() if date else None,
        "age_minutes": round(age / 60, 1) if age is not None and age >= 0 else None,
        "status": status,
        "source": source or "UNAVAILABLE",
        "basis": str(row.get("basis") or ""),
    }


def assess_oil_macro(oil: dict[str, dict[str, Any] | None] | None, now: datetime) -> dict[str, Any]:
    """Give conditional XAU channels separately from the Treasury/DXY score."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    oil = oil or {}
    wti = _validated(oil.get("WTI"), now)
    brent = _validated(oil.get("Brent"), now)
    base = {
        "status": "BELUM LENGKAP", "trend": "UNKNOWN",
        "wti": wti, "brent": brent,
        "quotes": {
            "WTI": oil_quote_status(oil.get("WTI"), now),
            "Brent": oil_quote_status(oil.get("Brent"), now),
        },
        "xau_inflation_bias": "TIDAK DINILAI",
        "inflation_path": "Jalur Oil → inflasi → Fed → real yield belum terkonfirmasi.",
        "safe_haven_path": "Geopolitik/safe haven tidak bisa disimpulkan hanya dari harga minyak.",
        "score_influence": False,
    }
    if wti is None or brent is None:
        base["summary"] = (
            "WTI/Brent tidak lengkap, tidak sebanding, atau melampaui batas sumber "
            "(spot intraday ≤5 menit dengan baseline valid / spot harian FRED ≤48 jam); "
            "data terakhir hanya ditampilkan sebagai referensi."
        )
        return base
    if wti["cadence"] != brent["cadence"] or wti["basis"] != brent["basis"]:
        base.update(status="TIDAK SEBANDING", summary=(
            "Basis pembanding atau frekuensi feed WTI–Brent berbeda; arah gabungan tidak disimpulkan."
        ))
        return base
    if (wti["cadence"] == "HARIAN" and
            wti["observed"][:10] != brent["observed"][:10]):
        base.update(status="TIDAK SEBANDING", summary=(
            "Tanggal observasi harian WTI dan Brent tidak sama; arah gabungan tidak disimpulkan."
        ))
        return base

    # An Oil pair represents ONE macro cluster. Mixing observations more than
    # two minutes apart can make even two delayed futures incomparable.
    if wti["cadence"] != "HARIAN" and abs(
        (_date(wti["observed"]) - _date(brent["observed"])).total_seconds()
    ) > 120:
        base.update(status="TIDAK SEBANDING", summary=(
            "Timestamp WTI–Brent berbeda lebih dari 2 menit; tidak dibobotkan bersama."
        ))
        return base

    base["status"] = wti["cadence"]
    a, b = wti["pct"], brent["pct"]
    if a >= 0.25 and b >= 0.25:
        base.update(
            trend="NAIK", xau_inflation_bias="BEARISH BERSYARAT",
            summary="WTI dan Brent sama-sama naik; risiko tekanan inflasi energi meningkat.",
            inflation_path=(
                "Oil naik → risiko inflasi naik → Fed berpotensi lebih hawkish → "
                "real yield bisa naik → tekanan bearish XAU, HANYA jika yield/DXY mengonfirmasi."
            ),
            safe_haven_path=(
                "Jika kenaikan Oil dipicu gangguan pasokan/geopolitik yang terverifikasi, "
                "permintaan safe haven justru dapat mendukung XAU. Penyebabnya belum diverifikasi oleh feed Oil."
            ),
        )
    elif a <= -0.25 and b <= -0.25:
        base.update(
            trend="TURUN", xau_inflation_bias="BULLISH BERSYARAT",
            summary="WTI dan Brent sama-sama turun; tekanan inflasi energi berpotensi mereda.",
            inflation_path=(
                "Oil turun → tekanan inflasi energi berpotensi turun → Fed bisa lebih dovish → "
                "real yield bisa turun → dukungan bullish XAU, HANYA jika yield/DXY mengonfirmasi."
            ),
            safe_haven_path=(
                "Oil turun tidak membuktikan risiko geopolitik mereda; "
                "perubahan permintaan safe haven belum dapat ditentukan."
            ),
        )
    else:
        base.update(
            trend="MIXED/FLAT", xau_inflation_bias="NETRAL",
            summary="WTI dan Brent tidak bergerak searah dengan amplitudo memadai (ambang ±0,25%).",
            inflation_path=(
                "Arah energi belum konsisten; tidak ada inferensi inflasi/Fed atau arah XAU dari Oil."
            ),
        )
    return base
