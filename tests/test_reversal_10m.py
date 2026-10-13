import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fx_scanner.reversal_zones import (CONFIGURATIONS, normalize_bars, closed_features,
    thin_events, GRID, base_events, matches)

spec = importlib.util.spec_from_file_location("research", Path(__file__).parents[1]/"scripts/research_reversal_10m.py")
research = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research)


def fixture(days=12):
    rng = np.random.default_rng(118)
    t = pd.date_range("2020-01-01", periods=days*1440, freq="min", tz="UTC")
    c = 1500+np.cumsum(rng.normal(0,.15,len(t)))
    o = np.r_[c[0],c[:-1]]
    return pd.DataFrame(dict(timestamp=t, open=o, high=np.maximum(o,c)+.1,
                             low=np.minimum(o,c)-.1, close=c))


def test_exact_grid():
    assert CONFIGURATIONS == 10_000_000


@pytest.mark.parametrize("offset", ["Z", "+00:00", "+07:00", "-05:00"])
def test_aware(offset):
    f=fixture(1).iloc[:1].copy(); f.timestamp=f"2020-01-01T00:00:00{offset}"
    assert str(normalize_bars(f).index.tz)=="UTC"


def test_naive_rejected():
    f=fixture(1).iloc[:1].copy(); f.timestamp="2020-01-01T00:00:00"
    with pytest.raises(ValueError, match="OFFSET"): normalize_bars(f)


def test_no_future_features_or_preexisting_anchor_leak():
    f=fixture(); cutoff=pd.Timestamp("2020-01-10T12:00Z")
    a=closed_features(normalize_bars(f))
    changed=f.copy(); changed.loc[changed.timestamp>=cutoff,["open","high","low","close"]]+=500
    b=closed_features(normalize_bars(changed))
    pd.testing.assert_frame_equal(a.loc[:cutoff],b.loc[:cutoff])
    # At 12:00 trigger open is 11:55; its anchors cannot use H1 ending 12:00.
    for side in [1,-1]:
        assert a.loc[cutoff,f"formed_{side}_6"] <= (cutoff-pd.Timedelta(hours=1)).value/3.6e12


def test_nonoverlap_and_first_observation():
    e=pd.DataFrame({"close":[1]*100},index=pd.date_range("2020-01-01",periods=100,freq="5min",tz="UTC"))
    out=thin_events(e)
    assert out.index[0]==e.index[0]
    assert np.all(np.diff(out.index.asi8)>=240*60*10**9)


def test_ambiguous_bar_stop_first_no_future_or_gap_slide():
    t=np.arange(0,301*60,60,dtype=np.int64)
    h=np.full(len(t),101.0); l=np.full(len(t),99.0)
    r=research.outcomes(t,h,l,np.full(len(t),100.),np.array([0]),np.array([100.]),
        np.array([100.]),np.array([1.]),1)
    assert np.all(r==-1)
    t=np.array([0,600,660],np.int64)
    r=research.outcomes(t,np.full(3,100.01),np.full(3,99.99),np.full(3,100.),np.array([0]),
        np.array([100.]),np.array([100.]),np.array([1.]),1)
    assert np.all(r==-2)


def test_histogram_exact_against_brute_force_filters():
    rng=np.random.default_rng(5)
    e=pd.DataFrame({k:rng.integers(0,n,100) for k,n in
        [("wick_bin",5),("approach_bin",5),("age_bin",5),("trend_bin",3),("session",4)]})
    hist=np.zeros((5,5,5,3,4),np.int32)
    np.add.at(hist,tuple(e[c].to_numpy() for c in e.columns),1)
    expanded=research.expand_hist(hist)
    for w in range(5):
        for a in range(5):
            for age in range(5):
                for tr,trend in enumerate(GRID["trend"]):
                    for se in range(4):
                        cfg={"wick_fraction":GRID["wick_fraction"][w],"approach_atr":GRID["approach_atr"][a],
                             "max_age_hours":GRID["max_age_hours"][age],"trend":trend,"session_utc":se*6}
                        assert expanded[w,a,age,tr,se]==matches(e,cfg).sum()


def test_incomplete_m5_excluded():
    f=fixture(); f=f.drop(index=100)
    out=closed_features(normalize_bars(f))
    assert pd.Timestamp("2020-01-01T01:45Z") not in out.index


def test_no_execution_imports():
    root=Path(__file__).parents[1]
    for filename in ["src/fx_scanner/reversal_zones.py", "scripts/research_reversal_10m.py"]:
        text=(root/filename).read_text()
        assert "from .execution" not in text and "cbot_bridge" not in text
