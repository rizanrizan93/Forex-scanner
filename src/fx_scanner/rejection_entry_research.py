"""Research-only entry planner for symmetric BUY/SELL rejection events."""
from dataclasses import dataclass
import pandas as pd
from fx_scanner.rejection_engine_research import evaluate_rejection

@dataclass(frozen=True)
class EntryPlan:
    rejection: str
    side: str
    entry_status: str
    retest_low: float | None
    retest_high: float | None
    invalidation: float | None
    reference_price: float
    explanation: str

def plan_entry(candles: pd.DataFrame, lookback: int = 12, dxy_direction: int | None = None, tolerance: float = 0.15) -> EntryPlan:
    """Closed M5 candles only. Detect a prior event, then evaluate subsequent retest.
    The entry band is the midpoint-to-body edge of the displacement candle.
    No fills or orders are generated. This is a deterministic hypothesis, not validated alpha.
    """
    if not 0 <= tolerance <= 1:
        raise ValueError("tolerance must be in [0,1]")
    if len(candles) < lookback + 5:
        raise ValueError("Insufficient closed M5 candles")
    # Find most recent confirmed event within last 12 bars; never use later bars to confirm event.
    latest = pd.to_numeric(candles["close"], errors="raise").iloc[-1]
    for end in range(len(candles), max(lookback+3,len(candles)-12), -1):
        subset = candles.iloc[:end]
        r = evaluate_rejection(subset, lookback, dxy_direction)
        if not r.status.startswith("VALID"):
            continue
        event, impulse = subset.iloc[-2], subset.iloc[-1]
        side = r.side
        low = float(impulse.low)
        high = float(impulse.high)
        mid = (low + high)/2
        if side == "BUY":
            band_low, band_high = mid, float(impulse.close)
            invalid = float(event.low)
        else:
            band_low, band_high = float(impulse.close), mid
            invalid = float(event.high)
        band_low,band_high = sorted((band_low,band_high))
        width=max(high-low,1e-8)
        pad=width*tolerance
        after = candles.iloc[end:]
        if side == "BUY":
            broken = (after["close"] < invalid).any() or latest < invalid
            touched = ((after["low"] <= band_high+pad) & (after["high"] >= band_low-pad)).any()
            currently = band_low-pad <= latest <= band_high+pad
            missed = latest > high+2*width
        else:
            broken = (after["close"] > invalid).any() or latest > invalid
            touched = ((after["low"] <= band_high+pad) & (after["high"] >= band_low-pad)).any()
            currently = band_low-pad <= latest <= band_high+pad
            missed = latest < low-2*width
        status = ("INVALIDATED" if broken else "ENTRY READY — CHECK M5 REACTION" if currently and touched
                  else "WAIT RETEST" if not touched else "MISSED ENTRY" if missed else "RETEST OCCURRED — WAIT CONFIRMATION")
        return EntryPlan(r.status,side,status,band_low,band_high,invalid,float(latest),
                         "Candidate retest of displacement candle; require a fresh closed-candle reaction before manual entry.")
    return EntryPlan("NO VALID REJECTION","NONE","NO TRADE",None,None,None,float(latest),
                     "No recent confirmed sweep, reclaim, and displacement. Do not force entry.")
