from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Sequence

from .models import Bar, ensure_utc

CONTRACT = "XAU_RIZAN_COMPOSITE_PRESSURE_V272"
POLICY_EFFECT = "SHADOW_PLUS_DEMO_CALIBRATION_FALLBACK"
EXECUTION_AUTHORITY = False
ADX_PERIOD = 14


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _ema(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    rows = tuple(float(v) for v in values)
    if period <= 1 or len(rows) < period:
        return tuple(None for _ in rows)
    seed = sum(rows[:period]) / float(period)
    out: list[float | None] = [None] * (period - 1) + [seed]
    alpha = 2.0 / (float(period) + 1.0)
    previous = seed
    for value in rows[period:]:
        previous = alpha * value + (1.0 - alpha) * previous
        out.append(previous)
    return tuple(out)


def _rma(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    rows = tuple(float(v) for v in values)
    if period <= 0 or len(rows) < period:
        return tuple(None for _ in rows)
    seed = sum(rows[:period]) / float(period)
    out: list[float | None] = [None] * (period - 1) + [seed]
    previous = seed
    for value in rows[period:]:
        previous = ((previous * (period - 1)) + value) / float(period)
        out.append(previous)
    return tuple(out)


def _atr(bars: Sequence[Bar], period: int = 14) -> float | None:
    rows = tuple(bars)
    if len(rows) < period + 1:
        return None
    tr: list[float] = []
    previous = rows[0]
    for current in rows[1:]:
        tr.append(
            max(
                float(current.high) - float(current.low),
                abs(float(current.high) - float(previous.close)),
                abs(float(current.low) - float(previous.close)),
            )
        )
        previous = current
    smoothed = [float(v) for v in _rma(tr, period) if v is not None]
    return None if not smoothed else smoothed[-1]


def _adx_bundle(
    bars: Sequence[Bar],
    period: int = ADX_PERIOD,
) -> dict[str, float | bool | None]:
    rows = tuple(bars)
    if len(rows) < period * 3 + 3:
        return {
            "adx": None,
            "adxr": None,
            "plus_di": None,
            "minus_di": None,
            "adx_rising": False,
        }

    tr: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    previous = rows[0]
    for current in rows[1:]:
        up_move = float(current.high) - float(previous.high)
        down_move = float(previous.low) - float(current.low)
        plus_dm.append(up_move if up_move > down_move and up_move > 0.0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0.0 else 0.0)
        tr.append(
            max(
                float(current.high) - float(current.low),
                abs(float(current.high) - float(previous.close)),
                abs(float(current.low) - float(previous.close)),
            )
        )
        previous = current

    tr_rma = _rma(tr, period)
    plus_rma = _rma(plus_dm, period)
    minus_rma = _rma(minus_dm, period)

    dx_values: list[float] = []
    latest_tr = latest_plus = latest_minus = None
    for tr_value, plus_value, minus_value in zip(tr_rma, plus_rma, minus_rma):
        if tr_value is None or plus_value is None or minus_value is None:
            continue
        if float(tr_value) <= 0.0:
            continue
        latest_tr = float(tr_value)
        latest_plus = float(plus_value)
        latest_minus = float(minus_value)
        plus_di = 100.0 * latest_plus / latest_tr
        minus_di = 100.0 * latest_minus / latest_tr
        denominator = plus_di + minus_di
        dx_values.append(
            0.0
            if denominator <= 1e-12
            else 100.0 * abs(plus_di - minus_di) / denominator
        )

    if (
        latest_tr is None
        or latest_plus is None
        or latest_minus is None
        or len(dx_values) < period
    ):
        return {
            "adx": None,
            "adxr": None,
            "plus_di": None,
            "minus_di": None,
            "adx_rising": False,
        }

    adx_values = [float(v) for v in _rma(dx_values, period) if v is not None]
    if not adx_values:
        return {
            "adx": None,
            "adxr": None,
            "plus_di": None,
            "minus_di": None,
            "adx_rising": False,
        }
    adx = adx_values[-1]
    prior_adx = adx_values[-1 - period] if len(adx_values) > period else adx
    adxr = (adx + prior_adx) / 2.0
    plus_di = 100.0 * latest_plus / latest_tr
    minus_di = 100.0 * latest_minus / latest_tr
    return {
        "adx": adx,
        "adxr": adxr,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "adx_rising": bool(len(adx_values) >= 2 and adx_values[-1] > adx_values[-2]),
    }


def _candle_pressure(bars: Sequence[Bar], lookback: int = 6) -> float:
    rows = tuple(bars)[-lookback:]
    if not rows:
        return 0.0
    values: list[float] = []
    for bar in rows:
        high = float(bar.high)
        low = float(bar.low)
        open_ = float(bar.open)
        close = float(bar.close)
        rng = max(high - low, 1e-12)
        body = _clamp((close - open_) / rng)
        close_location = _clamp(((close - low) / rng - 0.5) * 2.0)
        values.append(0.60 * body + 0.40 * close_location)
    return _clamp(sum(values) / len(values))


def _efficiency_pressure(bars: Sequence[Bar], lookback: int = 8) -> float:
    rows = tuple(bars)[-(lookback + 1):]
    if len(rows) < 3:
        return 0.0
    closes = [float(row.close) for row in rows]
    net = closes[-1] - closes[0]
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    if path <= 1e-12:
        return 0.0
    return _clamp(net / path)


def _timeframe_snapshot(bars: Sequence[Bar], timeframe: str) -> dict[str, Any]:
    rows = tuple(bars)
    if len(rows) < 60:
        return {
            "available": False,
            "timeframe": timeframe,
            "reason": "INSUFFICIENT_HISTORY",
        }

    closes = tuple(float(row.close) for row in rows)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    atr14 = _atr(rows, 14)
    bundle = _adx_bundle(rows, 14)
    if (
        ema20[-1] is None
        or ema50[-1] is None
        or atr14 is None
        or not isfinite(float(atr14))
        or float(atr14) <= 0.0
        or bundle.get("plus_di") is None
        or bundle.get("minus_di") is None
    ):
        return {
            "available": False,
            "timeframe": timeframe,
            "reason": "INDICATOR_NOT_READY",
        }

    atr_value = float(atr14)
    current_close = closes[-1]
    current_ema20 = float(ema20[-1])
    current_ema50 = float(ema50[-1])
    prior_ema20 = next(
        (
            float(value)
            for value in reversed(ema20[:-3])
            if value is not None
        ),
        current_ema20,
    )

    plus_di = float(bundle["plus_di"])
    minus_di = float(bundle["minus_di"])
    di_component = _clamp((plus_di - minus_di) / 25.0)
    ema_component = _clamp(
        0.35 * _clamp((current_close - current_ema20) / atr_value)
        + 0.40 * _clamp((current_ema20 - current_ema50) / atr_value)
        + 0.25 * _clamp((current_ema20 - prior_ema20) / atr_value)
    )
    candle_component = _candle_pressure(rows)
    efficiency_component = _efficiency_pressure(rows)

    adx = float(bundle.get("adx") or 0.0)
    adxr = float(bundle.get("adxr") or adx)
    strength = _clamp(((adx + adxr) / 2.0 - 12.0) / 28.0, 0.0, 1.0)
    raw_signed = _clamp(
        0.35 * di_component
        + 0.30 * ema_component
        + 0.20 * candle_component
        + 0.15 * efficiency_component
    )
    signed = _clamp(raw_signed * (0.70 + 0.30 * strength))
    buyer_index = 50.0 + 50.0 * signed

    return {
        "available": True,
        "timeframe": timeframe,
        "signed_pressure": signed,
        "buyer_index": buyer_index,
        "seller_index": 100.0 - buyer_index,
        "adx14": adx,
        "adxr14": adxr,
        "plus_di14": plus_di,
        "minus_di14": minus_di,
        "adx_rising": bool(bundle.get("adx_rising")),
        "atr14": atr_value,
        "ema20": current_ema20,
        "ema50": current_ema50,
        "close": current_close,
        "components": {
            "di": di_component,
            "ema_structure": ema_component,
            "candle": candle_component,
            "efficiency": efficiency_component,
            "trend_strength": strength,
        },
    }


def _completed(
    bars: Sequence[Bar],
    *,
    as_of: datetime,
    minutes: int,
) -> tuple[Bar, ...]:
    now = ensure_utc(as_of)
    return tuple(
        row
        for row in sorted(tuple(bars), key=lambda x: ensure_utc(x.timestamp))
        if ensure_utc(row.timestamp) + timedelta(minutes=minutes) <= now
    )


def evaluate_xau_composite_pressure_v272(
    *,
    m5_bars: Sequence[Bar],
    m15_bars: Sequence[Bar],
    as_of: datetime,
) -> dict[str, Any]:
    """Price-derived buyer/seller pressure that remains available when DOM is stale.

    ADX/ADXR are used only as trend-strength stabilizers. Direction comes from
    DI spread, EMA location/slope, candle pressure and directional efficiency.
    This output has no standalone execution authority. It may only provide a
    DEMO calibration fallback when the broker DOM sample is stale/unavailable;
    strict child execution remains governed by the existing structure/RR gates.
    """
    m5 = _completed(m5_bars, as_of=as_of, minutes=5)
    m15 = _completed(m15_bars, as_of=as_of, minutes=15)
    m5_now = _timeframe_snapshot(m5, "M5")
    m15_now = _timeframe_snapshot(m15, "M15")
    available = bool(m5_now.get("available") and m15_now.get("available"))
    if not available:
        return {
            "contract": CONTRACT,
            "available": False,
            "state": "UNAVAILABLE",
            "execution_authority": EXECUTION_AUTHORITY,
            "policy_effect": POLICY_EFFECT,
            "m5": m5_now,
            "m15": m15_now,
        }

    signed = _clamp(
        0.60 * float(m5_now["signed_pressure"])
        + 0.40 * float(m15_now["signed_pressure"])
    )
    buyer = 50.0 + 50.0 * signed
    seller = 100.0 - buyer

    previous_m5 = _timeframe_snapshot(m5[:-1], "M5") if len(m5) > 60 else {}
    previous_m15 = _timeframe_snapshot(m15[:-1], "M15") if len(m15) > 60 else {}
    previous_score = None
    if previous_m5.get("available") and previous_m15.get("available"):
        previous_signed = _clamp(
            0.60 * float(previous_m5["signed_pressure"])
            + 0.40 * float(previous_m15["signed_pressure"])
        )
        previous_score = 50.0 + 50.0 * previous_signed
    score_change = None if previous_score is None else buyer - previous_score

    if buyer >= 62.0:
        state = "BUYER_CONTROL"
    elif buyer >= 55.0:
        state = "BUYER_LEAN"
    elif buyer <= 38.0:
        state = "SELLER_CONTROL"
    elif buyer <= 45.0:
        state = "SELLER_LEAN"
    else:
        state = "BALANCED"

    # Mirrors the V271 'not materially opposing' tolerance for the tiny DEMO
    # calibration lane. Both can be true near balance because structure decides
    # the intended side; this is not a directional signal by itself.
    long_calibration_allowed = buyer >= 42.5
    short_calibration_allowed = buyer <= 57.5

    return {
        "contract": CONTRACT,
        "available": True,
        "as_of": ensure_utc(as_of).isoformat(),
        "state": state,
        "buyer_index": round(buyer, 4),
        "seller_index": round(seller, 4),
        "signed_pressure": round(signed, 6),
        "score_change": None if score_change is None else round(score_change, 4),
        "long_calibration_allowed": bool(long_calibration_allowed),
        "short_calibration_allowed": bool(short_calibration_allowed),
        "strict_long_supported": bool(buyer >= 55.0),
        "strict_short_supported": bool(buyer <= 45.0),
        "execution_authority": EXECUTION_AUTHORITY,
        "policy_effect": POLICY_EFFECT,
        "m5": m5_now,
        "m15": m15_now,
        "interpretation": (
            "RIZAN composite pressure: M5 60% + M15 40%. ADX/ADXR measure "
            "trend strength only; DI, EMA structure/slope, candle pressure and "
            "directional efficiency determine direction. This is not order-flow "
            "volume and is not a standalone entry signal."
        ),
    }
