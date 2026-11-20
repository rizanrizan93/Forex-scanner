"""R6.5 price-only *diagnostic*, not the full macro/news forecast.

Real historical M1 from a public secondary data vendor may be resampled
as closed M5/M15/H1/H4. Precisely the currently frozen R6 price-bias
and liquidity-screen algorithms are applied with as-of bars only.
Macro, OIS, DXY, calendar, broker spreads and receipt-time provenance
ARE NOT available; NEVER report this as live R6.5 forecast accuracy.

Historical observations, not proof of profitable trading.
"""
from __future__ import annotations
from collections import Counter
from math import sqrt
import pandas as pd

from .fed_r6_manual_entry_areas import _bias
from .fed_r63_liquidity_stress import assess_liquidity_stress

CONTRACT="RIZAN_R65_HISTDATA_PRICE_ONLY_4H_DIAGNOSTIC_V1"


def _tf(m1, minutes):
    # Original historical timestamps label the M1 OPEN.
    grouper=m1.resample(f"{minutes}min",label="right",closed="left")
    bar=grouper.agg({"open":"first","high":"max","low":"min","close":"last"})
    counts=grouper["close"].count()
    bar=bar[counts==minutes]
    return bar


def _bias_series(bars):
    # Identical to R6._bias: 20-period EMA, compare last with 3 bars ago.
    ema=bars.close.ewm(span=20,adjust=False,min_periods=20).mean()
    out=pd.Series("MIXED",index=bars.index,dtype="object")
    out[(bars.close>ema)&(ema>ema.shift(3))]="BUY"
    out[(bars.close<ema)&(ema<ema.shift(3))]="SELL"
    out.iloc[:23]="UNKNOWN"
    return out


def _statistics(rows,spread):
    n=len(rows)
    if not n:
        return {"n":0,"wins":0,"accuracy_pct":None,
                "wilson95_lower_pct":None,"mean_net_usd_per_oz":None,
                "median_mae_usd_per_oz":None}
    pnls=[(1 if x["side"]=="BUY" else -1)*(
        x["exit_close"]-x["next_open"])-spread for x in rows]
    wins=sum(p>0 for p in pnls)
    p=wins/n
    z=1.959963984540054
    d=1+z*z/n
    lower=(p+z*z/(2*n)-z*sqrt((p*(1-p)+z*z/(4*n))/n))/d
    return {
        "n":n,"wins":wins,"accuracy_pct":round(100*p,2),
        "wilson95_lower_pct":round(100*lower,2),
        "mean_net_usd_per_oz":round(sum(pnls)/n,4),
        "median_mae_usd_per_oz":round(
            float(pd.Series([x["mae_usd_per_oz"] for x in rows]).median()),4),
    }


