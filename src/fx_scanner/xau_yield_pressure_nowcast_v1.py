"""Yield direction nowcast V1 — XAU BUY/SELL decision SUPPORT, never execution.

Only a qualitative next 15–60m *pressure hypothesis*, NOT a statistically
validated directional forecast or numerical Treasury-yield prediction.
ZN/Treasury-futures price rise suggests yield pressure down, and vice versa.
Fed Funds ZQ is an independent short-end market input, not a 10Y price feed.
A contradictory, stale, fabricated or weekend-unavailable quote forces WAIT.
"""
from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any, Mapping

CONTRACT = "RIZAN_US10Y_YIELD_PRESSURE_NOWCAST_V1_READONLY"
EXECUTION_AUTHORITY = False
MAX_QUOTE_AGE_SECONDS = 900
MAX_REFERENCE_WINDOW_SECONDS = 4 * 3600
MIN_FUTURES_MOVE_POINTS = 1.0 / 32.0  # match existing V399 ZN 0.03125-point threshold


def _dict(x: Any) -> dict:
    return dict(x) if isinstance(x, Mapping) else {}


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _utc(value: Any) -> datetime | None:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else None
    except (TypeError, ValueError, OverflowError):
        return None


def _fresh(value: Any, *, now: datetime, max_age_seconds: int = MAX_QUOTE_AGE_SECONDS) -> bool:
    at = _utc(value)
    return at is not None and 0 <= (now - at).total_seconds() <= max_age_seconds


def _zn_direction(context: Mapping | None, now: datetime) -> dict:
    """Read original quote time and price change; don't trust derived age fields."""
    row = _dict(context)
    price = _num(row.get("futures_price"))
    move = _num(row.get("futures_change_points"))
    quote_at = row.get("futures_at")
    pressure = str(row.get("futures_yield_pressure") or "")
    source = str(row.get("effective_source") or "")
    state = str(row.get("session_state") or "")
    futures_state = str(row.get("futures_state") or "")
    futures_freshness = str(row.get("futures_freshness") or "")
    # V399 can prefer the fresh cash quote, while retaining independently
    # timestamped ZN futures for corroboration. Do not discard ZN in that case.
    has_broker_attested_zn = (
        row.get("contract") == "XAU_TREASURY_SESSION_AWARE_V399"
        and row.get("execution_authority") is False
        and row.get("execution_influence") is False
    )
    live_zn = (
        has_broker_attested_zn
        and (
            (state == "GLOBEX_PROXY_ACTIVE" and source == "YAHOO_FINANCE_ZN_FRONT_PROXY")
            or (state == "CASH_FEED_ACTIVE"
                and source == "YAHOO_FINANCE_TNX_INTRADAY_PROXY"
                and futures_freshness == "FRESH")
        )
        and futures_state in {
            "TREASURY_FUTURES_DOWN_YIELD_UP_PROXY",
            "TREASURY_FUTURES_UP_YIELD_DOWN_PROXY",
            "TREASURY_FUTURES_FLAT",
        }
    )
    if (
        not live_zn
        or price is None or price <= 0 or move is None
        or abs(move) > max(10.0, price * .10)
        or not _fresh(quote_at, now=now)
    ):
        return {
            "direction": "UNKNOWN", "quality": "UNAVAILABLE",
            "reason": "ZN Treasury futures tidak tersedia atau timestamp/session tidak valid",
            "observed_at": quote_at,
        }
    # Prevent cached derived indicator from disagreeing with raw observable price change.
    if move <= -MIN_FUTURES_MOVE_POINTS and (
        pressure != "YIELD_UP_PROXY"
        or futures_state != "TREASURY_FUTURES_DOWN_YIELD_UP_PROXY"
    ):
        return {"direction": "UNKNOWN", "quality": "INCONSISTENT",
                "reason": "Arah ZN tidak sesuai perubahan futures", "observed_at": quote_at}
    if move >= MIN_FUTURES_MOVE_POINTS and (
        pressure != "YIELD_DOWN_PROXY"
        or futures_state != "TREASURY_FUTURES_UP_YIELD_DOWN_PROXY"
    ):
        return {"direction": "UNKNOWN", "quality": "INCONSISTENT",
                "reason": "Arah ZN tidak sesuai perubahan futures", "observed_at": quote_at}
    if abs(move) < MIN_FUTURES_MOVE_POINTS:
        return {
            "direction": "FLAT", "quality": "PROXY_FRESH",
            "reason": "ZN bergerak kecil; tidak cukup sebagai bias yield",
            "move_points": move, "observed_at": quote_at,
        }
    return {
        "direction": "UP" if move < 0 else "DOWN",
        "quality": "PROXY_FRESH",
        "reason": (
            "ZN futures turun sehingga pressure US10Y cenderung naik"
            if move < 0 else "ZN futures naik sehingga pressure US10Y cenderung turun"
        ),
        "move_points": move, "source": "YAHOO_FINANCE_ZN_FRONT_PROXY",
        "observed_at": quote_at,
    }


