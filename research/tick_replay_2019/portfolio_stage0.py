"""Research-only technical stage-0 equity replay on REAL DUKASCOPY TICKS.
Not a parity backtest of Rizan Settlement v1.1.1: XAU macro point-in-time
authorization, full EUR virtual feedback, batch stages 1/2, per-child broker ACK,
position repair/settlement, tiered margin are NOT reproduced.
Prices, bid/ask execution, entry sizing, realized cash and interval equity stress
are derived from real tick records; do not present the result as native cBot PF/DD.
"""
import argparse, collections, json, time, gc, math, traceback
import numpy as np
import pandas as pd
from pilot_research import fetch, m1, xau_signals, eur_signals

def timestamp_np(t):
    return t.to_numpy(dtype="datetime64[ns]")

def quote_asof(t,stamp,side):
    ts=timestamp_np(t["timestamp"])
    i=int(np.searchsorted(ts,np.datetime64(stamp.tz_localize(None)),side="right"))-1
    if i<0:return None
    return float(t["bid"].iat[i] if side==1 else t["ask"].iat[i])

def trade_candidate(t,signal,delay=2,fee_multiplier=1):
    ts=timestamp_np(t["timestamp"])
    when=np.datetime64((signal["at"]+pd.Timedelta(seconds=delay)).tz_localize(None))
    pos=int(np.searchsorted(ts,when,side="left"))
    if pos>=len(t):return None
    bid=t.bid.to_numpy();ask=t.ask.to_numpy()
    side=int(signal["side"])
    sym=signal["symbol"];xau=sym=="XAUUSD"
    spread=float(ask[pos]-bid[pos])
    if spread>(1.5 if xau else .00022):return dict(symbol=sym,at=signal["at"],reject="SPREAD_ABOVE_LIMIT")
    slip=(.10 if xau else .00001)*fee_multiplier
    # Extra cost stresses fill slippage, not Dukascopy quoted prices.
    entry=float((ask[pos] if side==1 else bid[pos])+side*slip)
    anchor=signal.get("anchor")
    if xau and side==-1 and anchor is not None:anchor+=spread
    dist=max(.5,2.4*signal["atr"],side*(entry-anchor)) if xau else signal["distance"]
    if not np.isfinite(dist) or dist<=0:return None
    sl=entry-side*dist;tp=entry+side*dist*(5.5 if xau else 10)
    hold=480 if xau else 240
    expiry=min(signal["at"]+pd.Timedelta(minutes=hold),
               signal["at"].normalize()+pd.Timedelta(hours=19,minutes=59 if xau else 60))
    end=int(np.searchsorted(ts,np.datetime64(expiry.tz_localize(None)),side="right"))
    if end<=pos:return None
    quotes=(bid[pos:end] if side==1 else ask[pos:end])
    stop_ix=np.flatnonzero((quotes<=sl) if side==1 else (quotes>=sl))
    take_ix=np.flatnonzero((quotes>=tp) if side==1 else (quotes<=tp))
    # Actual chronological tick that FIRST reaches bracket; gap may exceed stop.
    j=int(min(int(stop_ix[0]) if len(stop_ix) else len(quotes),
              int(take_ix[0]) if len(take_ix) else len(quotes),
              len(quotes)-1))
    full_close=float(quotes[j])
    worst=float(np.min(quotes[:j+1]) if side==1 else np.max(quotes[:j+1]))
    return dict(symbol=sym,at=signal["at"],entry_at=t["timestamp"].iat[pos],exit_at=t["timestamp"].iat[pos+j],
                side=side,entry=entry,exit=full_close,stop=sl,target=tp,dist=dist,worst=worst,
                unit=1 if xau else 1000,per_side_comm=.06 if xau else .03,
                slip=slip,source_fee_multiplier=fee_multiplier,spread=spread)

