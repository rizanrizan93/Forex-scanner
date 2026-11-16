"""RIZAN USD Lead V1 — causal, explainable read-only USD→XAU research.

Independent evidence is kept separate:
- Fed Funds futures price repricing = intraday expectations proxy, NOT FedWatch.
- US2Y + real-yield official change = DAILY context, NOT live yield quotes.
- US-DE 2Y relative daily change = independent Bund quote, NOT an intraday feed.
- DXY secondary quote = CONFIRMATION, not a leading variable.
- XAU technical and broker risk must be validated independently.

This module contains no order/broker/bridge/network/storage code.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any, Mapping

CONTRACT = "RIZAN_USD_LEAD_V1_RESEARCH_ONLY"
EXECUTION_AUTHORITY = False
CHECK_STATUS = frozenset({"PASS", "FAIL", "UNKNOWN"})
FUTURES_SOURCES = frozenset({"YAHOO_FINANCE_ZQ_FRONT_PROXY"})
DXY_SOURCES = frozenset({
    "YAHOO_FINANCE_ICE_DXY_PROXY",
    "CTRADER_DXY_CFD_PROXY",
    "CTRADER_SYNTHETIC_USDX_6FX",
})
SPREAD_CONTRACT = "RIZAN_US_DE2Y_OFFICIAL_DAILY_V1"


def _obj(v: Any) -> dict:
    return dict(v) if isinstance(v, Mapping) else {}


def _n(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
        return x if isfinite(x) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _dt(v: Any) -> datetime | None:
    try:
        x = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return x.astimezone(UTC) if x.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def _valid_at(value: Any, now: datetime, max_age_s: int) -> bool:
    at = _dt(value)
    return at is not None and 0 <= (now - at).total_seconds() <= max_age_s


def _row(key: str, label: str, state: str, detail: str,
         *, category: str, observed_at: str | None = None) -> dict:
    if state not in CHECK_STATUS:
        raise ValueError("UNKNOWN_USD_LEAD_STATUS")
    return {"key": key, "label": label, "state": state, "detail": detail,
            "category": category, "observed_at": observed_at}


def _delta_check(
    component: Mapping | None, *, name: str, label: str, side: str,
    now: datetime, threshold: float = 2.0,
) -> dict:
    raw = _obj(component)
    current = _n(raw.get("current"))
    prev = _n(raw.get("previous"))
    delta = _n(raw.get("delta"))
    at = raw.get("observed_at")
    before = raw.get("previous_observed_at")
    if (raw.get("freshness") != "FRESH"
            or str(raw.get("release_state")) != "CURRENT_PUBLISHED"
            or not _valid_at(at, now, 5*86400)
            or _dt(before) is None
            or _dt(before) >= _dt(at)
            or not _valid_at(before, now, 8*86400)
            or None in (current, prev, delta)
            or abs((current - prev)*100 - delta) > .6):
        return _row(name, label, "UNKNOWN",
                    "Yield resmi harian belum terpublikasi/terverifikasi atau telah kedaluwarsa",
                    category="DAILY")
    # Policy: official yields are context on DAY-to-DAY changes, not intraday nowcasts.
    direction = 1 if side == "UP" else -1
    result = delta * direction
    state = "PASS" if result >= threshold else "FAIL"
    return _row(name, label, state,
                "Perubahan harian %+.1f bp (ambang %s%.1f bp); observasi %s"
                % (delta, "+" if direction > 0 else "-", threshold, str(at)),
                category="DAILY", observed_at=str(at))


def _fed_check(raw: Mapping | None, side: str, now: datetime) -> dict:
    q = _obj(raw)
    delta = _n(q.get("implied_rate_change_bps"))
    current = _n(q.get("current"))
    reference = _n(q.get("reference"))
    at = q.get("current_at")
    ref_at = q.get("reference_at")
    a, b = _dt(at), _dt(ref_at)
    # A cached numeric "fed_repricing_proxy" derived from US2Y is NOT ZQ futures.
    if (q.get("source") not in FUTURES_SOURCES
            or q.get("available") is not True
            or not _valid_at(at, now, 900)
            or a is None or b is None
            or not 300 <= (a-b).total_seconds() <= 4*3600
            or None in (delta, current, reference)
            or abs((reference-current)*100-delta) > .5):
        return _row("fed", "Ekspektasi Fed — futures ZQ",
                    "UNKNOWN",
                    "Data ZQ=F dengan timestamp asli belum valid; US2Y bukan pengganti FedWatch",
                    category="LEAD")
    signed = delta if side == "UP" else -delta
    return _row("fed", "Ekspektasi Fed — futures ZQ",
                "PASS" if signed >= 1 else "FAIL",
                "Perubahan implied Fed funds %+.2f bp dalam %.0f menit (proxy, bukan CME FedWatch)"
                % (delta, (a-b).total_seconds()/60),
                category="LEAD", observed_at=str(at))


def _spread_check(raw: Mapping | None, side: str, now: datetime) -> dict:
    r = _obj(raw)
    vals = [_n(r.get(k)) for k in (
        "us2y_current", "us2y_previous", "de2y_current", "de2y_previous",
    )]
    observed, prev = _dt(r.get("observed_at")), _dt(r.get("previous_observed_at"))
    if (r.get("contract") != SPREAD_CONTRACT or r.get("source") !=
            "US_TREASURY_AND_BUNDESBANK_OFFICIAL_DAILY"
            or r.get("execution_authority") is not False
            or r.get("execution_influence") is not False
            or None in vals or observed is None or prev is None or prev >= observed
            or not _valid_at(observed, now, 5*86400)):
        return _row("spread", "Selisih yield US2Y − DE2Y",
                    "UNKNOWN",
                    "Perlu Treasury US2Y dan Bundesbank DE2Y pada dua tanggal publikasi yang cocok",
                    category="LEAD_DAILY")
    us, us_prev, de, de_prev = vals
    spread = (us-de)*100
    spread_prev = (us_prev-de_prev)*100
    shift = spread-spread_prev
    signed = shift if side == "UP" else -shift
    return _row("spread", "Selisih yield US2Y − DE2Y",
                "PASS" if signed >= 2 else "FAIL",
                "Spread %+.1f bp; perubahan harian %+.1f bp; sumber Treasury+Bundesbank"
                % (spread, shift),
                category="LEAD_DAILY", observed_at=observed.isoformat())


def _dxy_check(raw: Mapping | None, side: str, now: datetime) -> dict:
    r = _obj(raw)
    a, b = _dt(r.get("current_at")), _dt(r.get("reference_at"))
    pct = _n(r.get("net_pct"))
    cur, prev = _n(r.get("current")), _n(r.get("reference"))
    if (r.get("source") not in DXY_SOURCES
            or r.get("available") is not True
            or not _valid_at(r.get("current_at"), now, 900)
            or a is None or b is None
            or not 300 <= (a-b).total_seconds() <= 4*3600
            or None in (pct, cur, prev) or prev <= 0
            or abs((cur/prev-1)*100-pct) > .03):
        return _row("dxy", "Konfirmasi DXY/USDX",
                    "UNKNOWN", "Kutipan DXY asli belum segar/valid; proxy tidak disamakan dengan ICE resmi",
                    category="CONFIRMATION")
    signed = pct if side == "UP" else -pct
    return _row("dxy", "Konfirmasi DXY/USDX",
                "PASS" if signed >= .05 else "FAIL",
                "DXY proxy %+.3f%% dalam %.0f menit (%s)"
                % (pct, (a-b).total_seconds()/60, r["source"]),
                category="CONFIRMATION", observed_at=str(r.get("current_at")))


def _news_check(event_quality: Mapping | None, side: str, now: datetime) -> dict:
    q = _obj(event_quality)
    state = q.get("state")
    at = q.get("event_time")
    if not _valid_at(at, now, 3600):
        return _row("news", "Actual vs forecast — berita AS", "UNKNOWN",
                    "Tidak ada actual terverifikasi dalam 60 menit; bukan alasan untuk entry",
                    category="OPTIONAL")
    if state not in {"VERIFIED_HOT", "VERIFIED_COOL"}:
        return _row("news", "Actual vs forecast — berita AS", "UNKNOWN",
                    "Berita masih campuran atau belum diverifikasi independen",
                    category="OPTIONAL")
    expected = "VERIFIED_HOT" if side == "UP" else "VERIFIED_COOL"
    return _row("news", "Actual vs forecast — berita AS",
                "PASS" if state == expected else "FAIL",
                "Rilis actual terverifikasi: " + state,
                category="OPTIONAL", observed_at=str(at))


def _xau_check(checklist: Mapping | None, side: str) -> dict:
    d = _obj(checklist)
    x = _obj(d.get("SELL" if side == "UP" else "BUY"))
    items = {v.get("key"): v for v in (x.get("items") or []) if isinstance(v, Mapping)}
    keys = ("h1", "m15", "m5", "v404")
    if not all(k in items for k in keys):
        return _row("xau", "Struktur XAU H1/M15/M5", "UNKNOWN",
                    "Checklist teknikal XAU belum terverifikasi", category="XAU")
    states = [items[k].get("state") for k in keys]
    if "UNKNOWN" in states:
        return _row("xau", "Struktur XAU H1/M15/M5", "UNKNOWN",
                    "Terdapat candle/struktur XAU yang tidak segar atau tidak valid",
                    category="XAU")
    return _row("xau", "Struktur XAU H1/M15/M5",
                "PASS" if all(x == "PASS" for x in states) else "FAIL",
                "H1 EMA, ADX/DI M15, BOS/MSS M5, dan zona V404 "
                + ("selaras" if all(x == "PASS" for x in states) else "belum selaras"),
                category="XAU")


def evaluate_usd_lead(
    evaluation: Mapping | None, *, now: datetime,
    spread: Mapping | None = None, xau_checklist: Mapping | None = None,
) -> dict:
    """Research watch status only; never infer intraday USD probability from daily FRED."""
    if now.tzinfo is None:
        raise ValueError("NOW_REQUIRES_TIMEZONE")
    now = now.astimezone(UTC)
    e = _obj(evaluation)
    components = _obj(e.get("components"))
    q = _obj(e.get("attribution_quality"))
    rowsets = {}
    for side in ("UP", "DOWN"):
        rows = [
            _fed_check(e.get("fed_funds_futures"), side, now),
            _delta_check(components.get("US2Y"), name="us2y",
                         label="US Treasury 2Y (harian)", side=side, now=now),
            _spread_check(spread, side, now),
            _dxy_check(e.get("dxy_intraday"), side, now),
            _delta_check(components.get("REAL_YIELD_10Y"), name="real",
                         label="Real yield AS 10Y (harian)", side=side, now=now),
            _news_check(q.get("event_quality"), side, now),
            _xau_check(xau_checklist, side),
        ]
        m = {v["key"]: v["state"] for v in rows}
        known_leading = sum(m[key] == "PASS" for key in ("fed", "us2y", "spread"))
        counter = sum(m[key] == "FAIL" for key in ("fed", "us2y", "spread"))
        # DXY confirmation is NOT counted as a lead. Optional news never
        # creates a lead without independent monetary-policy/rates evidence.
        # The daily US2Y change and US-DE spread share the SAME US2Y leg.
        # Do not misrepresent them as independent forecasting confirmations.
        macro_watch = (
            m["fed"] == "PASS"
            and (m["us2y"] == "PASS" or m["spread"] == "PASS")
            and counter == 0 and m["dxy"] == "PASS"
        )
        rates_only = (
            not macro_watch and m["fed"] == "UNKNOWN"
            and m["us2y"] == "PASS" and m["spread"] == "PASS"
            and m["dxy"] == "PASS"
        )
        full = macro_watch and m["real"] == "PASS" and m["xau"] == "PASS"
        if full:
            state = "XAU_SELL_SHADOW_WATCH" if side == "UP" else "XAU_BUY_SHADOW_WATCH"
        elif macro_watch:
            state = "USD_DIRECTION_WATCH_ONLY"
        elif rates_only:
            state = "USD_DAILY_RATES_WATCH_ONLY"
        else:
            state = "WAIT"
        rowsets[side] = {
            "rows": rows, "passed": sum(r["state"] == "PASS" for r in rows),
            "failed": sum(r["state"] == "FAIL" for r in rows),
            "unknown": sum(r["state"] == "UNKNOWN" for r in rows),
            "leading_votes": known_leading, "leading_contradictions": counter,
            "status": state, "xau_execution_permitted": False,
        }
    return {
        "contract": CONTRACT, "as_of_utc": now.isoformat(),
        "usd_up": rowsets["UP"], "usd_down": rowsets["DOWN"],
        "usd_direction": (
            "UP_WATCH" if rowsets["UP"]["status"] != "WAIT" else
            "DOWN_WATCH" if rowsets["DOWN"]["status"] != "WAIT" else "WAIT"
        ),
        "execution_authority": False, "execution_influence": False,
        "probability_calibrated": False, "historical_oos_validated": False,
        "risk_caution": (
            "Strong USD does not guarantee XAU decline: risk-off may lift both; "
            "broker minimum-lot and actual equity still govern XAU feasibility."
        ),
    }