def audit_price_only_four_hours(source_m1, *, year, month, spreads=(0.0,0.4,1.0)):
    """Prospective-as-of cohort with paired stress veto and 48 closed-M5 horizon.

    One *baseline* candidate per 4h window so adding a guard does not
    cherry-pick a different candidate population. Guarded subset is
    observed on exactly those same baseline candidates.
    """
    if not isinstance(source_m1,pd.DataFrame) or not {
        "open","high","low","close"}.issubset(source_m1.columns):
        raise ValueError("M1_OHLC_REQUIRED")
    if not isinstance(source_m1.index,pd.DatetimeIndex) or source_m1.index.tz is None:
        raise ValueError("UTC_AWARE_M1_OPEN_REQUIRED")
    d=source_m1[["open","high","low","close"]].copy()
    d.index=d.index.tz_convert("UTC")
    if (d.index.has_duplicates or not d.index.is_monotonic_increasing
        or d.isna().any().any()):
        raise ValueError("NON_MONOTONIC_OR_MISSING_OHLC")
    if not ((d.low>0)&(d.low<=d[["open","close"]].min(axis=1))&
            (d.high>=d[["open","close"]].max(axis=1))).all():
        raise ValueError("INVALID_M1_OHLC")
    bars={m:_tf(d,m) for m in (5,15,60,240)}
    m5,m15,h1,h4=[bars[k] for k in (5,15,60,240)]
    if len(m5)<150 or len(h4)<24:
        return {"contract":CONTRACT,"status":"INSUFFICIENT_HISTORY",
                "source_m1_rows":len(d),"year":year,"month":month}
    signals={m:_bias_series(b) for m,b in bars.items() if m!=5}
    pos={k:i for i,k in enumerate(m5.index)}
    sig15=signals[15]
    sig1h=signals[60].reindex(m15.index,method="ffill")
    sig4h=signals[240].reindex(m15.index,method="ffill")
    next_allowed=-1
    skipped=Counter()
    entries=[]
    for t in m15.index:
        if t.year!=year or t.month!=month:
            continue
        i=pos.get(t)
        if i is None or i<36 or i+48>=len(m5):
            skipped["insufficient_window"]+=1
            continue
        if i<next_allowed:
            skipped["overlap"]+=1
            continue
        side=sig15.loc[t]
        if side not in ("BUY","SELL") or sig1h.loc[t]!=side:
            skipped["h1_m15_not_aligned"]+=1
            continue
        h4side=sig4h.loc[t]
        if h4side in ("BUY","SELL") and h4side!=side:
            skipped["h4_opposes"]+=1
            continue
        # Validate M5 continuity throughout predecision and 4h future.
        window=m5.index[i-35:i+49]
        if not (window.to_series().diff().iloc[1:]==pd.Timedelta(minutes=5)).all():
            skipped["gap"]+=1
            continue
        guard=assess_liquidity_stress(m5.iloc[i-35:i+1],now=t)
        if guard["state"]=="UNKNOWN":
            skipped["invalid_guard"]+=1
            continue
        nxt=float(m5.open.iloc[i+1])
        exit_price=float(m5.close.iloc[i+48])
        future=m5.iloc[i+1:i+49]
        mae=max(0.0, nxt-float(future.low.min()) if side=="BUY"
                else float(future.high.max())-nxt)
        entries.append({
            "signal_at":t.isoformat(),"side":side,
            "next_open":nxt,"exit_close":exit_price,
            "mae_usd_per_oz":mae,
            "liquidity_state":guard["state"],
            "veto":bool(guard["risk_veto"]),
        })
        next_allowed=i+49
    eligible=[r for r in entries if not r["veto"]]
    blocked=[r for r in entries if r["veto"]]
    result={
        "contract":CONTRACT,"status":"PRICE_ONLY_DIAGNOSTIC",
        "source":"HISTDATA_XAUUSD_M1_PUBLIC_SECONDARY_MARKET_DATA",
        "source_m1_rows":len(d),"complete_m5_rows":len(m5),
        "year":year,"month":month,"forecast_horizon_minutes":240,
        "candidate_count":len(entries),"guarded_count":len(eligible),
        "blocked_count":len(blocked),
        "coverage_pct":round(100*len(eligible)/len(entries),2) if entries else None,
        "reasons_skipped":dict(skipped),
        "liquidity_veto_distribution":dict(Counter(
            x["liquidity_state"] for x in blocked)),
        "historical_macro_dxy_yield_verified":False,
        "calendar_verified":False,
        "independent_vendor_bid_ask_verified":False,
        "broker_execution_evidence":False,
        "R65_full_engine_forecast_backtested":False,
        "execution_authority":False,
        "sample_definition":"baseline H1/M15 EMA20 agreement + H4 veto; 4h nonoverlap",
        "cohorts":{},
    }
    for spread in spreads:
        key=str(spread)
        result["cohorts"][key]={
            "baseline":_statistics(entries,spread),
            "guarded":_statistics(eligible,spread),
            "blocked":_statistics(blocked,spread),
            "blocked_losers":sum(
                (1 if x["side"]=="BUY" else -1)*
                (x["exit_close"]-x["next_open"])-spread<=0 for x in blocked),
            "blocked_winners":sum(
                (1 if x["side"]=="BUY" else -1)*
                (x["exit_close"]-x["next_open"])-spread>0 for x in blocked),
            "buy_baseline":_statistics([x for x in entries if x["side"]=="BUY"],spread),
            "sell_baseline":_statistics([x for x in entries if x["side"]=="SELL"],spread),
            "buy_guarded":_statistics([x for x in eligible if x["side"]=="BUY"],spread),
            "sell_guarded":_statistics([x for x in eligible if x["side"]=="SELL"],spread),
        }
    return result
