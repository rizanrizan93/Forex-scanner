"""R6 liquidity veto A/B replay harness. NEVER trades, never invents data.

Input requirements:
 - Closed XAU M5 OHLC indexed by UTC M5 close timestamps.
 - An independently captured R6 direction ledger with columns
   signal_at, side, macro_received_at, price_received_at.
 - All signal sources must have been ingested no later than signal_at.
 - A trade is *hypothetically* filled at NEXT M5 open; 1 round-trip
   observed/assumed spread subtracted. No broker fill, gap or slippage claim.
Results are descriptive, NOT production authorization or 80% calibration.
"""
from __future__ import annotations
from math import sqrt
import pandas as pd
from .fed_r63_liquidity_stress import assess_liquidity_stress

REQUIRED_SIGNALS={"signal_at","side","macro_received_at","price_received_at"}
REQUIRED_M5={"open","high","low","close"}


def wilson95(wins: int, n: int):
    if n==0:
        return None
    z=1.959963984540054
    p=wins/n
    denominator=1+z*z/n
    return round((p+z*z/(2*n)-z*sqrt((p*(1-p)+z*z/(4*n))/n))/denominator,4)


def _stats(rows):
    n=len(rows)
    if n==0:
        return {"n":0,"correct_pct":None,"wilson95_lower_pct":None,
                "mean_after_spread_points":None,"median_mae_points":None}
    wins=sum(x["correct"] for x in rows)
    return {"n":n, "correct_pct":round(wins/n*100,2),
            "wilson95_lower_pct":round(wilson95(wins,n)*100,2),
            "mean_after_spread_points":round(sum(x["pnl_points"] for x in rows)/n,4),
            "median_mae_points":round(float(pd.Series([x["mae_points"] for x in rows]).median()),4)}


def replay_liquidity_guard(m5: pd.DataFrame, ledger: pd.DataFrame, *,
                           horizon_bars: int=12, spread_points: float=0.0):
    """Compare same point-in-time R6 signals with and without M5 veto.

    Nonoverlap: one candidate per full horizon; no contemporaneous
    compounded trades double counted. MAE computed from future bars
    with high/low (not extrapolated from close); signal generation never
    sees the future bars and trades are not assumed to fill intrabar.
    """
    if not isinstance(m5,pd.DataFrame) or not REQUIRED_M5.issubset(m5.columns):
        raise ValueError("MISSING_M5_COLUMNS")
    if not isinstance(m5.index,pd.DatetimeIndex) or m5.index.tz is None:
        raise ValueError("M5_CLOSE_TIMESTAMPS_MUST_BE_TZ_AWARE")
    if not isinstance(ledger,pd.DataFrame) or not REQUIRED_SIGNALS.issubset(ledger.columns):
        raise ValueError("POINT_IN_TIME_SIGNAL_LEDGER_REQUIRED")
    if isinstance(horizon_bars,bool) or not isinstance(horizon_bars,int) or not 1<=horizon_bars<=288:
        raise ValueError("INVALID_HORIZON")
    if not 0<=spread_points<1000:
        raise ValueError("INVALID_SPREAD")
    d=m5[["open","high","low","close"]].copy()
    d.index=d.index.tz_convert("UTC")
    if d.index.has_duplicates or not d.index.is_monotonic_increasing or d.isna().any().any():
        raise ValueError("BAD_M5_SEQUENCE")
    idx_to_pos={t:i for i,t in enumerate(d.index)}
    signals=ledger.copy()
    for col in ("signal_at","macro_received_at","price_received_at"):
        signals[col]=pd.to_datetime(signals[col],utc=True,errors="raise")
    signals=signals.sort_values("signal_at")
    if signals["signal_at"].duplicated().any():
        raise ValueError("DUPLICATE_SIGNAL_TIMES")
    rows=[]
    unavailable=0
    omitted_overlap=0
    next_allowed=-1
    for _,s in signals.iterrows():
        t=s["signal_at"]
        side=s["side"]
        if side not in ("BUY","SELL"):
            raise ValueError("INVALID_SIDE")
        if s["macro_received_at"]>t or s["price_received_at"]>t:
            raise ValueError("NON_CAUSAL_SIGNAL_SOURCE")
        pos=idx_to_pos.get(t)
        if pos is None or pos<35 or pos+1+horizon_bars>len(d):
            unavailable+=1
            continue
        if pos<next_allowed:
            omitted_overlap+=1
            continue
        # No missing M5 around signal or throughout future testing.
        sample=d.iloc[pos-35:pos+1+horizon_bars]
        if not (sample.index.to_series().diff().dropna()==pd.Timedelta(minutes=5)).all():
            unavailable+=1
            continue
        # Critical: the filter sees ONLY data through signal time.
        context=d.iloc[:pos+1]
        guard=assess_liquidity_stress(context,now=t)
        if guard["state"]=="UNKNOWN":
            unavailable+=1
            continue
        direction=1 if side=="BUY" else -1
        fill=float(d.open.iloc[pos+1])
        end=float(d.close.iloc[pos+horizon_bars])
        future=d.iloc[pos+1:pos+horizon_bars+1]
        pnl=direction*(end-fill)-spread_points
        adverse=(fill-float(future.low.min()) if direction==1
                 else float(future.high.max())-fill)
        favorable=(float(future.high.max())-fill if direction==1
                   else fill-float(future.low.min()))
        rows.append({
            "signal_at":t.isoformat(),"side":side,"guard_state":guard["state"],
            "guard_veto":guard["risk_veto"],"entry_next_open":fill,
            "exit_horizon_close":end,"pnl_points":pnl,
            "correct":pnl>0,
            "mae_points":round(max(0.,adverse),5),
            "mfe_points":round(max(0.,favorable),5),
        })
        next_allowed=pos+horizon_bars+1
    allowed=[x for x in rows if not x["guard_veto"]]
    blocked=[x for x in rows if x["guard_veto"]]
    return {
        "contract":"RIZAN_R6_PAIRED_LIQUIDITY_VETO_REPLAY_RESEARCH_ONLY_V1",
        "status":"EVALUATED" if rows else "INSUFFICIENT_PAIRED_SIGNALS",
        "scope":"EXTERNAL_POINT_IN_TIME_R6_SIGNALS_ONLY_NOT_GENERATED_BY_REPLAYER",
        "horizon_m5_bars":horizon_bars,"spread_points_assumed":spread_points,
        "excluded_missing_or_noncausal_data":unavailable,
        "excluded_overlapping_signals":omitted_overlap,
        "candidate_baseline":_stats(rows),
        "candidate_guarded":_stats(allowed),
        "blocked":_stats(blocked),
        "blocked_losers":sum(not x["correct"] for x in blocked),
        "blocked_winners":sum(x["correct"] for x in blocked),
        "coverage_pct":round(100*len(allowed)/len(rows),2) if rows else None,
        "per_side":{
            side:{"baseline":_stats([x for x in rows if x["side"]==side]),
                  "guarded":_stats([x for x in allowed if x["side"]==side])}
            for side in ("BUY","SELL")
        },
        "sample_years":sorted({int(x["signal_at"][:4]) for x in rows}),
        "validated_live_80pct":False,
        "usable_for_auto_trading":False,
        "events":rows,
    }
