from __future__ import annotations

from typing import Any


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_daily_us10y(macro_eval: dict[str, Any]) -> dict[str, Any]:
    """Translate daily FRED US10Y delta into a regime label for XAU context."""
    row = dict(dict(macro_eval.get("components") or {}).get("US10Y") or {})
    current = _f(row.get("current"))
    previous = _f(row.get("previous"))
    delta_bps = _f(row.get("delta"))
    freshness = str(row.get("freshness") or "UNAVAILABLE")

    if current is None or previous is None or delta_bps is None:
        return {
            "state": "UNAVAILABLE",
            "gold_bias": "UNAVAILABLE",
            "current": current,
            "previous": previous,
            "delta_bps": delta_bps,
            "freshness": freshness,
        }

    if delta_bps <= -1.0:
        state = "YIELD_DAILY_DOWN"
        bias = "BULLISH_XAU"
    elif delta_bps >= 1.0:
        state = "YIELD_DAILY_UP"
        bias = "BEARISH_XAU"
    else:
        state = "YIELD_DAILY_FLAT"
        bias = "NEUTRAL_MIXED"

    return {
        "state": state,
        "gold_bias": bias,
        "current": current,
        "previous": previous,
        "delta_bps": delta_bps,
        "freshness": freshness,
        "source": row.get("provider") or "FEDERAL_RESERVE_FRED",
        "frequency": "DAILY",
    }


def classify_intraday_us10y(macro_eval: dict[str, Any]) -> dict[str, Any]:
    """Translate the runtime intraday yield context into XAU timing pressure."""
    intraday = dict(
        macro_eval.get("intraday_yield_context")
        or macro_eval.get("intraday_us10y")
        or {}
    )
    state = str(intraday.get("state") or macro_eval.get("intraday_yield_state") or "UNAVAILABLE")
    current = _f(intraday.get("current"))
    rebound = _f(intraday.get("rebound_from_low_bps"))
    net = _f(intraday.get("net_from_release_bps"))
    gold_implication = str(intraday.get("gold_implication") or "UNAVAILABLE")

    if gold_implication == "GOLD_HEADWIND_CONFIRMED":
        bias = "BEARISH_XAU"
    elif gold_implication in {"GOLD_SUPPORT_CONFIRMED", "GOLD_TAILWIND_CONFIRMED"}:
        bias = "BULLISH_XAU"
    elif state in {"YIELD_REVERSAL_UP_STRONG", "YIELD_UP", "YIELD_ACCELERATION_UP"}:
        bias = "BEARISH_XAU"
    elif state in {"YIELD_REVERSAL_DOWN_STRONG", "YIELD_DOWN", "YIELD_ACCELERATION_DOWN"}:
        bias = "BULLISH_XAU"
    else:
        bias = "UNAVAILABLE" if not intraday.get("available", False) else "NEUTRAL_MIXED"

    return {
        "state": state,
        "gold_bias": bias,
        "current": current,
        "rebound_from_low_bps": rebound,
        "net_from_release_bps": net,
        "available": bool(intraday.get("available", False)),
        "source": intraday.get("source") or "INTRADAY_SECONDARY_PROXY",
        "frequency": "INTRADAY",
    }


def yield_regime_summary(macro_eval: dict[str, Any]) -> dict[str, Any]:
    daily = classify_daily_us10y(macro_eval)
    intraday = classify_intraday_us10y(macro_eval)
    daily_bias = daily.get("gold_bias")
    intraday_bias = intraday.get("gold_bias")

    if intraday_bias == "UNAVAILABLE":
        alignment = "INTRADAY_UNAVAILABLE"
        decision_note = "Gunakan daily FRED sebagai regime saja; timing menunggu intraday yield tersedia."
    elif daily_bias == intraday_bias and daily_bias in {"BULLISH_XAU", "BEARISH_XAU"}:
        alignment = "ALIGNED"
        decision_note = "Regime harian dan pressure intraday searah. Tetap tunggu konfirmasi struktur XAU sebelum entry."
    elif daily_bias in {"BULLISH_XAU", "BEARISH_XAU"} and intraday_bias in {"BULLISH_XAU", "BEARISH_XAU"}:
        alignment = "DIVERGENT"
        decision_note = "Daily regime dan intraday pressure berlawanan. Jangan entry dari makro saja; prioritaskan price structure dan tunggu alignment/reclaim."
    else:
        alignment = "MIXED"
        decision_note = "Yield context belum directional penuh. Gunakan sebagai konteks, bukan trigger entry."

    return {
        "daily": daily,
        "intraday": intraday,
        "alignment": alignment,
        "decision_note": decision_note,
    }
