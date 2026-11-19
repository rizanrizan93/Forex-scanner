"""Research-only, causal XAUUSD rejection classification. No trading or broker calls."""
from __future__ import annotations
from dataclasses import dataclass
import math
import pandas as pd

@dataclass(frozen=True)
class RejectionResult:
    status: str
    side: str
    score: int
    reasons: tuple[str, ...]
    event_time_utc: str
    zone: float | None

def evaluate_rejection(candles: pd.DataFrame, lookback: int = 12, dxy_direction: int | None = None) -> RejectionResult:
    """Evaluate latest *closed* M5 candle. Input must exclude the forming candle.

    Required: UTC timestamp, open/high/low/close. dxy_direction: -1 falling, +1 rising,
    0 flat, None unavailable. Never infer unavailable macro confirmation.
    """
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(candles.columns):
        raise ValueError("Missing columns: " + ", ".join(sorted(required - set(candles.columns))))
    if not 5 <= lookback <= 200 or len(candles) < lookback + 4:
        raise ValueError("Need lookback+4 closed candles and lookback in [5,200]")
    if dxy_direction not in (-1, 0, 1, None):
        raise ValueError("dxy_direction must be -1, 0, 1 or None")
    df = candles.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="raise")
    if df["timestamp"].isna().any() or not df["timestamp"].is_monotonic_increasing or df["timestamp"].duplicated().any():
        raise ValueError("Timestamps must be unique, ascending, and UTC parseable")
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    if not all(math.isfinite(float(v)) for v in df[["open","high","low","close"]].to_numpy().ravel()):
        raise ValueError("Non-finite OHLC")
    if ((df.high < df.low) | (df.high < df[["open","close"]].max(axis=1)) | (df.low > df[["open","close"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC")
    # Event candle is penultimate; latest candle is confirmation, both closed.
    event = df.iloc[-2]
    confirm = df.iloc[-1]
    prior = df.iloc[-(lookback+2):-2]
    resistance, support = float(prior.high.max()), float(prior.low.min())
    span = max(float(event.high-event.low), 1e-9)
    body = abs(float(event.close-event.open))
    upper_wick = float(event.high-max(event.open,event.close))
    lower_wick = float(min(event.open,event.close)-event.low)
    sell_sweep = event.high > resistance and event.close < resistance
    buy_sweep = event.low < support and event.close > support
    sell_reclaim = upper_wick / span >= 0.35
    buy_reclaim = lower_wick / span >= 0.35
    sell_mss = confirm.close < event.low and confirm.close < confirm.open
    buy_mss = confirm.close > event.high and confirm.close > confirm.open
    # Both sides swept in same bar: ambiguous by design.
    if buy_sweep and sell_sweep:
        return RejectionResult("PENDING CONFIRMATION","NONE",0,("Two-sided sweep: ambiguous event",),confirm.timestamp.isoformat(),None)
    if not buy_sweep and not sell_sweep:
        return RejectionResult("INVALID/BREAKOUT","NONE",0,("No confirmed sweep-and-reclaim against prior range",),confirm.timestamp.isoformat(),None)
    is_buy = bool(buy_sweep)
    side = "BUY" if is_buy else "SELL"
    wick_ok = buy_reclaim if is_buy else sell_reclaim
    mss_ok = buy_mss if is_buy else sell_mss
    macro_ok = dxy_direction == (-1 if is_buy else 1)
    reasons = [
        "Liquidity sweep and close back inside prior range",
        ("Rejection wick >=35% of candle" if wick_ok else "Rejection wick below 35%"),
        ("Confirmation candle breaks event extreme" if mss_ok else "No confirmed displacement beyond event extreme"),
        ("DXY direction supports rejection" if macro_ok else "DXY unavailable/neutral/opposing"),
    ]
    score = 40 + (20 if wick_ok else 0) + (30 if mss_ok else 0) + (10 if macro_ok else 0)
    if not wick_ok or not mss_ok:
        status = "PENDING CONFIRMATION"
    elif dxy_direction is not None and not macro_ok:
        status = "PENDING CONFIRMATION"
    else:
        status = "VALID " + side + " REJECTION"
    return RejectionResult(status,side,score,tuple(reasons),confirm.timestamp.isoformat(),support if is_buy else resistance)
