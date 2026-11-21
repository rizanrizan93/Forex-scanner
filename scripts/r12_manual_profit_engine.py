"""RIZAN R12 Manual Profit Engine research prototype.
NO live broker calls. Every feature available before candidate trade entry.
Trade entry next H1 open; SL/TP first-touch on following 4 consecutive H1 bars.
When SL and TP touch in same H1 bar, conservatively assign SL first.
Zero forward-data feature exposure, but 2024-26 is NOT pristine holdout.
"""
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from r10_million import load,ohlc_indicators,wilson
from r102_calibrated import context
O=Path("artifacts");O.mkdir(exist_ok=True)
FAMILIES=("EMA_PULLBACK","LIQUIDITY_SWEEP","RETEST_DISCOUNT","CONTINUATION")
SESSIONS=("ALL","LONDON","NY","OVERLAP")
SIDES=("BUY","SELL")
COSTS=(0.7,1.5,3.0)  # USD/oz sensitivity SCENARIOS, not verified cTrader costs
def finite(a):
    return np.asarray(np.isfinite(np.asarray(a,dtype=float)),dtype=bool)
def build():
    h=load("1h");four=load("4h")
    z=ohlc_indicators(h);context(z,h,1)
    z4=ohlc_indicators(four)
    d4=z4[["ema8","ema21","di","adx14","atr14"]].copy()
    d4.index=d4.index+pd.Timedelta(hours=4) # strictly CLOSED H4
    v=d4.reindex(h.index+pd.Timedelta(hours=1),method="ffill")
    for name in ["ema8","ema21","di","adx14","atr14"]:
        z["h4_"+name]=v[name].to_numpy()
    # Future bars used ONLY in outcome computation. Four consecutive one-hour bars
    # after last closed signal candle are required.
    t=h.index.to_series()
    contiguous=np.ones(len(h),bool)
    for j in range(1,5):
        contiguous &= ((t.shift(-j)-t)==pd.Timedelta(hours=j)).to_numpy()
    valid=contiguous & finite(z.atr14) & finite(z.h4_adx14) & finite(z.d1_mom) & finite(z.w1_mom)
    valid &= (z.atr14>0).to_numpy()
    return h,z,valid
def pattern(z,side,family):
    s=1 if side=="BUY" else -1
    c=z.c;o=z.o;at=z.atr14
    ema=z.ema21
    if family=="EMA_PULLBACK":
        touch = (z.l<=ema)&(z.h>=ema)
        recover = s*(c-ema)>0
        return (touch&recover&(s*z.clv>0.0)).to_numpy()
    if family=="LIQUIDITY_SWEEP":
        return (s*z.sweep5>0).to_numpy()
    if family=="RETEST_DISCOUNT":
        edge=z.discount<.40 if s==1 else z.discount>.60
        return (edge & (s*z.body>0)&((c-ema).abs()<=1.5*at)).to_numpy()
    if family=="CONTINUATION":
        return ((s*z.body>.3)&(s*z.di>0)&
                (s*z.roc3>0)&((c-ema).abs()<=1.8*at)).to_numpy()
    raise ValueError(family)
def qualifies(z,side,family,adx,context_gate,session):
    s=1 if side=="BUY" else -1
    m=pattern(z,side,family)
    m &= (s*(z.h4_ema8-z.h4_ema21)>0).to_numpy()
    m &= (s*z.h4_di>0).to_numpy()
    m &= (z.h4_adx14>=adx).to_numpy()
    if context_gate==1:m &= (s*z.d1_mom>0).to_numpy()
    if context_gate==2:m &= ((s*z.d1_mom>0)&(s*z.w1_mom>0)).to_numpy()
    hr=z.index.hour
    if session=="LONDON":m &= (hr>=7)&(hr<16)
    if session=="NY":m &= (hr>=13)&(hr<22)
    if session=="OVERLAP":m &= (hr>=13)&(hr<17)
    return m
