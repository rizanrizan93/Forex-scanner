"""RIZAN R6: conservative 60-minute XAU continuation risk labels.

For a detection at the CLOSE of M1 index i, entry is hypothetical NEXT
M1 OPEN, using a fixed synthetic round-trip XAU cost of $0.50/oz.
No future M1 can affect signal features or initial invalidation.
The target/stop first-touch uses OHLC extremes, with ambiguous
same-minute touches counted ADVERSE first. Not executable FP Markets
fills and no probabilistic or LIVE performance claim.
"""
from __future__ import annotations
from math import isfinite
import pandas as pd

COST_USD_OZ=.50
TARGET_USD_OZ=3.0
ADVERSE_USD_OZ=3.0
HORIZON_MIN=60

def continuation_h1_risk(m1,signal_i,*,side,atr_m5,
                         cost=COST_USD_OZ,horizon=HORIZON_MIN):
    if side not in ("BUY","SELL"):
        raise ValueError("BAD_SIDE")
    if (not isfinite(float(atr_m5)) or atr_m5<=0 or
        not isfinite(float(cost)) or cost<0):
        raise ValueError("BAD_RISK_PARAMS")
    if horizon!=60:
        raise ValueError("R6_FIXED_H1_HORIZON")
    if not isinstance(m1.index,pd.DatetimeIndex) or m1.index.tz is None:
        raise ValueError("UTC_M1_REQUIRED")
    if signal_i<3 or signal_i>=len(m1):
        raise ValueError("SIGNAL_INDEX_INVALID")
    if m1.index.has_duplicates or not m1.index.is_monotonic_increasing:
        raise ValueError("BAD_M1_ORDER")
    prior_with_signal=m1.iloc[signal_i-3:signal_i+1]
    if not (prior_with_signal.index.to_series().diff().iloc[1:]==
            pd.Timedelta(minutes=1)).all():
        raise ValueError("PRE_SIGNAL_M1_GAP")
    path=m1.iloc[signal_i+1:signal_i+1+horizon]
    if (len(path)!=horizon or
        path.index[0]!=m1.index[signal_i]+pd.Timedelta(minutes=1) or
        not (path.index.to_series().diff().iloc[1:]==pd.Timedelta(minutes=1)).all()):
        return {
            "contract":"RIZAN_R6_CONTINUATION_H1_RISK_OBSERVATION",
            "status":"CENSORED_MISSING_CONTIGUOUS_FUTURE_M1",
            "authority_to_trade":False,
        }
    entry=float(path.open.iloc[0])
    sign=1 if side=="BUY" else -1
    prior=m1.iloc[signal_i-3:signal_i]
    # Static invalidation exists at signal close from three PRE-signal
    # closed candles, never updated to a favorable future pivot.
    stop=(float(prior.low.min())-.1*atr_m5 if side=="BUY" else
          float(prior.high.max())+.1*atr_m5)
    if sign*(entry-stop)<=0:
        return {
            "contract":"RIZAN_R6_CONTINUATION_H1_RISK_OBSERVATION",
            "status":"CENSORED_STOP_ON_WRONG_SIDE_OF_ENTRY",
            "authority_to_trade":False,
        }
    highs=path.high.astype(float).to_numpy()
    lows=path.low.astype(float).to_numpy()
    closes=path.close.astype(float).to_numpy()
    if not all(isfinite(float(x)) for x in path[["open","high","low","close"]].to_numpy().ravel()):
        raise ValueError("FUTURE_M1_NONFINITE")
    favorable=highs-entry if side=="BUY" else entry-lows
    adverse=entry-lows if side=="BUY" else highs-entry
    target_ix=next((k for k,m in enumerate(favorable)
                    if m>=TARGET_USD_OZ+cost),None)
    adverse_ix=next((k for k,m in enumerate(adverse)
                     if m>=ADVERSE_USD_OZ),None)
    stop_ix=next((k for k,(high,low) in enumerate(zip(highs,lows))
                  if (low<=stop if side=="BUY" else high>=stop)),None)
    target_first=bool(target_ix is not None and
                      (adverse_ix is None or target_ix<adverse_ix))
    barrier_state=("TARGET_FIRST" if target_first else
                   "ADVERSE_FIRST" if adverse_ix is not None and
                   (target_ix is None or adverse_ix<=target_ix) else
                   "NEITHER")
    frozen_stop_first=bool(stop_ix is not None and
                           (target_ix is None or stop_ix<=target_ix))
    net_end=sign*(float(closes[-1])-entry)-cost
    return {
        "contract":"RIZAN_R6_CONTINUATION_H1_RISK_OBSERVATION",
        "status":"EVALUATED",
        "side":side,
        "signal_at_utc":(m1.index[signal_i]+pd.Timedelta(minutes=1)).isoformat(),
        "entry_next_m1_open_utc":path.index[0].isoformat(),
        "horizon_minutes":horizon,
        "entry_reference_price":round(entry,5),
        "static_prior_three_m1_stop_reference":round(stop,5),
        "initial_stop_distance_usd_oz":round(abs(entry-stop),5),
        "terminal_net_usd_oz":round(float(net_end),5),
        "terminal_direction_correct_after_cost":bool(net_end>0),
        "max_favorable_excursion_net_usd_oz":round(float(max(0,max(favorable)-cost)),5),
        "max_adverse_excursion_usd_oz":round(float(max(adverse)),5),
        "target3_vs_adverse3":barrier_state,
        "static_stop_before_target3":frozen_stop_first,
        "target3_first_minute":None if target_ix is None else target_ix+1,
        "adverse3_first_minute":None if adverse_ix is None else adverse_ix+1,
        "static_stop_first_minute":None if stop_ix is None else stop_ix+1,
        "ambiguous_same_m1_is_adverse":True,
        "cost_assumed_usd_oz":cost,
        "authority_to_trade":False,
        "true_bid_ask_verified":False,
    }
