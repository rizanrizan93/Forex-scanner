from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

FX_PATHS = {
    "EURUSD": "Forex-Majors/EURUSD/EURUSD_M15.csv",
    "GBPUSD": "Forex-Majors/GBPUSD/GBPUSD_M15.csv",
    "USDJPY": "Forex-Majors/USDJPY/USDJPY_M15.csv",
    "AUDUSD": "Forex-Majors/AUDUSD/AUDUSD_M15.csv",
    "USDCAD": "Forex-Main/USDCAD/USDCAD_M15.csv",
    "USDCHF": "Forex-Main/USDCHF/USDCHF_M15.csv",
}
XAU_PATH = "Gold-Cash/XAUUSD/XAUUSD_M15.csv"
RAW = "https://raw.githubusercontent.com/simom1/XAUUSD-history/main/{path}"

MAX_HOLD = 64
COOLDOWN = 8
FINAL_HOLDOUT_START = pd.Timestamp("2023-01-01")
FOLDS = [
    ("F1_2016_2017", pd.Timestamp("2016-01-01"), pd.Timestamp("2018-01-01")),
    ("F2_2018_2019", pd.Timestamp("2018-01-01"), pd.Timestamp("2020-01-01")),
    ("F3_2020_2021", pd.Timestamp("2020-01-01"), pd.Timestamp("2022-01-01")),
    ("F4_2022", pd.Timestamp("2022-01-01"), pd.Timestamp("2023-01-01")),
    ("FINAL_2023_PLUS", pd.Timestamp("2023-01-01"), pd.Timestamp("2027-01-01")),
]

STRATEGIES = [
    "DONCHIAN_20_BREAKOUT",
    "DONCHIAN_20_LOWVOL",
    "DONCHIAN_40_LOWVOL",
    "BB_SQUEEZE_BREAKOUT",
    "ASIA_RANGE_LONDON_BREAKOUT",
    "EMA200_TREND_PULLBACK",
    "FOUR_EMA_9_20_34_50_PULLBACK",
    "SMC_SWEEP_DISPLACEMENT_PROXY",
]

@dataclass(frozen=True)
class Spec:
    stop_atr: float
    rr: float
    max_hold: int = MAX_HOLD

SPECS = {
    "DONCHIAN_20_BREAKOUT": Spec(1.5, 2.0),
    "DONCHIAN_20_LOWVOL": Spec(1.5, 2.0),
    "DONCHIAN_40_LOWVOL": Spec(1.5, 2.2),
    "BB_SQUEEZE_BREAKOUT": Spec(1.5, 2.0),
    "ASIA_RANGE_LONDON_BREAKOUT": Spec(0.0, 1.8),
    "EMA200_TREND_PULLBACK": Spec(1.3, 2.0),
    "FOUR_EMA_9_20_34_50_PULLBACK": Spec(1.4, 1.8),
    "SMC_SWEEP_DISPLACEMENT_PROXY": Spec(0.0, 2.0),
}


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(RAW.format(path=path))
    cols = {c.lower().strip(): c for c in df.columns}
    required = {"time", "open", "high", "low", "close"}
    if not required.issubset(cols):
        raise RuntimeError(f"missing columns in {path}: {df.columns.tolist()}")
    out = pd.DataFrame({
        "time": pd.to_datetime(df[cols["time"]], errors="coerce", utc=True).dt.tz_convert(None),
        "open": pd.to_numeric(df[cols["open"]], errors="coerce"),
        "high": pd.to_numeric(df[cols["high"]], errors="coerce"),
        "low": pd.to_numeric(df[cols["low"]], errors="coerce"),
        "close": pd.to_numeric(df[cols["close"]], errors="coerce"),
        "tick_volume": pd.to_numeric(df[cols.get("tick_volume", cols["close"])], errors="coerce"),
    }).dropna(subset=["time","open","high","low","close"])
    out = out.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    return features(out)


