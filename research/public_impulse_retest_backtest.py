from __future__ import annotations

import json
from io import StringIO

import numpy as np
import pandas as pd
import requests

SOURCES = {
    "EURUSD": "https://raw.githubusercontent.com/getdata-finance/eurusd-5m-ohlcv-forex-historical-data/main/EURUSD_5m.csv",
    "USDJPY": "https://raw.githubusercontent.com/getdata-finance/usdjpy-5m-ohlcv-forex-historical-data/main/USDJPY_5m.csv",
    "AUDUSD": "https://raw.githubusercontent.com/getdata-finance/audusd-5m-ohlcv-forex-historical-data/main/AUDUSD_5m.csv",
    "XAUUSD": "https://raw.githubusercontent.com/getdata-finance/xauusd-5m-ohlcv-metals-historical-data/main/XAUUSD_5m.csv",
}

LOOKBACK = 12
RETEST_BARS = 12
OUTCOME_BARS = 24
IMPULSE_RANGE_ATR = 1.20
IMPULSE_BODY_ATR = 0.80
RETEST_MIN_ATR = 0.10
RETEST_MAX_ATR = 1.25
TARGET_R = 1.5


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def load(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    d = pd.read_csv(StringIO(r.text), parse_dates=["datetime"])
    d = d.dropna(subset=["datetime", "open", "high", "low", "close"]).sort_values("datetime").drop_duplicates("datetime")
    d = d.set_index("datetime")
    prev = d["close"].shift(1)
    tr = pd.concat([(d.high-d.low).abs(), (d.high-prev).abs(), (d.low-prev).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(14).mean()
    for n in (9,20,34,50):
        d[f"e{n}"] = ema(d.close, n)
    d["ema_long"] = (d.e9>d.e20)&(d.e20>d.e34)&(d.e34>d.e50)
    d["ema_short"] = (d.e9<d.e20)&(d.e20<d.e34)&(d.e34<d.e50)
    sep = (d.e9-d.e20).abs()+(d.e20-d.e34).abs()+(d.e34-d.e50).abs()
    d["ema_expand"] = sep > sep.shift(5)*1.05
    # M15 regime proxy from completed bars only.
    m15 = d.resample("15min", label="right", closed="right").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()
    m15["e20"] = ema(m15.close,20); m15["e50"] = ema(m15.close,50)
    m15["slope50"] = m15.e50 - m15.e50.shift(4)
    m15["reg_long"] = (m15.e20>m15.e50)&(m15.slope50>=0)
    m15["reg_short"] = (m15.e20<m15.e50)&(m15.slope50<=0)
    d = d.join(m15[["reg_long","reg_short"]].reindex(d.index, method="ffill"))
    return d.dropna(subset=["atr"])


def events(d: pd.DataFrame, variant: str):
    rows=[]; i=LOOKBACK+60; n=len(d)
    while i < n-RETEST_BARS-OUTCOME_BARS-2:
        atr=float(d.atr.iloc[i]); o=float(d.open.iloc[i]); h=float(d.high.iloc[i]); l=float(d.low.iloc[i]); c=float(d.close.iloc[i])
        if atr<=0: i+=1; continue
        ph=float(d.high.iloc[i-LOOKBACK:i].max()); pl=float(d.low.iloc[i-LOOKBACK:i].min())
        rng=h-l; body=abs(c-o)
        long_break=c>ph; short_break=c<pl
        if not (long_break or short_break): i+=1; continue
        direction=1 if long_break else -1; level=ph if direction==1 else pl
        close_loc=(c-l)/rng if rng>0 else .5
        impulse=(rng>=IMPULSE_RANGE_ATR*atr and body>=IMPULSE_BODY_ATR*atr and ((direction==1 and c>o and close_loc>=.75) or (direction==-1 and c<o and close_loc<=.25)))
        regime=bool(d.reg_long.iloc[i]) if direction==1 else bool(d.reg_short.iloc[i])
        ema_ok=bool(d.ema_long.iloc[i]) if direction==1 else bool(d.ema_short.iloc[i])
        ema_state=ema_ok and bool(d.ema_expand.iloc[i])
        if variant in {"impulse","impulse_regime","impulse_regime_ema"} and not impulse: i+=1; continue
        if variant in {"impulse_regime","impulse_regime_ema"} and not regime: i+=1; continue
        if variant=="impulse_regime_ema" and not ema_state: i+=1; continue
        ret=None
        for j in range(i+1, min(i+1+RETEST_BARS,n-OUTCOME_BARS-1)):
            rc=float(d.close.iloc[j]); rl=float(d.low.iloc[j]); rh=float(d.high.iloc[j])
            depth=(c-rl)/atr if direction==1 else (rh-c)/atr
            accepted=(rc>level if direction==1 else rc<level)
            touched=(depth>=RETEST_MIN_ATR and depth<=RETEST_MAX_ATR)
            if accepted and touched:
                ret=j; break
            # invalid acceptance before valid retest
            if (direction==1 and rc<level-0.25*atr) or (direction==-1 and rc>level+0.25*atr):
                break
        if ret is None: i+=1; continue
        entry=float(d.close.iloc[ret]);
        stop=(level-0.35*atr) if direction==1 else (level+0.35*atr)
        risk=(entry-stop)*direction
        if risk<=0: i=ret+1; continue
        tp=entry+direction*TARGET_R*risk
        outcome=0; exit_k=ret+OUTCOME_BARS
        for k in range(ret+1,min(ret+1+OUTCOME_BARS,n)):
            kh=float(d.high.iloc[k]); kl=float(d.low.iloc[k])
            hit_sl=(kl<=stop) if direction==1 else (kh>=stop)
            hit_tp=(kh>=tp) if direction==1 else (kl<=tp)
            if hit_sl and hit_tp: outcome=-1; exit_k=k; break
            if hit_sl: outcome=-1; exit_k=k; break
            if hit_tp: outcome=1; exit_k=k; break
        if outcome==0:
            fc=float(d.close.iloc[min(ret+OUTCOME_BARS,n-1)])
            r=(fc-entry)*direction/risk
        else: r=TARGET_R if outcome==1 else -1.0
        ts=d.index[ret]
        hour=ts.hour
        session="ASIA" if hour<7 else "LONDON" if hour<12 else "OVERLAP" if hour<16 else "NEW_YORK" if hour<21 else "OFF"
        rows.append({"ts":str(ts),"outcome":outcome,"r":float(r),"session":session,"dir":"LONG" if direction==1 else "SHORT"})
        i=max(i+1,exit_k+1)
    return rows


def stats(rows):
    if not rows: return {"n":0}
    x=pd.DataFrame(rows); dec=x[x.outcome!=0]
    wins=int((dec.outcome==1).sum()); losses=int((dec.outcome==-1).sum());
    return {"n":len(x),"decisive":len(dec),"wins":wins,"losses":losses,"win_rate":round(wins/len(dec),4) if len(dec) else None,"expectancy_r":round(float(x.r.mean()),4),"sum_r":round(float(x.r.sum()),2),"sessions":{k:{"n":len(g),"exp_r":round(float(g.r.mean()),3)} for k,g in x.groupby("session")}}


def split_stats(rows):
    if len(rows)<4: return {"all":stats(rows)}
    cut=max(1,int(len(rows)*0.70)); return {"train70":stats(rows[:cut]),"holdout30":stats(rows[cut:]),"all":stats(rows)}


def main():
    out={"parameters":{"lookback_bars":LOOKBACK,"retest_bars":RETEST_BARS,"outcome_bars":OUTCOME_BARS,"impulse_range_atr":IMPULSE_RANGE_ATR,"impulse_body_atr":IMPULSE_BODY_ATR,"retest_atr":[RETEST_MIN_ATR,RETEST_MAX_ATR],"target_r":TARGET_R},"pairs":{},"aggregate":{}}
    variants=["baseline","impulse","impulse_regime","impulse_regime_ema"]
    agg={v:[] for v in variants}
    for sym,url in SOURCES.items():
        d=load(url); out["pairs"][sym]={"rows":len(d),"from":str(d.index.min()),"to":str(d.index.max()),"variants":{}}
        for v in variants:
            rr=events(d,v); out["pairs"][sym]["variants"][v]=split_stats(rr); agg[v].extend(rr)
    for v in variants:
        agg[v]=sorted(agg[v],key=lambda z:z["ts"]); out["aggregate"][v]=split_stats(agg[v])
    print("PUBLIC_IMPULSE_RETEST_RESULT="+json.dumps(out,separators=(",",":"),sort_keys=True))

if __name__=="__main__": main()
