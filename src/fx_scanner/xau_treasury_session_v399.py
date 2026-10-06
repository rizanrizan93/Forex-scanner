from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Iterable, Mapping

CONTRACT = "XAU_TREASURY_SESSION_AWARE_V399"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _window_rows(
    points: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    window_minutes: float,
) -> list[tuple[datetime, float]]:
    current = now.astimezone(UTC)
    rows: list[tuple[datetime, float]] = []
    for raw in points:
        row = dict(raw or {})
        at = _dt(row.get("observed_at"))
        value = _number(row.get("value"))
        if at is None or value is None or at > current:
            continue
        rows.append((at, value))
    rows.sort(key=lambda row: row[0])
    if not rows:
        return []
    cutoff = current - timedelta(minutes=max(5.0, float(window_minutes)))
    window = [(at, value) for at, value in rows if at >= cutoff]
    return window or rows[-1:]


def evaluate_treasury_futures_pressure(
    points: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    max_age_seconds: float = 1200.0,
    window_minutes: float = 120.0,
    flat_threshold_points: float = 0.03125,
) -> dict[str, Any]:
    """Use 10Y Treasury Note futures price as an overnight yield-direction proxy.

    ZN price and Treasury yields move inversely. This intentionally classifies
    direction only; it does not convert a futures price move into synthetic
    basis points and never has execution authority.
    """
    current = now.astimezone(UTC)
    rows = _window_rows(points, now=current, window_minutes=window_minutes)
    if not rows:
        return {
            "available": False,
            "freshness": "MISSING",
            "state": "TREASURY_FUTURES_MISSING",
            "gold_implication": "UNAVAILABLE",
            "source": "YAHOO_FINANCE_ZN_FRONT_PROXY",
            "execution_authority": False,
            "execution_influence": False,
        }

    reference_at, reference = rows[0]
    latest_at, latest = rows[-1]
    age_seconds = max(0.0, (current - latest_at).total_seconds())
    change_points = latest - reference
    change_pct = 0.0 if reference == 0 else (latest / reference - 1.0) * 100.0
    threshold = abs(float(flat_threshold_points))
    stale = age_seconds > float(max_age_seconds)

    if stale:
        state = "TREASURY_FUTURES_STALE"
        implication = "UNAVAILABLE"
        available = False
        freshness = "STALE"
        yield_pressure = "UNAVAILABLE"
    elif change_points <= -threshold:
        state = "TREASURY_FUTURES_DOWN_YIELD_UP_PROXY"
        implication = "GOLD_HEADWIND"
        available = True
        freshness = "FRESH"
        yield_pressure = "YIELD_UP_PROXY"
    elif change_points >= threshold:
        state = "TREASURY_FUTURES_UP_YIELD_DOWN_PROXY"
        implication = "GOLD_SUPPORT"
        available = True
        freshness = "FRESH"
        yield_pressure = "YIELD_DOWN_PROXY"
    else:
        state = "TREASURY_FUTURES_FLAT"
        implication = "MIXED"
        available = True
        freshness = "FRESH"
        yield_pressure = "YIELD_FLAT_PROXY"

    return {
        "contract": CONTRACT,
        "available": available,
        "freshness": freshness,
        "state": state,
        "yield_pressure": yield_pressure,
        "gold_implication": implication,
        "current": latest,
        "current_at": latest_at.isoformat(),
        "reference": reference,
        "reference_at": reference_at.isoformat(),
        "change_points": change_points,
        "change_pct": change_pct,
        "window_minutes": float(window_minutes),
        "age_seconds": age_seconds,
        "freshness_limit_seconds": float(max_age_seconds),
        "source": "YAHOO_FINANCE_ZN_FRONT_PROXY",
        "source_note": (
            "ZN=F is a secondary/delayed Yahoo Finance proxy for CME 10-Year U.S. "
            "Treasury Note futures. Futures price is inverse to yield pressure. "
            "It is used only when the cash/index yield feed is not fresh."
        ),
        "execution_authority": False,
        "execution_influence": False,
    }