def features(x: pd.DataFrame) -> pd.DataFrame:
    x = x.copy()
    pc = x.close.shift(1)
    tr = pd.concat([(x.high-x.low), (x.high-pc).abs(), (x.low-pc).abs()], axis=1).max(axis=1)
    x["atr"] = tr.rolling(14, min_periods=14).mean()
    for p in [9,20,34,50,200]:
        x[f"ema{p}"] = x.close.ewm(span=p, adjust=False).mean()
    delta = x.close.diff()
    up = delta.clip(lower=0).rolling(14, min_periods=14).mean()
    dn = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
    rs = up / dn.replace(0, np.nan)
    x["rsi"] = 100 - 100/(1+rs)
    x.loc[(dn==0)&(up>0), "rsi"] = 100
    x.loc[(up==0)&(dn>0), "rsi"] = 0
    x["hi20"] = x.high.shift(1).rolling(20, min_periods=20).max()
    x["lo20"] = x.low.shift(1).rolling(20, min_periods=20).min()
    x["hi40"] = x.high.shift(1).rolling(40, min_periods=40).max()
    x["lo40"] = x.low.shift(1).rolling(40, min_periods=40).min()
    x["bb_mid"] = x.close.rolling(20, min_periods=20).mean()
    sd = x.close.rolling(20, min_periods=20).std(ddof=0)
    x["bb_up"] = x.bb_mid + 2*sd
    x["bb_dn"] = x.bb_mid - 2*sd
    x["bb_width"] = (x.bb_up-x.bb_dn)/x.bb_mid.replace(0,np.nan)
    x["atr_pct"] = x.atr/x.close.replace(0,np.nan)
    # strictly PIT thresholds: current bar excluded from percentile window
    x["atr_q35"] = x.atr_pct.shift(1).rolling(1500, min_periods=500).quantile(0.35)
    x["bbw_q25"] = x.bb_width.shift(1).rolling(1500, min_periods=500).quantile(0.25)
    body = (x.close-x.open).abs()
    x["body_atr"] = body/x.atr.replace(0,np.nan)
    x["hour"] = x.time.dt.hour
    x["date"] = x.time.dt.date
    return x


