"""Non-executable daily regime context when real-time macro evidence is incomplete.

Never relabel a previous-session DXY or official daily yield as intraday/live.
Daily regime is a separate, intentionally reduced-authority score.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

YIELD_WEIGHTS = {"REAL_YIELD_10Y": 0.50, "US2Y": 0.30, "US10Y": 0.20}
FRED_YIELD_SERIES = {
    "US2Y": "DGS2", "US10Y": "DGS10", "REAL_YIELD_10Y": "DFII10"
}
MAX_YIELD_AGE_HOURS = 120
MAX_DXY_CLOSE_AGE_HOURS = 96


def _number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _dt(value: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def _age(value: Any, now: datetime) -> float | None:
    stamp = _dt(value)
    return (now - stamp).total_seconds() / 3600 if stamp else None


def fred_daily_yield_row(
    symbol: str, observations: list[tuple[str, float]] | None,
    *, now: datetime,
) -> dict[str, Any] | None:
    """Build an official daily change in BPS from two dated FRED observations."""
    if symbol not in FRED_YIELD_SERIES or now.tzinfo is None:
        return None
    now = now.astimezone(UTC)
    valid: dict[str, float] = {}
    for at, raw in observations or []:
        d, val = _dt(at), _number(raw)
        if d is not None and 0 < val < 30 and d <= now:
            valid[d.date().isoformat()] = val
    if len(valid) < 2:
        return None
    series = sorted(valid.items())
    (prev_at, prev), (at, current) = series[-2:]
    stamp = _dt(at)
    age = _age(at, now)
    if age is None or not 0 <= age <= MAX_YIELD_AGE_HOURS:
        return None
    return {
        "series": FRED_YIELD_SERIES[symbol],
        "provider": "FRED_OFFICIAL_DAILY",
        "freshness": "FRESH",
        "observed_at": stamp.isoformat(),
        "previous_observed_at": _dt(prev_at).isoformat(),
        "current": current, "previous": prev,
        "delta": round((current - prev) * 100, 6), "delta_unit": "BPS",
        "execution_authority": False, "execution_influence": False,
    }


def assess_daily_regime(
    *, yields: dict[str, dict[str, Any]] | None,
    dxy_last: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    """Separate daily Treasury–DXY backdrop, NOT an intraday entry signal.

    DXY close up to 96h old allows weekend/after-hours context. Official daily
    yields can be <=5 days old. If one source is absent, show partial coverage
    and missing factors, not an invented complete score.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    yields, dxy_last = yields or {}, dxy_last or {}
    available = 0.0
    signed_sum = 0.0
    n_yields = 0
    missing: list[str] = []
    components = []
    yield_times = []
    for name, weight in YIELD_WEIGHTS.items():
        item = yields.get(name) or {}
        at, delta = item.get("observed_at"), _number(item.get("delta"))
        age = _age(at, now)
        valid = (item.get("freshness") == "FRESH"
                 and delta is not None and age is not None
                 and 0 <= age <= MAX_YIELD_AGE_HOURS)
        if valid:
            n_yields += 1
            available += weight
            yield_times.append(_dt(at))
            direction = -1 if delta >= 1.0 else 1 if delta <= -1.0 else 0
            signed_sum += weight * direction
        else:
            missing.append(name)
        components.append({
            "name": name, "valid": valid, "timestamp": at,
            "provider": item.get("provider"), "delta_bps": delta,
        })
    treasury_valid = n_yields >= 2 and available >= 0.49
    treasury_score = signed_sum / available if treasury_valid else None

    pct = _number(dxy_last.get("pct"))
    age = _age(dxy_last.get("observed"), now)
    close_basis = str(dxy_last.get("basis") or "") == "penutupan sebelumnya"
    source = str(dxy_last.get("source") or "")
    source_ok = (source.startswith("CNBC Quote Cache")
                 or source.startswith("Yahoo Finance"))
    dxy_valid = (pct is not None and age is not None
                 and 0 <= age <= MAX_DXY_CLOSE_AGE_HOURS
                 and close_basis and source_ok)
    if dxy_valid and yield_times:
        # Weekend or publication gaps tolerated, but last DXY and Treasury
        # observations must refer to broadly the same macro interval.
        dxy_at = _dt(dxy_last["observed"])
        if min(abs((dxy_at - stamp).total_seconds())
               for stamp in yield_times) > 72 * 3600:
            dxy_valid = False
    if not dxy_valid:
        missing.append("DXY LAST SESSION <=96h (CNBC/Yahoo; prior close)")
    dollar_direction = (-1 if pct >= 0.05 else
                        1 if pct <= -0.05 else 0) if dxy_valid else None
    coverage = round(100 * (0.55 * available + 0.45 * int(dxy_valid)))
    if treasury_valid and dxy_valid:
        score = round(100 * (0.55 * treasury_score + 0.45 * dollar_direction))
        bias = ("BULLISH REGIME" if score >= 25 else
                "BEARISH REGIME" if score <= -25 else "NETRAL / MIXED REGIME")
        status = "REGIME_HARIAN_TERSEDIA"
    else:
        score, bias, status = None, "REGIME BELUM LENGKAP", "WAIT_DAILY_DATA"
    return {
        "status": status, "bias": bias, "score": score,
        "coverage_pct": coverage, "treasury_direction": treasury_score,
        "dxy_direction": dollar_direction, "components": components,
        "dxy_timestamp": dxy_last.get("observed"),
        "dxy_source": source, "dxy_pct": pct,
        "missing": missing,
        "horizon": "regime observasi harian / penutupan sesi terakhir, bukan intraday",
        "execution_authority": False, "execution_influence": False,
        "as_of": now.isoformat(),
    }