def simulate(h,z,valid,mask,side,stop_atr,rr,period,cost=0.7):
    s=1 if side=="BUY" else -1
    eligible=np.flatnonzero(mask & valid & period)
    if not len(eligible):
        return {"n":0,"win_rate":None,"profit_factor":None,"mean_R":None,
                "net_mean_R":None,"mfe10_1h_pct":None,"mean_holding_hours":None,
                "worst_drawdown_R":None}
    op=h.o.to_numpy(float);hi=h.h.to_numpy(float);lo=h.l.to_numpy(float);cl=h.c.to_numpy(float)
    atr=z.atr14.to_numpy(float)
    risk=np.maximum(atr[eligible]*stop_atr,1e-5)
    entry=op[eligible+1]
    sl=entry-s*risk;tp=entry+s*risk*rr
    # All OHLC at future offsets are *outcomes*, never predictor features.
    pnl=np.zeros(len(eligible),float);exit_hour=np.full(len(eligible),4,dtype=int)
    active=np.ones(len(eligible),bool)
    mfe=np.maximum(0,s*(np.where(s==1,hi[eligible+1],lo[eligible+1])-entry))
    for k in range(1,5):
        h_k=hi[eligible+k];l_k=lo[eligible+k]
        hit_sl=(l_k<=sl) if s==1 else (h_k>=sl)
        hit_tp=(h_k>=tp) if s==1 else (l_k<=tp)
        # Conservative for unknown intrabar order: SL first.
        close_sl=active&hit_sl
        pnl[close_sl]=-risk[close_sl]
        exit_hour[close_sl]=k
        active[close_sl]=False
        close_tp=active&hit_tp
        pnl[close_tp]=rr*risk[close_tp]
        exit_hour[close_tp]=k
        active[close_tp]=False
    pnl[active]=s*(cl[eligible[active]+4]-entry[active])
    net_R=(pnl-cost)/risk;raw_R=pnl/risk
    gross_pos=pnl[pnl>0].sum();gross_neg=pnl[pnl<0].sum()
    # Scenario compares all opportunities even if signals overlap. To protect actual
    # portfolio reporting, NON-OVERLAPPING sub-selection is also reported below.
    curve=np.cumsum(net_R);dd=np.maximum.accumulate(np.r_[0,curve])[1:]-curve
    return {"n":len(eligible),"win_rate":round(float((net_R>0).mean()),5),
        "gross_win_rate":round(float((raw_R>0).mean()),5),
        "profit_factor":round(float(gross_pos/max(1e-10,-gross_neg)),5),
        "mean_R":round(float(raw_R.mean()),6),
        "net_mean_R":round(float(net_R.mean()),6),
        "net_median_R":round(float(np.median(net_R)),6),
        "net_total_R":round(float(net_R.sum()),4),
        "mfe10_1h_pct":round(float((mfe>=10).mean()),5),
        "mean_holding_hours":round(float(exit_hour.mean()),4),
        "worst_drawdown_R":round(float(dd.max()),4),
        "avg_entry_risk_usd_oz":round(float(risk.mean()),4)}
def audit_prefix(h,z,valid):
    # Strict context historical-prefix causality audit, not merely calendar lag.
    check=np.flatnonzero(valid & (h.index.year>=2020))
    idx=check[np.linspace(0,len(check)-1,min(12,len(check)),dtype=int)]
    from r10_million import ohlc_indicators
    from r102_calibrated import context
    errors=[]
    for i in idx:
        end=h.index[i]+pd.Timedelta(hours=1)
        subset=h.loc[h.index<=h.index[i]]
        px=ohlc_indicators(subset)
        context(px,subset,1)
        # H4 features check using only current and prior H1 bars (no future).
        h4=subset.resample("4h",label="left",closed="left").agg(o=("o","first"),h=("h","max"),l=("l","min"),c=("c","last"),n=("c","count"))
        h4=h4[h4.n>=4]
        if len(h4)>50:
            h4z=ohlc_indicators(h4)
            h4z.index=h4z.index+pd.Timedelta(hours=4)
            w=h4z.reindex([end],method="ffill")
            # skip H4 compare if canonical full data had partial bars; test 1st.
            for col in ["ema8","ema21","di","adx14"]:
                lhs=float(z.iloc[i]["h4_"+col]);rhs=float(w.iloc[0][col])
                if not np.isclose(lhs,rhs,rtol=1e-7,atol=1e-7,equal_nan=True):
                    errors.append({"i":int(i),"feature":"h4_"+col,"full":lhs,"prefix":rhs})
        for col in ["d1_mom","w1_mom","sweep5","discount","atr14","adx14"]:
            a=float(z.iloc[i][col]);b=float(px.iloc[-1][col])
            if not np.isclose(a,b,rtol=1e-8,atol=1e-8,equal_nan=True):
                errors.append({"i":int(i),"feature":col,"full":a,"prefix":b})
    return {"sample_count":len(idx),"errors":errors[:20],"pass":not errors}
