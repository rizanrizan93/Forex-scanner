"""Independent S8 2026 Jan-Aug XAU retrospective; future years NEVER included in train.
Pinned XAU third-party bid/ask monthly repo. 2026 incomplete as of Aug 20.
"""
from __future__ import annotations
import hashlib,io,json,time,requests,numpy as np,pandas as pd
import snowball_s8_structural_xau as s8

def acquire_2026(year):
    assert year==2026
    session=requests.Session();book={};checks={}
    for side in ("bid","ask"):
        pieces=[];sum_by_month={}
        for month in range(1,9):
            url=(f"https://raw.githubusercontent.com/{s8.gold.REPO}/{s8.gold.PIN}/"
                f"xauusd/{side}/m1/xauusd_{side}_m1_2026_{month:02d}.csv")
            for retry in range(3):
                try:
                    r=session.get(url,timeout=(12,80));r.raise_for_status()
                    break
                except requests.RequestException:
                    if retry==2:raise
                    time.sleep(1+retry)
            raw=r.content
            assert 200_000<len(raw)<6_000_000,(side,month,len(raw))
            t=pd.read_csv(io.BytesIO(raw))
            assert list(t.columns)==["timestamp","open","high","low","close"]
            ix=pd.to_datetime(pd.to_numeric(t.pop("timestamp"),errors="raise").to_numpy(np.int64),
               unit="ms",utc=True)
            assert ix.is_unique and ix.is_monotonic_increasing
            assert ix[0].year==2026 and ix[0].month==month
            assert ix[-1].year==2026 and ix[-1].month==month
            t.index=ix
            pieces.append(t.rename(columns={"open":"o","high":"h","low":"l","close":"c"}).astype(float))
            sum_by_month[str(month)]=hashlib.sha256(raw).hexdigest()
        book[side]=pd.concat(pieces).sort_index()
        checks[side]=sum_by_month
    b=book["bid"];a=book["ask"]
    common=b.index.intersection(a.index)
    assert len(common)>=.95*max(len(b),len(a))
    missing=max(len(b),len(a))-len(common)
    b=b.loc[common];a=a.loc[common]
    v=np.isfinite(b.to_numpy()).all(axis=1)&np.isfinite(a.to_numpy()).all(axis=1)
    v&=(b.l>0)&(a.l>0)
    v&=(b.l<=b[["o","c"]].min(axis=1))&(b.h>=b[["o","c"]].max(axis=1))
    v&=(a.l<=a[["o","c"]].min(axis=1))&(a.h>=a[["o","c"]].max(axis=1))
    v&=(a.o-b.o>=0)&(a.o-b.o<15)
    ny=b.index.tz_convert("America/New_York")
    closed=(ny.dayofweek==5)|((ny.dayofweek==4)&(ny.hour>=17))|(
             (ny.dayofweek==6)&(ny.hour<18))
    v&=~closed
    b=b.loc[v];a=a.loc[v]
    stationary=(b.h==b.l)&(b.o==b.c)&b.c.eq(b.c.shift())
    frozen=stationary.rolling(3,min_periods=3).sum()>=3
    b=b.loc[~frozen];a=a.loc[~frozen]
    d=pd.DataFrame({"bo":b.o,"bh":b.h,"bl":b.l,"bc":b.c,
                    "ao":a.o,"ah":a.h,"al":a.l,"ac":a.c})
    assert d.index.is_unique and d.index.is_monotonic_increasing
    assert len(d)>150000 and (d.index.asi8%60_000_000_000==0).all()
    prov={"provider":"THIRD_PARTY_DUKASCOPY_DERIVED_XAU_M1_BID_ASK",
       "repository":s8.gold.REPO,"commit":s8.gold.PIN,
       "year":2026,"rows":len(d),"month_end":8,
       "full_year":False,"missing_sep_to_dec":True,
       "source_from":"2026-01-01","source_last":str(d.index.max()),
       "bid_ask_unmatched_censored":int(missing),
       "bad_or_closed_minutes_removed":int((~v).sum()),
       "stale_quote_minutes_censored":int(frozen.sum()),
       "monthly_sha256":checks,
       "venue_not_FP_Markets":True,"approximate_minimum_oz":1.,
       "no_native_execution_or_capacity_proof":True}
    return d,prov

if __name__=="__main__":
    s8.gold.source=acquire_2026
    s8.execute(2026)
