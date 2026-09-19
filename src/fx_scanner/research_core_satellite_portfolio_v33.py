from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

import pandas as pd

from .demo_five_core_router import _ema, _true_ranges, _wilder_ewm
from .models import Bar, ensure_utc

RESEARCH_VERSION="CORE_SATELLITE_PORTFOLIO_V33"
ARTIFACT_CONTRACT="CORE_SATELLITE_PORTFOLIO_V33_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False

SPECS={
    "XAUUSD":{"strategy_id":"D1_TSMOM_60_200_CLASSIC","timeframe":"D1","family":"D1_TSMOM","period":60,"cost_abs":0.4675},
    "AUDJPY":{"strategy_id":"H4_DONCHIAN40_ADX20","timeframe":"H4","family":"H4_DONCHIAN","cost_abs":0.03},
    "GBPJPY":{"strategy_id":"D1_TSMOM_60_200","timeframe":"D1","family":"D1_TSMOM","period":60,"cost_abs":0.035},
    "CADJPY":{"strategy_id":"D1_TSMOM_120_200","timeframe":"D1","family":"D1_TSMOM","period":120,"cost_abs":0.03},
    "USDCAD":{"strategy_id":"H4_DONCHIAN40_ADX20","timeframe":"H4","family":"H4_DONCHIAN","cost_abs":0.0002},
}

PORTFOLIOS={
    "XAU_CORE":("XAUUSD",),
    "SATELLITE_STRONG3":("AUDJPY","GBPJPY","CADJPY"),
    "XAU_PLUS_STRONG3":("XAUUSD","AUDJPY","GBPJPY","CADJPY"),
    "XAU_PLUS_STRONG3_USDCAD":("XAUUSD","AUDJPY","GBPJPY","CADJPY","USDCAD"),
}


@dataclass(frozen=True,slots=True)
class RTrade:
    symbol:str
    strategy_id:str
    entry_at:Any
    exit_at:Any
    direction:str
    gross_r:float
    cost_r:float
    net_r:float
    exit_reason:str


def _resample(rows:Sequence[Bar],rule:str,timeframe:str)->tuple[Bar,...]:
    df=pd.DataFrame({
        "time":[ensure_utc(x.timestamp) for x in rows],
        "open":[float(x.open) for x in rows],
        "high":[float(x.high) for x in rows],
        "low":[float(x.low) for x in rows],
        "close":[float(x.close) for x in rows],
    }).sort_values("time").set_index("time")
    r=df.resample(rule,label="left",closed="left").agg(
        open=("open","first"),high=("high","max"),low=("low","min"),close=("close","last"),
    ).dropna().reset_index()
    symbol=rows[0].symbol
    return tuple(
        Bar(symbol=symbol,timeframe=timeframe,timestamp=row.time.to_pydatetime(),
            open=float(row.open),high=float(row.high),low=float(row.low),close=float(row.close),
            tick_count=1,spread_avg=0.0,spread_max=0.0)
        for row in r.itertuples(index=False)
    )


def _adx_series(bars:Sequence[Bar],period:int=14)->list[float]:
    rows=tuple(bars)
    tr=_true_ranges(rows)
    plus_dm=[0.0]; minus_dm=[0.0]
    for prev,cur in zip(rows[:-1],rows[1:]):
        up=float(cur.high)-float(prev.high)
        down=float(prev.low)-float(cur.low)
        plus_dm.append(up if up>down and up>0 else 0.0)
        minus_dm.append(down if down>up and down>0 else 0.0)
    atr=_wilder_ewm(tr,period)
    plus=_wilder_ewm(plus_dm,period); minus=_wilder_ewm(minus_dm,period)
    dx=[]
    for a,p,m in zip(atr,plus,minus):
        if a<=0:
            dx.append(0.0); continue
        pdi=100.0*p/a; mdi=100.0*m/a; den=pdi+mdi
        dx.append(0.0 if den<=0 else 100.0*abs(pdi-mdi)/den)
    return _wilder_ewm(dx,period)


