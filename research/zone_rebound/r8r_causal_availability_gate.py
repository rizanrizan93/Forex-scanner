"""R8-R: research-only causal USD availability audit, no performance claims.

An M1 bar is usable only after its CLOSE plus publication delay.
The reported age is measured from availability, not from close.
This module does not download data or authenticate vendor provenance.
"""
from bisect import bisect_right
from datetime import timedelta

def causal_window(bar_open_times, event_utc, lag_seconds=120, max_age_seconds=300,
                  windows=(5,15,60)):
    """Return selected bar and window availability; timestamps must be aware UTC."""
    if lag_seconds < 0 or max_age_seconds < 0:
        raise ValueError("NEGATIVE_DELAY")
    if event_utc.tzinfo is None or event_utc.utcoffset().total_seconds()!=0:
        raise ValueError("EVENT_NOT_UTC")
    if any(t.tzinfo is None or t.utcoffset().total_seconds()!=0 for t in bar_open_times):
        raise ValueError("BAR_NOT_UTC")
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
    flags={}
    for n in windows:
        if not isinstance(n,int) or n<1: raise ValueError("BAD_WINDOW")
        flags[n]=(age<=max_age_seconds and
                  all(end-timedelta(minutes=k) in present for k in range(n+1)))
    return {"status":"OK" if any(flags.values()) else "UNAVAILABLE",
            "bar_open_utc":end.isoformat(),"available_at_utc":available_at.isoformat(),
            "age_seconds":age,"windows":flags}

if __name__=="__main__":
    import unittest
    from datetime import datetime,timezone
    class Tests(unittest.TestCase):
        def setUp(self):
            self.t=datetime(2020,1,2,12,0,tzinfo=timezone.utc)
            self.bars=[self.t+timedelta(minutes=k) for k in range(61)]
        def test_before_publication(self):
            r=causal_window(self.bars,self.t+timedelta(seconds=179))
            self.assertEqual(r["status"],"NO_AVAILABLE_BAR")
        def test_at_publication(self):
            r=causal_window(self.bars,self.t+timedelta(minutes=63))
            self.assertEqual(r["age_seconds"],0)
            self.assertTrue(r["windows"][60])
        def test_gap_rejected(self):
            r=causal_window(self.bars[:40]+self.bars[41:],self.t+timedelta(minutes=63))
            self.assertFalse(r["windows"][60])
            self.assertTrue(r["windows"][15])
        def test_stale_rejected(self):
            r=causal_window(self.bars,self.t+timedelta(minutes=70))
            self.assertFalse(any(r["windows"].values()))
        def test_duplicate_rejected(self):
            with self.assertRaisesRegex(ValueError,"UNSORTED"):
                causal_window(self.bars+[self.bars[-1]],self.t)
    unittest.main()
