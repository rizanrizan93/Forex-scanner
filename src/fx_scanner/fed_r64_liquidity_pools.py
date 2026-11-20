"""R6 liquidity pools derived from fully closed XAU M5 bars, research only.

Levels: previous COMPLETED NY-17:00 FX trading day range, and latest
COMPLETED 08:00–13:00 WIB Asia session. They are candidates for stop
concentration, NOT broker stop orders nor proof of smart-money activity.
No current partial sessions or retroactively changed extremes allowed.
"""
from __future__ import annotations
from datetime import timedelta
import pandas as pd

CONTRACT = "RIZAN_R6_LIQUIDITY_POOLS_CLOSED_M5_READONLY_V1"


def _out(reason="M5_UNAVAILABLE"):
    return {
        "contract": CONTRACT, "state": "UNKNOWN", "reason": reason,
        "levels": [], "entry_permission": False, "execution_influence": False,
        "actual_stop_orders_observed": False, "liquidation_confirmed": False,
    }


def map_xau_liquidity_pools(m5, *, now):
    result = _out()
    try:
        t = pd.Timestamp(now)
        if t.tzinfo is None:
            return _out("NAIVE_AS_OF")
        t = t.tz_convert("UTC")
        if not isinstance(m5, pd.DataFrame) or not {"open","high","low","close"}.issubset(m5.columns):
            return result
        if not isinstance(m5.index,pd.DatetimeIndex) or m5.index.tz is None:
            return _out("NAIVE_M5")
        d = m5[["open","high","low","close"]].copy()
        d.index = d.index.tz_convert("UTC")
        d = d.loc[d.index <= t]  # only closed bar timestamps
        if len(d) < 60 or d.index.has_duplicates or not d.index.is_monotonic_increasing:
            return _out("INSUFFICIENT_OR_INVALID_M5")
        if d.isna().any().any() or not (
            (d.low>0)&(d.high>=d[["open","close"]].max(axis=1))&
            (d.low<=d[["open","close"]].min(axis=1))
        ).all():
            return _out("INVALID_OHLC")
        if not 0 <= (t-d.index[-1]).total_seconds() <= 600:
            return _out("STALE_M5")
        ny = d.index.tz_convert("America/New_York")
        ny_day = pd.Index([
            (x.date() if x.hour >= 17 else x.date()-timedelta(days=1))
            for x in ny
        ])
        current_ny = t.tz_convert("America/New_York")
        trading_date = (current_ny.date() if current_ny.hour >= 17
                        else current_ny.date()-timedelta(days=1))
        completed_days = sorted(set(x for x in ny_day if x < trading_date),reverse=True)
        levels=[]
        for day in completed_days[:5]:
            sub=d.loc[ny_day==day]
            # Real NY-17 rollover is ~23h of active spot trading (276 bars).
            # Require >=250 complete M5 observations and no >30-min holes.
            if len(sub)<250 or (sub.index.to_series().diff().dropna() >
                                pd.Timedelta(minutes=30)).any():
                continue
            for tag,price in (("PRIOR_NY_DAY_HIGH",float(sub.high.max())),
                              ("PRIOR_NY_DAY_LOW",float(sub.low.min()))):
                levels.append({"name":tag,"price":round(price,5),
                               "session_date":str(day),
                               "confirmed_at":sub.index[-1].isoformat(),
                               "timestamp_basis":"NY_17_TRADING_DAY"})
            break
        wib = d.index.tz_convert("Asia/Jakarta")
        # M5 index denotes *close*: Asia 08:00-13:00 WIB has 60
        # completed bars ending 08:05 through 13:00 inclusive.
        session=(wib.hour*60+wib.minute>8*60)&(wib.hour*60+wib.minute<=13*60)
        asia_dates=sorted(set(x.date() for x in wib[session]),reverse=True)
        for day in asia_dates[:4]:
            selected = session & (pd.Index(wib.date)==day)
            sub=d.loc[selected]
            if (len(sub)!=60 or not
                (sub.index.to_series().diff().dropna()==pd.Timedelta(minutes=5)).all()):
                continue
            # A complete session must have the exact first and last bar.
            local=sub.index.tz_convert("Asia/Jakarta")
            if (local[0].hour,local[0].minute)!=(8,5) or (
                local[-1].hour,local[-1].minute)!=(13,0):
                continue
            if (t-sub.index[-1])>pd.Timedelta(hours=42):
                continue
            for tag,price in (("ASIA_SESSION_HIGH",float(sub.high.max())),
                              ("ASIA_SESSION_LOW",float(sub.low.min()))):
                levels.append({"name":tag,"price":round(price,5),
                               "session_date":str(day),
                               "confirmed_at":sub.index[-1].isoformat(),
                               "timestamp_basis":"08_13_WIB"})
            break
        result.update(state="READY" if levels else "NO_FULL_SESSION_IN_WINDOW",
                      reason="CLOSED_SESSIONS_ONLY",levels=levels)
        return result
    except (ValueError,TypeError,OverflowError,IndexError):
        return _out("LIQUIDITY_POOL_INPUT_INVALID")