def _simulate_fixed(
    bars:Sequence[Bar],directions:Sequence[int],*,
    strategy_id:str,cost_abs:float,stop_atr:float,target_r:float,max_hold:int,
)->tuple[RTrade,...]:
    rows=tuple(bars)
    atr=_wilder_ewm(_true_ranges(rows),14)
    out=[]
    i=0
    while i<len(rows)-1:
        direction=int(directions[i]) if i<len(directions) else 0
        if direction==0 or not isfinite(float(atr[i])) or float(atr[i])<=0:
            i+=1; continue
        entry_i=i+1
        entry=float(rows[entry_i].open)
        risk=float(stop_atr)*float(atr[i])
        stop=entry-direction*risk
        target=entry+direction*float(target_r)*risk
        last=min(len(rows)-1,entry_i+int(max_hold)-1)
        gross=None; exit_i=last; reason="TIME"
        for j in range(entry_i,last+1):
            hi=float(rows[j].high); lo=float(rows[j].low)
            stop_hit=lo<=stop if direction>0 else hi>=stop
            target_hit=hi>=target if direction>0 else lo<=target
            if stop_hit:
                gross=-1.0; exit_i=j; reason="STOP_FIRST_AMBIGUOUS" if target_hit else "STOP"; break
            if target_hit:
                gross=float(target_r); exit_i=j; reason="TARGET"; break
        if gross is None:
            exit_px=float(rows[exit_i].close)
            gross=direction*(exit_px-entry)/risk
        cost_r=float(cost_abs)/risk
        out.append(RTrade(
            symbol=rows[0].symbol,strategy_id=strategy_id,
            entry_at=ensure_utc(rows[entry_i].timestamp),exit_at=ensure_utc(rows[exit_i].timestamp),
            direction="LONG" if direction>0 else "SHORT",
            gross_r=float(gross),cost_r=float(cost_r),net_r=float(gross-cost_r),
            exit_reason=reason,
        ))
        i=exit_i+1
    return tuple(out)


def _d1_tsmom(rows:Sequence[Bar],*,period:int,strategy_id:str,cost_abs:float)->tuple[RTrade,...]:
    d1=_resample(rows,"1D","D1")
    closes=[float(x.close) for x in d1]
    ema200=_ema(closes,200)
    direction=[0]*len(d1)
    for i in range(max(200,period),len(d1)):
        mom=closes[i]/closes[i-period]-1.0
        if closes[i]>ema200[i] and mom>0:
            direction[i]=1
        elif closes[i]<ema200[i] and mom<0:
            direction[i]=-1
    return _simulate_fixed(
        d1,direction,strategy_id=strategy_id,cost_abs=cost_abs,
        stop_atr=2.0,target_r=2.0,max_hold=30,
    )


def _h4_donchian(rows:Sequence[Bar],*,strategy_id:str,cost_abs:float)->tuple[RTrade,...]:
    h4=_resample(rows,"4h","H4")
    closes=[float(x.close) for x in h4]
    ema50=_ema(closes,50); ema200=_ema(closes,200)
    adx=_adx_series(h4,14)
    direction=[0]*len(h4)
    for i in range(200,len(h4)):
        prior=h4[i-40:i]
        if len(prior)<40:
            continue
        hi=max(float(x.high) for x in prior)
        lo=min(float(x.low) for x in prior)
        if ema50[i]>ema200[i] and adx[i]>=20.0 and closes[i]>hi:
            direction[i]=1
        elif ema50[i]<ema200[i] and adx[i]>=20.0 and closes[i]<lo:
            direction[i]=-1
    return _simulate_fixed(
        h4,direction,strategy_id=strategy_id,cost_abs=cost_abs,
        stop_atr=1.5,target_r=2.0,max_hold=24,
    )


def _metrics(trades:Sequence[RTrade])->dict[str,Any]:
    vals=[float(x.net_r) for x in sorted(trades,key=lambda x:ensure_utc(x.exit_at))]
    if not vals:
        return {"trades":0,"profit_factor":None,"expectancy_r":None,"net_r":0.0,
                "win_rate":None,"max_dd_r":0.0,"max_losing_streak":0}
    gp=sum(x for x in vals if x>0); gl=-sum(x for x in vals if x<0)
    eq=0.0; peak=0.0; dd=0.0; streak=0; max_streak=0
    for x in vals:
        eq+=x; peak=max(peak,eq); dd=max(dd,peak-eq)
        if x<0:
            streak+=1; max_streak=max(max_streak,streak)
        else:
            streak=0
    return {
        "trades":len(vals),"profit_factor":None if gl<=0 else gp/gl,
        "expectancy_r":sum(vals)/len(vals),"net_r":sum(vals),
        "win_rate":sum(x>0 for x in vals)/len(vals),
        "max_dd_r":dd,"max_losing_streak":max_streak,
    }