def _zq_direction(fed: Mapping | None, now: datetime) -> dict:
    r = _dict(fed)
    source = str(r.get("source") or "")
    at, ref_at = _utc(r.get("current_at")), _utc(r.get("reference_at"))
    latest, reference = _num(r.get("current")), _num(r.get("reference"))
    change = _num(r.get("implied_rate_change_bps"))
    if (
        source != "YAHOO_FINANCE_ZQ_FRONT_PROXY"
        or r.get("available") is not True
        or at is None or ref_at is None
        or not _fresh(at, now=now)
        or not 300 <= (at - ref_at).total_seconds() <= MAX_REFERENCE_WINDOW_SECONDS
        or latest is None or reference is None or change is None
        or not 80 <= latest <= 105 or not 80 <= reference <= 105
        or abs((reference - latest) * 100 - change) > .5
    ):
        return {
            "direction": "UNKNOWN", "quality": "UNAVAILABLE",
            "reason": "Fed Funds futures ZQ tidak tersedia/valid pada timestamp asli",
            "observed_at": r.get("current_at"),
        }
    if abs(change) < 1.:
        direction = "FLAT"
    else:
        direction = "UP" if change > 0 else "DOWN"
    return {
        "direction": direction, "quality": "PROXY_FRESH",
        "reason": "Perubahan ekspektasi Fed Funds %+.2f bp" % change,
        "observed_at": at.isoformat(), "change_bps": change,
    }


def evaluate_yield_pressure(
    evaluation: Mapping | None, *, now: datetime,
    fed_funds: Mapping | None = None,
) -> dict:
    """Two horizons remain distinct: DAILY official context vs 15–60m proxy.

    Only fresh, consistent ZN futures is enough to publish a tentative directional
    nowcast; a concordant ZQ futures change upgrades to CONFIRMED_PROXY but
    is not a third independent lead for USD (USD Lead already uses ZQ).
    """
    if now.tzinfo is None:
        raise ValueError("NOW_MUST_HAVE_TIMEZONE")
    now = now.astimezone(UTC)
    e = _dict(evaluation)
    futures_context = _dict(e.get("intraday_yield_context"))
    zn = _zn_direction(futures_context, now)
    fed = _zq_direction(fed_funds if fed_funds is not None else e.get("fed_funds_futures"), now)
    zn_dir, fed_dir = zn["direction"], fed["direction"]
    if zn_dir not in ("UP", "DOWN"):
        state, direction, explanation = "WAIT_SOURCE", "WAIT", zn["reason"]
    elif fed_dir in ("UP", "DOWN") and fed_dir != zn_dir:
        state, direction, explanation = (
            "WAIT_CONFLICT", "WAIT",
            "ZN futures dan ZQ Fed funds bergerak berbeda; tidak ada konfirmasi",
        )
    elif fed_dir == zn_dir:
        state, direction, explanation = (
            "CONCORDANT_PROXY", zn_dir,
            "ZN Treasury futures dan ZQ Fed funds searah; belum divalidasi sebagai forecast",
        )
    else:
        state, direction, explanation = (
            "ZN_PROXY_ONLY", zn_dir,
            "Tekanan arah dari ZN saja; Fed funds belum mengonfirmasi",
        )
    return {
        "contract": CONTRACT, "as_of_utc": now.isoformat(),
        "horizon_label": "NEXT_15_TO_60_MIN_EXPLORATORY",
        "yield_direction": direction, "state": state,
        "concordance": fed_dir == zn_dir and zn_dir in ("UP", "DOWN"),
        "zn": zn, "zq": fed,
        "explanation": explanation,
        "daily_yield_is_forecast": False,
        "probability_calibrated": False, "out_of_sample_validated": False,
        "predicted_numeric_yield_percent": None,
        "execution_authority": False, "execution_influence": False,
    }