def base_records(df: pd.DataFrame, strategy: str) -> list[dict]:
    if strategy == "DONCHIAN_20_BREAKOUT":
        long = (df.close>df.hi20)&(df.close>df.open)&(df.body_atr>=0.35)
        short = (df.close<df.lo20)&(df.close<df.open)&(df.body_atr>=0.35)
    elif strategy == "DONCHIAN_20_LOWVOL":
        lowvol = df.atr_pct.shift(1) <= df.atr_q35.shift(1)
        long = lowvol&(df.close>df.hi20)&(df.close>df.open)&(df.body_atr>=0.30)
        short = lowvol&(df.close<df.lo20)&(df.close<df.open)&(df.body_atr>=0.30)
    elif strategy == "DONCHIAN_40_LOWVOL":
        lowvol = df.atr_pct.shift(1) <= df.atr_q35.shift(1)
        long = lowvol&(df.close>df.hi40)&(df.close>df.open)&(df.body_atr>=0.30)
        short = lowvol&(df.close<df.lo40)&(df.close<df.open)&(df.body_atr>=0.30)
    elif strategy == "BB_SQUEEZE_BREAKOUT":
        squeeze = df.bb_width.shift(1) <= df.bbw_q25.shift(1)
        long = squeeze&(df.close>df.hi20)&(df.close>df.bb_up)&(df.close>df.open)
        short = squeeze&(df.close<df.lo20)&(df.close<df.bb_dn)&(df.close<df.open)
    elif strategy == "EMA200_TREND_PULLBACK":
        long = (df.ema50>df.ema200)&(df.ema20>df.ema50)&(df.low<=df.ema20)&(df.close>df.ema9)&(df.close>df.open)&df.rsi.between(50,68)
        short = (df.ema50<df.ema200)&(df.ema20<df.ema50)&(df.high>=df.ema20)&(df.close<df.ema9)&(df.close<df.open)&df.rsi.between(32,50)
    elif strategy == "FOUR_EMA_9_20_34_50_PULLBACK":
        long = (df.ema9>df.ema20)&(df.ema20>df.ema34)&(df.ema34>df.ema50)&(df.ema9>df.ema9.shift(5))&(df.low<=df.ema20+0.10*df.atr)&(df.close>df.ema9)&(df.close>df.open)
        short = (df.ema9<df.ema20)&(df.ema20<df.ema34)&(df.ema34<df.ema50)&(df.ema9<df.ema9.shift(5))&(df.high>=df.ema20-0.10*df.atr)&(df.close<df.ema9)&(df.close<df.open)
    elif strategy == "SMC_SWEEP_DISPLACEMENT_PROXY":
        # liquidity sweep of prior 20-bar extreme, reclaim, displacement close.
        long = (df.low<df.lo20)&(df.close>df.lo20)&(df.close>df.open)&(df.body_atr>=0.55)&(df.close>df.high.shift(1))
        short = (df.high>df.hi20)&(df.close<df.hi20)&(df.close<df.open)&(df.body_atr>=0.55)&(df.close<df.low.shift(1))
    else:
        raise ValueError(strategy)
    rows=[]
    for d,mask in [("LONG",long),("SHORT",short)]:
        for i in np.flatnonzero(mask.fillna(False).to_numpy()):
            if i<1600 or i+1>=len(df) or not np.isfinite(df.at[i,"atr"]): continue
            rec={"i":int(i),"direction":d,"atr":float(df.at[i,"atr"])}
            if strategy=="SMC_SWEEP_DISPLACEMENT_PROXY":
                rec["stop"] = float(df.at[i,"low"]-0.15*df.at[i,"atr"]) if d=="LONG" else float(df.at[i,"high"]+0.15*df.at[i,"atr"])
            rows.append(rec)
    return cooldown(rows)


def asia_records(df: pd.DataFrame) -> list[dict]:
    rows=[]
    # UTC fixed-window approximation: Asian range 00:00-05:45, trade 06:00-11:45.
    for _,g in df.groupby("date", sort=False):
        asian=g[g.hour<6]
        trade=g[(g.hour>=6)&(g.hour<12)]
        if len(asian)<16 or trade.empty: continue
        hi=float(asian.high.max()); lo=float(asian.low.min()); width=hi-lo
        if width<=0: continue
        # no lookahead: asia session is complete before trade window.
        triggered=False
        for idx,row in trade.iterrows():
            if triggered: break
            if row.close>hi and row.close>row.open and row.body_atr>=0.25:
                rows.append({"i":int(idx),"direction":"LONG","atr":float(row.atr),"stop":lo})
                triggered=True
            elif row.close<lo and row.close<row.open and row.body_atr>=0.25:
                rows.append({"i":int(idx),"direction":"SHORT","atr":float(row.atr),"stop":hi})
                triggered=True
    return cooldown(rows, 1)


def cooldown(rows: list[dict], bars: int=COOLDOWN) -> list[dict]:
    rows=sorted(rows,key=lambda r:r["i"]); out=[]; last=-10**9
    for r in rows:
        if r["i"]-last<bars: continue
        out.append(r); last=r["i"]
    return out


def cost_r(symbol: str, risk: float, atr: float, stress: float) -> float:
    # Relative-cost model: base transaction drag scales inversely with stop size.
    # Base 0.025R approximates spread+slippage+commission for liquid majors;
    # stress adds 0, 0.025R, or 0.075R.
    stop_atr = risk/max(atr,1e-12)
    base = 0.025/max(stop_atr,0.35)
    return base + stress