def _max_active(trades:Sequence[RTrade])->int:
    events=[]
    for i,t in enumerate(trades):
        events.append((ensure_utc(t.entry_at),1,i))
        events.append((ensure_utc(t.exit_at),-1,i))
    # exits before entries at identical timestamps
    events.sort(key=lambda x:(x[0],x[1]))
    active=0; maximum=0
    for _,delta,_ in events:
        active+=delta; maximum=max(maximum,active)
    return maximum


def _frequency(trades:Sequence[RTrade],trading_dates:Sequence[Any])->dict[str,Any]:
    dates=sorted(set(trading_dates)); counts={d:0 for d in dates}
    for t in trades:
        d=ensure_utc(t.entry_at).date()
        if d in counts: counts[d]+=1
    vals=list(counts.values())
    return {
        "trading_days":len(vals),"mean_trades_per_day":0.0 if not vals else sum(vals)/len(vals),
        "days_ge_1_fraction":0.0 if not vals else sum(x>=1 for x in vals)/len(vals),
        "days_ge_2_fraction":0.0 if not vals else sum(x>=2 for x in vals)/len(vals),
        "max_trades_in_day":0 if not vals else max(vals),
    }


def evaluate_v33(
    datasets:Mapping[str,Sequence[Bar]],*,era_id:str,era_start,era_end
)->dict[str,Any]:
    start=ensure_utc(era_start); end=ensure_utc(era_end)
    trades_by_symbol={}
    for symbol,spec in SPECS.items():
        rows=datasets[symbol]
        if spec["family"]=="D1_TSMOM":
            all_trades=_d1_tsmom(
                rows,period=int(spec["period"]),strategy_id=str(spec["strategy_id"]),
                cost_abs=float(spec["cost_abs"]),
            )
        else:
            all_trades=_h4_donchian(
                rows,strategy_id=str(spec["strategy_id"]),cost_abs=float(spec["cost_abs"]),
            )
        trades_by_symbol[symbol]=tuple(
            x for x in all_trades if ensure_utc(x.entry_at)>=start and ensure_utc(x.entry_at)<end
        )

    xau_dates=sorted({
        ensure_utc(x.timestamp).date() for x in datasets["XAUUSD"]
        if ensure_utc(x.timestamp)>=start and ensure_utc(x.timestamp)<end
    })

    portfolio_results={}
    for pid,symbols in PORTFOLIOS.items():
        trades=tuple(
            sorted(
                [t for symbol in symbols for t in trades_by_symbol[symbol]],
                key=lambda x:(ensure_utc(x.entry_at),x.symbol),
            )
        )
        portfolio_results[pid]={
            "symbols":list(symbols),
            "metrics":_metrics(trades),
            "frequency":_frequency(trades,xau_dates),
            "max_active_positions":_max_active(trades),
        }

    symbol_results={
        symbol:{
            "strategy_id":SPECS[symbol]["strategy_id"],
            "metrics":_metrics(trades),
            "long_metrics":_metrics(tuple(x for x in trades if x.direction=="LONG")),
            "short_metrics":_metrics(tuple(x for x in trades if x.direction=="SHORT")),
        }
        for symbol,trades in trades_by_symbol.items()
    }
    return {
        "research_version":RESEARCH_VERSION,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "live_execution_enabled":False,
        "promotion_eligible":False,
        "era_id":era_id,"era_start":start.isoformat(),"era_end_exclusive":end.isoformat(),
        "portfolio_accounting":"EQUAL_R_RESEARCH_SPACE_NOT_CASH_PNL",
        "symbol_results":symbol_results,
        "portfolio_results":portfolio_results,
        "note":(
            "Frozen broker-supported strategy rules are replayed on Dukascopy H1 and combined "
            "in equal-R research space. This evaluates breadth/diversification, not actual cash "
            "PnL or LIVE sizing."
        ),
    }