def run(months, fee_mult=1, initial=100):
    cash=initial;closed_trades=[];peak=initial;dd=0;mae_worst=0
    history={"XAUUSD":pd.DataFrame(),"EURUSD":pd.DataFrame()}
    cooldown_until={"XAUUSD":pd.Timestamp("1970-01-01",tz="UTC")}
    blocked=collections.Counter()
    annual={};monthly={}
    pf_plus=pf_minus=0
    prev_m=None
    for n,month in enumerate(months):
        started=time.monotonic()
        ticks={};bars={};signals=[];expected_size=0
        for sym in ("XAUUSD","EURUSD"):
            t,meta=fetch(sym,month)
            ticks[sym]=t
            expected_size+=meta["bytes"]
            v=m1(t)
            bar=v
            bars[sym]=bar
            if len(history[sym]):
                subset=history[sym]
                calc=pd.concat((subset,v))
                calc=calc[~calc.index.duplicated(keep="last")].sort_index()
            else:calc=v
            candidate=xau_signals(calc) if sym=="XAUUSD" else eur_signals(calc)
            signals.extend(q for q in candidate if q["at"].strftime("%Y-%m")==month)
            # Keep ~45 days for next month's slow indicators.
            history[sym]=calc.loc[calc.index.max()-pd.Timedelta(days=45):].copy()
        signals.sort(key=lambda x:(x["at"],x["symbol"]))
        to_open=[]
        for sig in signals:
            t=ticks[sig["symbol"]]
            d=trade_candidate(t,sig,fee_multiplier=fee_mult)
            if d and "reject" not in d:to_open.append(d)
            else:blocked[(d or {}).get("reject","MISSING_QUOTE")]+=1
        # Proposed exits are determined from future tick quotes independently
        # of sizing, but each decision only observes prior exits and current MTM.
        to_open.sort(key=lambda x:(x["at"],x["symbol"]))
        cash_start=cash;done=[];open_positions=[]
        daycount=collections.Counter()
        for proposed in to_open:
            at=proposed["at"];sym=proposed["symbol"]
            # Settle positions whose exits occurred by the decision time.
            survivors=[]
            for p in open_positions:
                if p["exit_at"]<=at:
                    cash+=p["pnl"]
                    done.append(p)
                    pf_plus+=max(p["pnl"],0)
                    pf_minus+=max(-p["pnl"],0)
                    if p["symbol"]=="XAUUSD" and p["pnl"]<0:
                        cooldown_until["XAUUSD"]=max(cooldown_until["XAUUSD"],p["exit_at"]+pd.Timedelta(days=3))
                else:survivors.append(p)
            open_positions=survivors
            if any(x["symbol"]==sym for x in open_positions):
                blocked["SAME_SYMBOL_ACTIVE"]+=1;continue
            if sym=="XAUUSD":
                if at<cooldown_until["XAUUSD"]:
                    blocked["XAU_COOLDOWN"]+=1;continue
                daykey=at.tz_convert("Asia/Jakarta").strftime("%Y-%m-%d")
                if daycount[daykey]>=6:
                    blocked["XAU_DAILY_LIMIT"]+=1;continue
            equity=cash
            allocated_margin=0;allocated_risk=0
            for p in open_positions:
                quote=quote_asof(ticks[p["symbol"]],at,p["side"])
                if quote is None:continue
                equity+=p["side"]*(quote-p["entry"])*p["volume"]-p["entry_fees"]
                allocated_margin+=p["margin"]
                allocated_risk+=p["risk_reserved"]
            reference=min(cash,equity)
            if reference<=0:
                blocked["NONPOSITIVE_EQUITY"]+=1;continue
            per_unit_risk=proposed["dist"]*proposed["unit"]+proposed["slip"]*proposed["unit"]+2*proposed["per_side_comm"]*fee_mult
            margin_child=proposed["entry"]*proposed["unit"]/200
            if per_unit_risk<=0 or margin_child<=0:continue
            individual=.121 if sym=="XAUUSD" else .2075
            riskleft=max(0,reference*.2075-allocated_risk)
            caprisk=int(min(reference*individual,riskleft)/per_unit_risk+1e-9)
            capmargin=int(max(0,reference*.5-allocated_margin)/margin_child+1e-9)
            qty=min(caprisk,capmargin,2000)
            if sym=="XAUUSD":
                qty=min(qty,max(1,int(cash/102.5)))
            else:
                # EUR F0245 starts with a 40% opening stage; later stages are NOT simulated.
                qty=int(math.floor(qty*.4)) if qty>=1 else 0
            if qty<1:
                blocked["NO_INTEGER_CHILD_WITHIN_BUDGET"]+=1;continue
            if sym=="XAUUSD":daycount[daykey]+=1
            p=proposed.copy()
            p["qty"]=qty;p["volume"]=qty*p["unit"]
            p["entry_fees"]=qty*p["per_side_comm"]*fee_mult
            p["exit_fees"]=p["entry_fees"]
            p["margin"]=qty*margin_child
            p["risk_reserved"]=qty*per_unit_risk
            p["pnl"]=p["side"]*(p["exit"]-p["entry"])*p["volume"]-p["entry_fees"]-p["exit_fees"]
            open_positions.append(p)
        for p in open_positions:
            cash+=p["pnl"]
            done.append(p)
            pf_plus+=max(p["pnl"],0)
            pf_minus+=max(-p["pnl"],0)
            if p["symbol"]=="XAUUSD" and p["pnl"]<0:
                cooldown_until["XAUUSD"]=max(cooldown_until["XAUUSD"],p["exit_at"]+pd.Timedelta(days=3))
        # Compute conservative minute-level joint equity stress from true tick-derived
        # M1 intrabar extremes. Does NOT reconstruct simultaneous exact tick equity.
        minute_start=pd.Timestamp(month+"-01",tz="UTC")
        month_end=minute_start+pd.offsets.MonthBegin(1)
        idx=pd.date_range(minute_start,month_end,freq="min",inclusive="left")
        balance_array=np.full(len(idx),cash_start,dtype=np.float64)
        changes=np.zeros(len(idx)+1,dtype=np.float64)
        floating=np.zeros(len(idx),dtype=np.float64)
        stamps=idx.values
        for p in done:
            ent_i=int(np.searchsorted(stamps,np.datetime64(p["entry_at"].tz_localize(None)),side="right"))-1
            ex_i=int(np.searchsorted(stamps,np.datetime64(p["exit_at"].tz_localize(None)),side="right"))-1
            ent_i=max(0,min(len(idx)-1,ent_i));ex_i=max(0,min(len(idx)-1,ex_i))
            changes[ex_i]+=p["pnl"]
            if ex_i>ent_i:
                series=bars[p["symbol"]]
                mark=series["low"] if p["side"]==1 else series["high"]
                # SELL quote adverse ASK; add conservative contemporaneous spread estimate.
                extra=p["spread"] if p["side"]==-1 else 0
                vals=mark.reindex(idx[ent_i:ex_i],method=None).to_numpy(dtype=float)
                vals=np.where(np.isfinite(vals),vals, p["entry"])
                floating[ent_i:ex_i]+=p["side"]*(vals+extra-p["entry"])*p["volume"]-p["entry_fees"]
        balance_array+=np.cumsum(changes[:-1])
        eq=balance_array+floating
        peaks=np.maximum.accumulate(np.maximum(peak,eq))
        localdd=float(np.max(1-eq/np.maximum(1e-9,peaks)))
        dd=max(dd,localdd)
        peak=max(peak,float(np.max(eq)),cash)
        for p in done:
            closed_trades.append({k:(str(v) if isinstance(v,pd.Timestamp) else (float(v) if isinstance(v,np.floating) else v))
                            for k,v in p.items() if k not in ("source_fee_multiplier",)})
        year=month[:4]
        monthly[month]={"end_balance":round(cash,4),"basket_count":len(done),
                       "xau_baskets":sum(p["symbol"]=="XAUUSD" for p in done),
                       "eur_baskets":sum(p["symbol"]=="EURUSD" for p in done),
                       "signals":len(signals),"max_minute_equity_dd_pct_to_date":round(100*dd,4)}
        annual[year]={"end_balance":round(cash,4),"max_minute_equity_dd_pct_to_date":round(100*dd,4)}
        print("TICK_STAGE0_PROGRESS",month,"signals",len(signals),"closed",len(done),
              "cash",round(cash,3),"DDpct",round(dd*100,3),"downloadMB",round(expected_size/1e6,1),
              "elapsed_s",round(time.monotonic()-started,2),flush=True)
        del ticks,bars,signals,to_open,done,eq,floating,changes,balance_array
        gc.collect()
    return {"report_type":"TICK_TECHNICAL_STAGE0_NOT_FROZEN_CBOT_PARITY",
            "data_source":"Public Dukascopy bid-ask tick via Henrik404 HF Parquet",
            "period_start":months[0],"period_end":months[-1],
            "initial_balance":initial,"leverage_model":200,"fee_multiplier":fee_mult,
            "end_balance_technical_stage0":round(cash,4),
            "max_minute_equity_dd_pct_conservative_tick_m1":round(dd*100,4),
            "profit_factor_stage0":round(pf_plus/pf_minus,4) if pf_minus else None,
            "closed_baskets_stage0":len(closed_trades),"xau_baskets":sum(x["symbol"]=="XAUUSD" for x in closed_trades),
            "eur_baskets":sum(x["symbol"]=="EURUSD" for x in closed_trades),
            "blocked":dict(blocked),"annual":annual,"monthly":monthly,"ledger":closed_trades,
            "limitations":["No original XAU point-in-time macro/event permission (signals only technical)",
            "No EUR virtual fast/slow feedback, no stage 1 and 2 partial adds",
            "No persisted ACK/broker reject/settlement nor account identity gates",
            "2 second first-entry delay only; none for later ACK as there are no later stages",
            "DD combines adverse real-tick M1 extremes, not exact joint-tick portfolio equity",
            "Recalculated rolling 45-day indicator warmup at each monthly transition",
            "Data from Dukascopy not user broker execution feed, linear margin leverage 1:200",
            "One basket per instrument at a time, risk cap 20.75%, XAU cooldown 3d",
            "Performance cannot be equated with $90m native or baseline cBot"]}
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--start",default="2019-01")
    parser.add_argument("--end",default="2019-03")
    parser.add_argument("--out",default="tick_stage0_portfolio.json")
    parser.add_argument("--cost",type=float,default=1)
    a=parser.parse_args()
    mons=pd.period_range(a.start,a.end,freq="M").astype(str).tolist()
    ans=run(mons,fee_mult=a.cost)
    with open(a.out,"w") as f:json.dump(ans,f,indent=2,allow_nan=False)
    print("TICK_STAGE0_COMPLETED",json.dumps({k:v for k,v in ans.items() if k in (
        "period_start","period_end","end_balance_technical_stage0","max_minute_equity_dd_pct_conservative_tick_m1",
        "profit_factor_stage0","closed_baskets_stage0","xau_baskets","eur_baskets")}),flush=True)
if __name__=="__main__":
    main()
