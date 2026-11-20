"""R8-T: research-only causal USD availability gate; no market performance claims."""
from bisect import bisect_right
from math import isfinite
from datetime import timedelta

def causal_window(bar_open_times, event_utc, lag_seconds=120, max_age_seconds=300,
                  windows=(5,15,60)):
    """Require completed, published, UTC minute-aligned candles for each lookback."""
    if (isinstance(lag_seconds,bool) or not isinstance(lag_seconds,(int,float)) or
        not isfinite(lag_seconds) or lag_seconds<0 or isinstance(max_age_seconds,bool) or
        not isinstance(max_age_seconds,(int,float)) or not isfinite(max_age_seconds) or max_age_seconds<0):
        raise ValueError("BAD_DELAY")
    if not windows or any(isinstance(n,bool) or not isinstance(n,int) or n<1 for n in windows):
        raise ValueError("BAD_WINDOW")
    if event_utc.tzinfo is None or event_utc.utcoffset() is None or event_utc.utcoffset().total_seconds()!=0:
        raise ValueError("EVENT_NOT_UTC")
    if any(t.tzinfo is None or t.utcoffset() is None or t.utcoffset().total_seconds()!=0 for t in bar_open_times):
        raise ValueError("BAR_NOT_UTC")
    if any(t.second!=0 or t.microsecond!=0 for t in bar_open_times):
        raise ValueError("BAR_NOT_MINUTE_ALIGNED")
    if any(b<=a for a,b in zip(bar_open_times,bar_open_times[1:])):
        raise ValueError("UNSORTED_OR_DUPLICATE_BARS")
    cutoff=event_utc-timedelta(seconds=60+lag_seconds)
    i=bisect_right(bar_open_times,cutoff)-1
    if i<0:
        return {"status":"NO_AVAILABLE_BAR","age_seconds":None,"windows":{}}
    end=bar_open_times[i]
    available_at=end+timedelta(seconds=60+lag_seconds)
    age=(event_utc-available_at).total_seconds()
    present=set(bar_open_times)
    flags={n:(age<=max_age_seconds and all(end-timedelta(minutes=k) in present for k in range(n+1))) for n in windows}
    return {"status":"OK" if any(flags.values()) else "UNAVAILABLE",
            "bar_open_utc":end.isoformat(),"available_at_utc":available_at.isoformat(),
            "age_seconds":age,"windows":flags}
