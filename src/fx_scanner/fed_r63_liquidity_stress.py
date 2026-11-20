"""R6.3 exploratory liquidity-stress veto. READ ONLY; not a liquidation detector.

Uses only fully closed cTrader M5 OHLC already prepared by R6. The labels
describe observable price behaviour, NEVER proof of margin calls, stop runs,
forced liquidations, market-maker intent, or predictive trading accuracy.
All thresholds are research hypotheses pending point-in-time 2019-2026 replay.
"""
from __future__ import annotations

from math import isfinite
import pandas as pd

CONTRACT = "RIZAN_R63_LIQUIDITY_STRESS_RESEARCH_READONLY_V1"
STRESS = frozenset((
    "DOWNSIDE_DISPLACEMENT", "UPSIDE_DISPLACEMENT", "VOLATILITY_SPIKE",
    "SWEEP_LOW_RECLAIM", "SWEEP_HIGH_REJECT", "WIDE_SPREAD",
    "POST_STRESS_COOLDOWN",
))


def _base(reason: str = "NO_VALID_CLOSED_M5"):
    return {
        "contract": CONTRACT,
        "state": "UNKNOWN",
        "reason": reason,
        "observed_at": None,
        "atr_reference": None,
        "previous_20_low": None,
        "previous_20_high": None,
        "prior_stress_state": None,
        "stress_age_bars": None,
        "risk_veto": False,
        "liquidation_confirmed": False,
        "open_interest_confirmation": False,
        "volume_confirmation": False,
        "independently_backtested": False,
        "entry_permission": False,
        "authority_to_send_orders": False,
        "execution_influence": False,
    }


def assess_liquidity_stress(m5, *, now, spread=None, _scan_prior=True):
    """Causal closed-M5 displacement/sweep screen; no future-data access.

    Definitions (all research-only):
      displacement = break prior 20-bar range with 3-bar expansion and
                     >=2 same-direction candle bodies;
      sweep = pierce prior 20-bar extreme and close back inside, with wick;
      volatility spike = last completed bar's TR >= 2.4x previous TR median.
    Spread >0.2x past M5 TR median blocks chasing if supplied. A suspected
    liquidation cannot be *identified* by candles; OI/volume needed.
    """
    out = _base()
    try:
        asof = pd.Timestamp(now)
        if asof.tzinfo is None:
            return _base("NAIVE_AS_OF_CLOCK")
        asof = asof.tz_convert("UTC")
        if not isinstance(m5, pd.DataFrame) or not {"open", "high", "low", "close"}.issubset(m5.columns):
            return out
        if not isinstance(m5.index, pd.DatetimeIndex) or m5.index.tz is None:
            return _base("NAIVE_CANDLE_CLOCK")
        d = m5[["open", "high", "low", "close"]].copy().tail(36)
        d.index = d.index.tz_convert("UTC")
        if len(d) < 30 or not d.index.is_monotonic_increasing or d.index.has_duplicates:
            return _base("INSUFFICIENT_OR_INVALID_M5")
        if not (d.index[-29:].to_series().diff().iloc[1:] == pd.Timedelta(minutes=5)).all():
            return _base("M5_GAPS_PREVENT_LIQUIDITY_CLASSIFICATION")
        seconds = (asof - d.index[-1]).total_seconds()
        if not (0 <= seconds <= 600):
            return _base("STALE_OR_FUTURE_M5")
        if not d.apply(lambda x: x.map(isfinite)).all().all():
            return _base("INVALID_M5_PRICE")
        if not ((d.low > 0) & (d.high >= d[["open", "close"]].max(axis=1)) &
                (d.low <= d[["open", "close"]].min(axis=1))).all():
            return _base("INVALID_M5_OHLC")
        prior = d.iloc[:-1]
        tr = pd.concat(
            [prior.high - prior.low,
             (prior.high - prior.close.shift(1)).abs(),
             (prior.low - prior.close.shift(1)).abs()], axis=1
        ).max(axis=1)
        atr = float(tr.tail(20).median())
        if not isfinite(atr) or atr <= 0:
            return _base("INVALID_REFERENCE_VOLATILITY")
        lo = float(d.low.iloc[-21:-1].min())
        hi = float(d.high.iloc[-21:-1].max())
        last = d.iloc[-1]
        rng = float(last.high - last.low)
        net3 = float(d.close.iloc[-1] - d.close.iloc[-4])
        reds = int((d.close.iloc[-3:] < d.open.iloc[-3:]).sum())
        greens = int((d.close.iloc[-3:] > d.open.iloc[-3:]).sum())
        spread_n = None if spread is None else float(spread)
        if spread_n is not None and (not isfinite(spread_n) or spread_n < 0):
            return _base("INVALID_SPREAD")
        out.update({
            "observed_at": d.index[-1].isoformat(),
            "atr_reference": round(atr, 5),
            "previous_20_low": round(lo, 5),
            "previous_20_high": round(hi, 5),
        })
        if spread_n is not None and spread_n > .20 * atr:
            state = "WIDE_SPREAD"
        elif (last.low < lo - .10 * atr and last.close > lo + .05 * atr
              and min(last.open, last.close) - last.low >= .30 * atr):
            state = "SWEEP_LOW_RECLAIM"
        elif (last.high > hi + .10 * atr and last.close < hi - .05 * atr
              and last.high - max(last.open, last.close) >= .30 * atr):
            state = "SWEEP_HIGH_REJECT"
        elif (last.close < lo - .10 * atr and net3 <= -2.2 * atr
              and reds >= 2 and rng >= 1.1 * atr):
            state = "DOWNSIDE_DISPLACEMENT"
        elif (last.close > hi + .10 * atr and net3 >= 2.2 * atr
              and greens >= 2 and rng >= 1.1 * atr):
            state = "UPSIDE_DISPLACEMENT"
        elif rng >= 2.4 * atr:
            state = "VOLATILITY_SPIKE"
        else:
            state = "NORMAL"
        # A liquidations-like displacement must not become "NORMAL"
        # after just one harmless M5. Preserve a 3-closed-bar WATCH
        # cooldown using only already completed bars. No future data.
        if state == "NORMAL" and _scan_prior:
            for lag in (1,2,3):
                previous=d.iloc[:-lag]
                if len(previous)<30:
                    break
                prior = assess_liquidity_stress(
                    previous, now=previous.index[-1], spread=None,
                    _scan_prior=False)
                if prior["state"] in STRESS and prior["state"]!="WIDE_SPREAD":
                    state="POST_STRESS_COOLDOWN"
                    out["prior_stress_state"]=prior["state"]
                    out["stress_age_bars"]=lag
                    break
        out["state"] = state
        out["reason"] = (
            "CLOSED_BAR_PRICE_STRESS_NOT_PROOF_OF_FORCED_LIQUIDATION"
            if state in STRESS else "NO_ABNORMAL_CLOSED_BAR_PATTERN"
        )
        out["risk_veto"] = state in STRESS
        return out
    except (TypeError, ValueError, IndexError, OverflowError):
        return _base("LIQUIDITY_INPUT_INVALID")