def simulate(df:pd.DataFrame,symbol:str,strategy:str,r:dict,stress:float=0.0)->dict|None:
    spec=SPECS[strategy]; i=r["i"]; e=i+1
    if e>=len(df): return None
    entry=float(df.at[e,"open"]); atr=float(r["atr"]); d=r["direction"]
    if "stop" in r:
        stop=float(r["stop"]); risk=entry-stop if d=="LONG" else stop-entry
    else:
        risk=spec.stop_atr*atr; stop=entry-risk if d=="LONG" else entry+risk
    if not np.isfinite(risk) or risk<=0 or risk<0.25*atr: return None
    target=entry+spec.rr*risk if d=="LONG" else entry-spec.rr*risk
    last=min(len(df)-1,e+spec.max_hold-1); gross=None; why="TIME"; x=last
    for j in range(e,last+1):
        lo=float(df.at[j,"low"]); hi=float(df.at[j,"high"])
        hs=(lo<=stop) if d=="LONG" else (hi>=stop)
        ht=(hi>=target) if d=="LONG" else (lo<=target)
        if hs and ht: gross=-1.0; why="STOP_FIRST"; x=j; break
        if hs: gross=-1.0; why="STOP"; x=j; break
        if ht: gross=spec.rr; why="TARGET"; x=j; break
    if gross is None:
        px=float(df.at[x,"close"]); gross=(px-entry)/risk if d=="LONG" else (entry-px)/risk
        gross=max(-1.0,min(spec.rr,gross))
    cr=cost_r(symbol,risk,atr,stress)
    return {"strategy":strategy,"symbol":symbol,"signal_at":df.at[i,"time"],"entry_at":df.at[e,"time"],"direction":d,"gross_r":float(gross),"cost_r":float(cr),"net_r":float(gross-cr),"reason":why}


def metrics(g:pd.DataFrame)->dict:
    if g.empty:return {"trades":0}
    pos=g.loc[g.net_r>0,"net_r"].sum(); neg=-g.loc[g.net_r<0,"net_r"].sum()
    eq=g.net_r.cumsum(); peak=np.maximum.accumulate(np.maximum(eq.to_numpy(),0.0)); dd=peak-eq.to_numpy()
    return {"trades":int(len(g)),"avg_r":float(g.net_r.mean()),"net_r":float(g.net_r.sum()),"win_rate":float((g.net_r>0).mean()),"pf":float(pos/neg) if neg>0 else None,"max_dd_r":float(dd.max()) if len(dd) else 0.0}


def bootstrap(g:pd.DataFrame,n=1000,seed=912)->dict:
    if len(g)<20:return {}
    a=g.net_r.to_numpy(); rng=np.random.default_rng(seed); means=[]
    for _ in range(n): means.append(float(rng.choice(a,size=len(a),replace=True).mean()))
    q=np.quantile(means,[.05,.5,.95])
    return {"p_avg_positive":float(np.mean(np.asarray(means)>0)),"avg_r_p05":float(q[0]),"avg_r_p50":float(q[1]),"avg_r_p95":float(q[2])}


def walkforward_rows(trades:pd.DataFrame)->list[dict]:
    out=[]
    for strategy in STRATEGIES:
        s=trades[trades.strategy==strategy]
        for name,start,end in FOLDS:
            g=s[(s.entry_at>=start)&(s.entry_at<end)].sort_values("entry_at").reset_index(drop=True)
            m=metrics(g); b=bootstrap(g)
            out.append({"strategy":strategy,"fold":name,**m,**b})
    return out