def candidates():
    for side in SIDES:
      for family in FAMILIES:
       for adx in [15,20,25]:
        for gate in [0,1,2]:
         for session in SESSIONS:
          for sl in [0.75,1.25]:
           for rr in [1.5,2.5]:
            yield {"side":side,"family":family,"min_h4_adx":adx,"context_gate":gate,
              "session":session,"stop_atr":sl,"reward_to_risk":rr}
def run():
    h,z,valid=build()
    audit=audit_prefix(h,z,valid)
    O.joinpath("r12-manual-causality.json").write_text(json.dumps(audit,indent=2))
    if not audit["pass"]:raise AssertionError("PREFIX CAUSALITY FAILED "+str(audit["errors"][:2]))
    yr=h.index.year
    val=valid&(yr==2023)
    ev=valid&(yr>=2024)&(yr<=2026)
    assert val.sum()>1000 and ev.sum()>1000
    selected={}
    by_side={}
    total=0
    for cfg in candidates():
        total+=1
        side=cfg["side"]
        m=qualifies(z,side,cfg["family"],cfg["min_h4_adx"],cfg["context_gate"],cfg["session"])
        v=simulate(h,z,valid,m,side,cfg["stop_atr"],cfg["reward_to_risk"],val)
        # Limited candidate count and strict min sample in fixed validation.
        if v["n"]<25:continue
        score=v["net_mean_R"]-1.96*min(3.,1/np.sqrt(v["n"])) # penalize thin samples
        obj={"cfg":cfg,"development":v,"score":round(float(score),6)}
        if side not in selected or obj["score"]>selected[side]["score"]:selected[side]=obj
    print(json.dumps({"stage":"model_selected_on_2023_only","enumerated":total,
        "selected":selected}),flush=True)
    for side in SIDES:
        if side not in selected:continue
        obj=selected[side];c=obj["cfg"]
        mask=qualifies(z,side,c["family"],c["min_h4_adx"],c["context_gate"],c["session"])
        obj["evaluation"]={str(cost):simulate(h,z,valid,mask,side,c["stop_atr"],c["reward_to_risk"],ev,cost=cost) for cost in COSTS}
        obj["evaluation_annual"]={str(year):simulate(h,z,valid,mask,side,c["stop_atr"],c["reward_to_risk"],valid&(yr==year)) for year in [2024,2025,2026]}
        obj["evaluation_baseline"]=simulate(h,z,valid,np.ones(len(h),bool),side,c["stop_atr"],c["reward_to_risk"],ev)
        by_side[side]=obj
    summary={"version":"R12","strategy":"manual decision engine candidate only",
      "timeframe":"H4 trend + H1 setup; M5 confirmation NOT yet included",
      "decision_time":"at CLOSE of completed signal H1 bar; entry NEXT H1 bar OPEN",
      "outcome":"first SL/TP hit across NEXT four consecutive H1 OHLC; if both hit same hour SL first; otherwise mark-to-close at hour 4",
      "cost_scenarios_usd_per_oz":list(COSTS),
      "lookahead_audit":audit,
      "source":"R10 immutable HistData H1/H4 bars downloaded from archived 44901264975; 2019-2026",
      "validation":"2023 (selection uses validation only)",
      "evaluation":"2024-2026 (previously inspected; NOT pristine holdout)",
      "configurations_evaluated":total,
      "selected_by_side":by_side,
      "research_only":True,
      "limitations":["2024-26 previously inspected; not untouched holdout",
                     "No actual FP Markets bid/ask/slippage/spread; scenarios only",
                     "4H horizon independent signals can overlap; not realized portfolio backtest",
                     "No M5/M1 reaction confirmation; cannot promise early warning precision",
                     "H1 high/low within each candle have unknown intrabar event order: SL first",
                     "No user broker/trade data and no live execution authority",
                     "Not a proven profitable strategy; selection risk remains"]}
    O.joinpath("r12-manual-profit-engine.json").write_text(json.dumps(summary,indent=2))
    print(json.dumps({"stage":"done","configs":total,"causal":audit["pass"],
       "selected":{s:{"cfg":x["cfg"],"dev":x["development"],
            "eval_0_7":x["evaluation"]["0.7"],"annual":x["evaluation_annual"]} for s,x in by_side.items()}}),flush=True)
if __name__=="__main__":run()
