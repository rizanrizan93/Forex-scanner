"""XAU ZQ4 alternate source (research ONLY): pinned public Dukascopy-derived M1 bid/ask.
Original HistData v193 download is blocked by expired TLS certificate.
No TLS bypass; no mixing with XAU immutable direction benchmark.
Dataset source itself is a third-party GitHub archive, not Dukascopy API.
"""
import hashlib, io, json
from datetime import datetime
import numpy as np,pandas as pd,requests
import zq4_bz3_micro_replay as engine

PIN="1d8e4c008fe177be455f6de05f5057ebdde901ae"
REPO="3650326613-png/dukascopy_xauusd_1m_data"
ROOT=f"https://raw.githubusercontent.com/{REPO}/{PIN}/xauusd"
def acquire(year):
    months=list(range(1,9)) if year==2026 else list(range(1,13))
    periods=[(year-1,11),(year-1,12)]+[(year,m) for m in months]
    sess=requests.Session();out={};hashes={};allspreads=[]
    for side in ("bid","ask"):
        frames=[]
        for y,m in periods:
            name=f"xauusd_{side}_m1_{y}_{m:02d}.csv"
            url=f"{ROOT}/{side}/m1/{name}"
            response=sess.get(url,timeout=(10,60))
            response.raise_for_status()
            content=response.content
            assert 200_000<len(content)<4_000_000,(name,len(content))
            a=pd.read_csv(io.BytesIO(content))
            assert list(a.columns)==["timestamp","open","high","low","close"],name
            times=pd.to_datetime(pd.to_numeric(a.pop("timestamp"),errors="raise"),unit="ms",utc=True)
            assert times.is_monotonic_increasing and times.is_unique
            start=pd.Timestamp(f"{y}-{m:02d}-01",tz="UTC")
            finish=start+pd.offsets.MonthBegin(1)
            assert start<=times.iloc[0]<finish and start<times.iloc[-1]<finish
            # Up to May 2026 vendor padded whole calendar months; from Jun 2026
            # it switched to trading-session rows. Both are valid when explicit.
            if y<2026 or (y==2026 and m<6):
                days=pd.Period(f"{y}-{m:02d}").days_in_month
                assert times.iloc[0]==start and len(a)==days*1440,(name,len(a),days*1440)
                assert times.iloc[-1]==finish-pd.Timedelta(minutes=1)
            elif m in (6,7):
                assert len(a)>=30000 and len(a)<45000,(name,len(a))
            else:
                assert m==8 and len(a)>=20000,(name,len(a))
            a.index=times
            frames.append(a.rename(columns={"open":"o","high":"h","low":"l","close":"c"}))
            hashes[name]=hashlib.sha256(content).hexdigest()
        out[side]=pd.concat(frames).sort_index()
    bid=out["bid"];ask=out["ask"]
    shared=bid.index.intersection(ask.index)
    mismatch=max(len(bid),len(ask))-len(shared)
    assert len(shared)>=.95*max(len(bid),len(ask)),("MISALIGNED_BID_ASK",len(bid),len(ask),len(shared))
    # Unlike forwardfill, strict intersection cannot manufacture an executable quote.
    bid=bid.loc[shared];ask=ask.loc[shared]
    assert np.isfinite(bid).all().all() and np.isfinite(ask).all().all()
    assert ((bid.l>0)&(bid.l<=bid[["o","c"]].min(axis=1))&(bid.h>=bid[["o","c"]].max(axis=1))).all()
    assert ((ask.l>0)&(ask.l<=ask[["o","c"]].min(axis=1))&(ask.h>=ask[["o","c"]].max(axis=1))).all()
    spread=ask.c-bid.c
    negative=int((spread<0).sum())
    if negative>0:raise ValueError(f"Negative Dukascopy quote spread {negative}")
    # Archive contains calendar-minute forward-filled quotes through market close.
    # Exclude the full New York FX closed session; never label padded weekend prices as trades.
    ny=bid.index.tz_convert("America/New_York")
    closed=(ny.dayofweek==5)|((ny.dayofweek==4)&(ny.hour>=17))|((ny.dayofweek==6)&(ny.hour<18))
    valid=~closed
    bid=bid.loc[valid]
    observed=spread.loc[valid]
    stationary=(bid.h==bid.l)&(bid.o==bid.c)&bid.c.eq(bid.c.shift())
    # Reject runs with 3+ consecutive apparently forward-filled quotes.
    flat3=stationary.rolling(3,min_periods=3).sum()>=3
    bid.loc[flat3,["o","h","l","c"]]=np.nan
    bid=bid.dropna()
    assert len(bid)>150000,(year,len(bid))
    assert bid.index.is_monotonic_increasing and bid.index.is_unique
    provenance={"source":"THIRD_PARTY_GITHUB_DUKASCOPY_DERIVED_XAUUSD_M1_BID_ASK",
        "repository":REPO,"commit":PIN,"source_SHA256_monthly":hashes,
        "data_through":"2026-08-20" if year==2026 else f"{year}-12-31",
        "nonmatching_bid_ask_minutes_censored":int(mismatch),
        "ask_bid_spread_mean":float(observed.mean()),
        "ask_bid_spread_p95":float(observed.quantile(.95)),
        "flat_minutes_censored":int(flat3.sum()),
        "nontrading_minutes_removed":int(closed.sum()),
        "limitations":["Independent secondary archive, not Dukascopy API direct or FP Markets cTrader",
            "Cannot equate results to HistData frozen benchmarks",
            "Bid-only mid-proxy outcome; measured ask-bid spread is descriptive, NOT actually applied at entry or exit",
            "Weekends/nontrading padded quotes removed; other vendor forward-fills may remain",
            "2026 archive ends Aug 20 and cannot measure 2026 Sep-Nov",
            "Source locked to GitHub commit; SHA256s recorded for every month"]}
    return bid,provenance
if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--year",type=int,choices=range(2022,2027),required=True)
    z=p.parse_args()
    engine.source_data=lambda asset,year:acquire(year)
    engine.run("XAU",z.year)