def tournament(pathmap:dict[str,str], include_xau=False)->dict:
    all_by_stress={0.0:[],0.025:[],0.075:[]}; coverage={}
    for symbol,path in pathmap.items():
        df=load(path); coverage[symbol]={"rows":len(df),"start":str(df.time.min()),"end":str(df.time.max())}
        recs={s:(asia_records(df) if s=="ASIA_RANGE_LONDON_BREAKOUT" else base_records(df,s)) for s in STRATEGIES}
        for stress in all_by_stress:
            for strategy,rr in recs.items():
                for r in rr:
                    t=simulate(df,symbol,strategy,r,stress)
                    if t is not None: all_by_stress[stress].append(t)
    result={"coverage":coverage,"stress":{}}
    for stress,rows in all_by_stress.items():
        trades=pd.DataFrame(rows)
        if trades.empty: continue
        trades["entry_at"]=pd.to_datetime(trades.entry_at)
        wf=walkforward_rows(trades)
        holdout=[]; pair_holdout=[]
        h=trades[trades.entry_at>=FINAL_HOLDOUT_START]
        for s in STRATEGIES:
            g=h[h.strategy==s].sort_values("entry_at").reset_index(drop=True)
            m=metrics(g); b=bootstrap(g)
            positive_pairs=0; pair_avgs={}
            for symbol in pathmap:
                pg=g[g.symbol==symbol].sort_values("entry_at").reset_index(drop=True)
                pm=metrics(pg); pair_avgs[symbol]=pm.get("avg_r")
                if pm.get("trades",0)>=30 and (pm.get("avg_r") or 0)>0: positive_pairs+=1
                pair_holdout.append({"strategy":s,"symbol":symbol,"stress":stress,**pm})
            holdout.append({"strategy":s,"stress":stress,"positive_pairs":positive_pairs,"pair_avg_r":pair_avgs,**m,**b})
        # robust score prioritizes untouched holdout expectancy, PF, breadth, and bootstrap confidence.
        for r in holdout:
            pf=r.get("pf") or 0; ar=r.get("avg_r") or -99; pp=r.get("positive_pairs",0); p=r.get("p_avg_positive",0)
            r["robust_score"] = float(100*ar + 2*max(0,pf-1) + 0.35*pp + p)
        result["stress"][str(stress)]={"walkforward":wf,"holdout":sorted(holdout,key=lambda r:r["robust_score"],reverse=True),"pair_holdout":pair_holdout}
    return result


def main()->None:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",default="out/stage2_m15"); args=ap.parse_args()
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    fx=tournament(FX_PATHS)
    # XAU is reported separately and never affects the FX ranking.
    xau=tournament({"XAUUSD":XAU_PATH}, include_xau=True)
    payload={"methodology":{"timeframe":"M15","final_holdout":"2023-01-01 onward","folds":[f[0] for f in FOLDS],"cost_stress_r":[0.0,0.025,0.075],"same_bar":"STOP_FIRST","universe":"6 FX majors; XAU separate"},"fx":fx,"xau":xau}
    (out/"summary.json").write_text(json.dumps(payload,indent=2,default=str),encoding="utf-8")
    lines=["# Stage 2 M15 Walk-Forward Tournament","","## FX final holdout 2023+ — base costs","","|Rank|Strategy|Trades|Avg R|Net R|Win %|PF|Max DD|Positive pairs|Bootstrap P(avg>0)|","|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k,r in enumerate(fx["stress"]["0.0"]["holdout"],1):
        pf="NA" if r.get("pf") is None else f"{r['pf']:.3f}"; p=r.get("p_avg_positive",0)
        lines.append(f"|{k}|{r['strategy']}|{r['trades']}|{r.get('avg_r',0):.4f}|{r.get('net_r',0):.2f}|{100*r.get('win_rate',0):.1f}%|{pf}|{r.get('max_dd_r',0):.2f}|{r.get('positive_pairs',0)}/6|{100*p:.1f}%|")
    lines += ["","## Cost stress winner check",""]
    for stress in ["0.0","0.025","0.075"]:
        top=fx["stress"][stress]["holdout"][0]
        lines.append(f"- stress +{stress}R/trade: **{top['strategy']}** avgR={top.get('avg_r',0):.4f}, PF={top.get('pf')}, positive_pairs={top.get('positive_pairs')}/6")
    lines += ["","## XAUUSD separate final holdout",""]
    for r in xau["stress"]["0.0"]["holdout"][:5]:
        lines.append(f"- {r['strategy']}: trades={r['trades']}, avgR={r.get('avg_r',0):.4f}, PF={r.get('pf')}")
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print((out/"report.md").read_text())

if __name__=="__main__": main()
