"""Read-only pre-release expectations. No actuals, fitted probabilities or orders.

Consensus versus previous is a change expectation, never an actual surprise.
Freshness is checked again at read time, independently of publication age.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

CONTRACT = "RIZAN_PRE_NEWS_EXPECTATION_V1"
EVENT_WORKER = "ctrader_demo_xau_event_risk_v192"
MACRO_WORKER = "ctrader_demo_xau_macro_attribution_v357"
DIRECT = {"CPI", "PPI", "EMPLOYMENT", "NFP", "WAGES", "ECI", "JOLTS", "FOMC"}
INVERSE = {"UNEMPLOYMENT_RATE"}
SUPPORTED = DIRECT | INVERSE


def timestamp(value: Any) -> datetime | None:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else None
    except (ValueError, TypeError):
        return None


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if isfinite(n) else None
    except (ValueError, TypeError):
        return None


def fresh(at: Any, now: datetime, limit: float) -> bool:
    dt = timestamp(at)
    return dt is not None and 0 <= (now - dt).total_seconds() <= limit


def _scenarios(category: str) -> list[dict[str, str]]:
    inverse = category in INVERSE
    return [
        {"Rilis": "Di atas konsensus", "Implikasi awal XAU": "Cenderung mendukung" if inverse else "Cenderung menekan"},
        {"Rilis": "Sesuai konsensus", "Implikasi awal XAU": "Tergantung revisi, komponen dan positioning"},
        {"Rilis": "Di bawah konsensus", "Implikasi awal XAU": "Cenderung menekan" if inverse else "Cenderung mendukung"},
    ]


def evaluate_pre_news(snapshot: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Consume full or compact V192/V398 heartbeat payloads without mutation."""
    current = timestamp(now)
    if current is None:
        raise ValueError("now must be timezone-aware")
    by_worker: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("heartbeats") or []:
        key = row.get("worker_name")
        at = timestamp(row.get("observed_at"))
        previous = timestamp(by_worker.get(key, {}).get("observed_at"))
        if at is not None and (previous is None or at > previous):
            by_worker[key] = row
    event_hb = by_worker.get(EVENT_WORKER, {})
    macro_hb = by_worker.get(MACRO_WORKER, {})
    event_details = event_hb.get("details") or {}
    risk = event_details.get("risk") or event_details.get("dashboard_projection") or {}
    macro_details = macro_hb.get("details") or {}
    macro = macro_details.get("evaluation") or macro_details.get("dashboard_projection") or {}
    reasons: list[str] = []
    if not fresh(event_hb.get("observed_at"), current, 600) or not event_hb.get("healthy"):
        reasons.append("CALENDAR_STALE_MISSING_OR_UNHEALTHY")
    if not fresh(macro_hb.get("observed_at"), current, 600) or not macro_hb.get("healthy"):
        reasons.append("MACRO_STALE_MISSING_OR_UNHEALTHY")
    events = [dict(e) for e in risk.get("upcoming_events") or []]
    if risk.get("focal_event"):
        events.append(dict(risk["focal_event"]))
    upcoming = []
    seen = set()
    for event in events:
        at = timestamp(event.get("scheduled_at"))
        key = (event.get("title"), at)
        if at is None or at < current or event.get("category") not in SUPPORTED or key in seen:
            continue
        if event.get("currency", "USD") != "USD":
            continue
        seen.add(key)
        upcoming.append((at, event))
    upcoming.sort(key=lambda item: (item[0], str(item[1].get("title"))))
    result: dict[str, Any] = {
        "contract": CONTRACT, "observed_at": current.isoformat(),
        "state": "DATA INCOMPLETE", "expectation": "UNAVAILABLE",
        "xau_bias": "UNAVAILABLE", "conviction": "UNAVAILABLE",
        "probability": None, "calibration": "UNVALIDATED_HEURISTIC",
        "execution_authority": False, "execution_influence": False,
        "news_gate": str(risk.get("state") or "UNAVAILABLE"),
        "news_gate_action": str(risk.get("action") or "UNAVAILABLE"),
        "event": None, "minutes_to_event": None, "scenarios": [],
        "calendar_observed_at": event_hb.get("observed_at"),
        "macro_observed_at": macro_hb.get("observed_at"),
        "reasons": reasons, "components": [], "event_cluster": [],
    }
    if "CALENDAR_STALE_MISSING_OR_UNHEALTHY" in reasons:
        result["news_gate"] = "UNAVAILABLE_STALE_CALENDAR"
        result["news_gate_action"] = "UNAVAILABLE"
    if not upcoming:
        reasons.append("NO_UPCOMING_SUPPORTED_EVENT_IN_CALENDAR")
        return result
    at, event = upcoming[0]
    minutes = (at - current).total_seconds() / 60
    result.update(event=event, minutes_to_event=round(minutes, 1),
                  event_time_wib=at.astimezone(ZoneInfo("Asia/Jakarta")).isoformat(),
                  scenarios=_scenarios(event["category"]))
    # Evaluate all simultaneous components, e.g. headline/core CPI and NFP/wages.
    cluster = [e for t, e in upcoming if t == at]
    tilts = []
    for e in cluster:
        forecast, previous = number(e.get("forecast")), number(e.get("previous"))
        tilt = None
        if forecast is not None and previous is not None:
            tolerance = max(abs(previous) * 0.01, 1e-9)
            tilt = 0 if abs(forecast - previous) <= tolerance else (1 if forecast > previous else -1)
            if e["category"] in INVERSE:
                tilt *= -1
        else:
            reasons.append("CONSENSUS_OR_PREVIOUS_MISSING:" + str(e.get("title")))
        if e["category"] == "FOMC":
            # Even an unchanged target rate cannot describe statement/press conference.
            reasons.append("FOMC_LANGUAGE_AND_RATE_PATH_UNMODELED")
        if tilt is not None:
            tilts.append(tilt)
        result["event_cluster"].append({"title": e.get("title"), "category": e["category"],
                                        "forecast": forecast, "previous": previous, "hawkish_tilt": tilt})
    if tilts and len(tilts) == len(cluster):
        if 1 in tilts and -1 in tilts:
            expectation = "MIXED"
        elif 1 in tilts:
            expectation = "HOT-RISK"
        elif -1 in tilts:
            expectation = "COOL"
        else:
            expectation = "INLINE"
        result["expectation"] = expectation
    components = macro.get("components") or {}
    cross = macro_details.get("cross_asset") or {}
    intraday_dxy = macro.get("dxy_intraday") or macro_details.get("dxy_intraday") or {}
    for name in ("DXY", "US2Y", "US10Y", "REAL_YIELD_10Y"):
        row = intraday_dxy if name == "DXY" else (cross.get(name) or components.get(name) or {})
        intraday = name == "DXY"
        observed = row.get("current_at") if intraday else row.get("observed_at")
        # Daily FRED can span weekends/holidays, but is explicitly a daily regime.
        dxy_limit = 900 if str(row.get("source") or "").startswith("CTRADER_") else 1800
        valid = (fresh(observed, current, dxy_limit if intraday else 7 * 86400)
                 and row.get("freshness") == "FRESH")
        delta = number(row.get("net_pct") if intraday else row.get("delta"))
        valid = valid and delta is not None
        if not valid:
            reasons.append(name + "_STALE_OR_MISSING")
            if name == "DXY" and row.get("source_status") == "RATE_LIMITED":
                reasons.append("DXY_PROVIDER_RATE_LIMITED")
        threshold = 0.05 if intraday else 2.0
        pressure = None if not valid else (1 if delta >= threshold else -1 if delta <= -threshold else 0)
        result["components"].append({"name": name, "fresh": valid, "observed_at": observed,
                                      "current": number(row.get("current")),
                                      "basis": row.get("basis"),
                                      "delta": delta, "unit": "%" if intraday else "bps",
                                      "frequency": "INTRADAY" if intraday else "DAILY_REGIME",
                                      "source": row.get("source") or row.get("provider"),
                                      "source_status": row.get("source_status") or row.get("freshness"),
                                      "hawkish_pressure": pressure})
    if reasons:
        result["expectation"] = "UNAVAILABLE"
        return result
    result["state"] = "PRE_NEWS"
    pressures = [r["hawkish_pressure"] for r in result["components"]]
    expectation = result["expectation"]
    expected = 1 if expectation == "HOT-RISK" else -1 if expectation == "COOL" else 0
    conflict = (1 in pressures and -1 in pressures) or (expected and -expected in pressures)
    direction = expected if expected and not conflict else 0
    result["xau_bias"] = "BEARISH_XAU" if direction == 1 else "BULLISH_XAU" if direction == -1 else "NEUTRAL_MIXED"
    # This label describes agreement of evidence, never a calibrated win rate.
    result["conviction"] = "LOW" if not direction else "MEDIUM" if pressures.count(direction) >= 3 else "LOW"
    if conflict:
        reasons.append("CONSENSUS_MACRO_DIVERGENCE")
    result["next_step"] = "H1 bias → M15 struktur/reversal → M5 timing; cek revisi dan respons yield/DXY setelah rilis."
    return result