def resolve_us10y_session_context(
    *,
    cash_yield: Mapping[str, Any] | None,
    treasury_futures: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve cash US10Y versus extended-hours Treasury futures without faking freshness.

    A stale ^TNX value remains visible as LAST VALID cash yield. If ZN futures are
    fresh, ZN supplies only the live direction/timing implication. This prevents
    a last valid cash yield such as 5.311% from being mislabeled as live while
    still giving the macro layer an overnight Treasury-pressure signal.
    """
    cash = dict(cash_yield or {})
    fut = dict(treasury_futures or {})
    cash_available = bool(cash.get("available"))
    futures_available = bool(fut.get("available"))
    cash_last = _number(cash.get("current"))
    cash_has_last = cash_last is not None

    base = {
        "contract": CONTRACT,
        "cash_state": cash.get("state") or "UNAVAILABLE",
        "cash_freshness": cash.get("freshness") or ("FRESH" if cash_available else "STALE" if cash_has_last else "MISSING"),
        "last_cash_yield": cash_last,
        "last_cash_at": cash.get("current_at"),
        "last_cash_age_seconds": cash.get("age_seconds"),
        "futures_state": fut.get("state") or "UNAVAILABLE",
        "futures_freshness": fut.get("freshness") or ("FRESH" if futures_available else "MISSING"),
        "futures_price": fut.get("current"),
        "futures_at": fut.get("current_at"),
        "futures_change_points": fut.get("change_points"),
        "futures_change_pct": fut.get("change_pct"),
        "futures_yield_pressure": fut.get("yield_pressure"),
        "execution_authority": False,
        "execution_influence": False,
    }

    if cash_available:
        out = {
            **cash,
            **base,
            "available": True,
            "freshness": "FRESH",
            "state": "US10Y_CASH_LIVE",
            "session_state": "CASH_FEED_ACTIVE",
            "effective_source": "YAHOO_FINANCE_TNX_INTRADAY_PROXY",
            "source": "YAHOO_FINANCE_TNX_INTRADAY_PROXY",
            "source_note": (
                "Cash/index US10Y proxy is fresh; it remains the preferred intraday yield context. "
                "Treasury futures are retained as secondary corroboration only."
            ),
        }
        if cash.get("post_event_diagnostic") is not None:
            out["post_event_diagnostic"] = cash.get("post_event_diagnostic")
        return out

    if futures_available:
        state = (
            "US10Y_CASH_LAST_VALID_FUTURES_ACTIVE"
            if cash_has_last
            else "US10Y_FUTURES_ONLY_ACTIVE"
        )
        return {
            **base,
            "available": True,
            "freshness": "PROXY_FRESH",
            "state": state,
            "session_state": "GLOBEX_PROXY_ACTIVE",
            "gold_implication": fut.get("gold_implication") or "MIXED",
            "current": cash_last,
            "current_at": cash.get("current_at"),
            "reference": cash.get("reference"),
            "reference_at": cash.get("reference_at"),
            "net_bps": None,
            "age_seconds": fut.get("age_seconds"),
            "effective_source": "YAHOO_FINANCE_ZN_FRONT_PROXY",
            "source": "CASH_LAST_VALID_PLUS_ZN_FUTURES_PROXY",
            "source_note": (
                "^TNX cash/index quote is not fresh. The displayed yield is LAST VALID only; "
                "fresh ZN Treasury futures provide directional yield pressure for overnight timing."
            ),
        }

    return {
        **base,
        "available": False,
        "freshness": "STALE" if cash_has_last else "MISSING",
        "state": (
            "US10Y_CASH_LAST_VALID_NO_FRESH_PROXY"
            if cash_has_last
            else "US10Y_NO_FRESH_TREASURY_FEED"
        ),
        "session_state": "NO_FRESH_TREASURY_FEED",
        "gold_implication": "UNAVAILABLE",
        "current": cash_last,
        "current_at": cash.get("current_at"),
        "reference": cash.get("reference"),
        "reference_at": cash.get("reference_at"),
        "net_bps": None,
        "age_seconds": cash.get("age_seconds"),
        "effective_source": "NONE",
        "source": "US10Y_SESSION_RESOLVER",
        "source_note": (
            "Neither the cash/index US10Y proxy nor Treasury futures are fresh enough for "
            "intraday confirmation. Last cash yield may still be shown as historical context."
        ),
    }
