from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade
from .models import Bar, ensure_utc
from .research_xau_margin_leverage_v21 import LeverageTier
from .research_xau_multihorizon_100usd_v20 import (
    BrokerLotSpec,
    _d1_cost_r,
    _daily_frame,
)

RESEARCH_VERSION="XAU_SETUP_STRENGTH_SIZING_V32"
ARTIFACT_CONTRACT="XAU_SETUP_STRENGTH_SIZING_V32_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
DIAGNOSTIC_ONLY=True

ACCOUNT_LEVERAGE=100.0
MARGIN_FLOOR_PCT=150.0
MIN_LOT=0.01
MAX_LOT=0.10
PERCENTILE_LOOKBACK=252
PERCENTILE_MIN_OBS=126

LOT_MAPS={
    "FIXED_001":((101.0,0.01),),
    "FLEX_CONSERVATIVE":(
        (50.0,0.01),(65.0,0.02),(80.0,0.03),(90.0,0.04),(101.0,0.05),
    ),
    "FLEX_001_TO_010":(
        (50.0,0.01),(65.0,0.02),(80.0,0.03),(90.0,0.05),(101.0,0.10),
    ),
}


@dataclass(frozen=True,slots=True)
class ScoredTrade:
    trade:TournamentTrade
    score:float
    trend_distance_pct:float
    momentum_pct:float
    slope_alignment_pct:float


def _prior_percentile(values:Sequence[float|None],i:int,*,lookback:int=PERCENTILE_LOOKBACK)->float|None:
    if i<=0:
        return None
    raw=values[i]
    if raw is None or not isfinite(float(raw)):
        return None
    lo=max(0,i-lookback)
    prior=[
        float(x) for x in values[lo:i]
        if x is not None and isfinite(float(x))
    ]
    if len(prior)<PERCENTILE_MIN_OBS:
        return None
    value=float(raw)
    return sum(x<=value for x in prior)/len(prior)


def _desired_lot(score:float,map_id:str)->float:
    mapping=LOT_MAPS[map_id]
    for upper,lot in mapping:
        if float(score)<float(upper):
            return float(lot)
    return float(mapping[-1][1])


def _symbol_leverage(tiers:Sequence[LeverageTier],notional:float)->float|None:
    if not tiers:
        return None
    for tier in tiers:
        if notional<=float(tier.max_usd_volume):
            return float(tier.leverage)
    return float(tiers[-1].leverage)


def _classic_scored_trades(rows:Sequence[Bar],*,costs,pip_size:float)->tuple[ScoredTrade,...]:
    d1=_daily_frame(rows)
    n=len(d1)
    if n<500:
        return ()

    trend_distance=[None]*n
    momentum_distance=[None]*n
    slope_strength=[None]*n
    slope_signed=[None]*n

    for i in range(n):
        atr=float(d1.loc[i,"atr14"]) if isfinite(float(d1.loc[i,"atr14"])) else float("nan")
        ema=float(d1.loc[i,"ema200"]) if isfinite(float(d1.loc[i,"ema200"])) else float("nan")
        close=float(d1.loc[i,"close"])
        if isfinite(atr) and atr>0 and isfinite(ema):
            trend_distance[i]=abs(close-ema)/atr
        if i>=60 and isfinite(atr) and atr>0:
            momentum_distance[i]=abs(close-float(d1.loc[i-60,"close"]))/atr
        if i>=20 and isfinite(atr) and atr>0 and isfinite(ema):
            prior_ema=float(d1.loc[i-20,"ema200"])
            if isfinite(prior_ema):
                slope=(ema-prior_ema)/atr
                slope_signed[i]=slope
                slope_strength[i]=abs(slope)

    output=[]
    i=0
    while i<n-1:
        direction=int(d1.loc[i,"direction"])
        if direction==0:
            i+=1
            continue
        atr=float(d1.loc[i,"atr14"])
        if not isfinite(atr) or atr<=0:
            i+=1
            continue

        p_trend=_prior_percentile(trend_distance,i)
        p_mom=_prior_percentile(momentum_distance,i)
        p_slope=_prior_percentile(slope_strength,i)
        slope=slope_signed[i]
        if p_trend is None or p_mom is None or p_slope is None or slope is None:
            i+=1
            continue
        aligned=(float(slope)*direction)>0
        p_slope_aligned=float(p_slope) if aligned else 0.0
        score=100.0*(float(p_trend)+float(p_mom)+p_slope_aligned)/3.0

        entry_i=i+1
        entry=float(d1.loc[entry_i,"open"])
        risk=2.0*atr
        stop=entry-direction*risk
        target=entry+direction*2.0*risk
        last_i=min(n-1,entry_i+29)
        gross=None; exit_i=last_i; exit_price=float(d1.loc[last_i,"close"]); reason="TIME_EXIT"
        for j in range(entry_i,last_i+1):
            hi=float(d1.loc[j,"high"]); lo=float(d1.loc[j,"low"])
            stop_hit=lo<=stop if direction>0 else hi>=stop
            target_hit=hi>=target if direction>0 else lo<=target
            if stop_hit:
                gross=-1.0; exit_i=j; exit_price=stop
                reason="STOP_FIRST_AMBIGUOUS" if target_hit else "STOP_HIT"
                break
            if target_hit:
                gross=2.0; exit_i=j; exit_price=target; reason="TARGET_HIT"
                break
        if gross is None:
            exit_price=float(d1.loc[exit_i,"close"])
            gross=direction*(exit_price-entry)/risk
        entry_time=d1.loc[entry_i,"time"]; exit_time=d1.loc[exit_i,"time"]
        cost_r=_d1_cost_r(
            risk_price=risk,entry_time=entry_time,exit_time=exit_time,
            pip_size=pip_size,costs=costs,
        )
        trade=TournamentTrade(
            "V32_D1_TSMOM_CLASSIC_SCORED","XAUUSD","LONG" if direction>0 else "SHORT",
            d1.loc[i,"time"],entry_time,exit_time,i,exit_i,entry,exit_price,atr,
            stop,target,float(gross),float(cost_r),float(gross-cost_r),
            int(exit_i-entry_i),reason,
        )
        output.append(ScoredTrade(
            trade=trade,score=float(score),
            trend_distance_pct=float(p_trend),
            momentum_pct=float(p_mom),
            slope_alignment_pct=float(p_slope_aligned),
        ))
        i=exit_i+1
    return tuple(output)


def _r_metrics(values:Sequence[float])->dict[str,Any]:
    vals=[float(x) for x in values]
    if not vals:
        return {"trades":0,"profit_factor":None,"expectancy_r":None,"net_r":0.0,"win_rate":None}
    gp=sum(x for x in vals if x>0)
    gl=-sum(x for x in vals if x<0)
    return {
        "trades":len(vals),
        "profit_factor":None if gl<=0 else gp/gl,
        "expectancy_r":sum(vals)/len(vals),
        "net_r":sum(vals),
        "win_rate":sum(x>0 for x in vals)/len(vals),
    }


def _bucket_label(score:float)->str:
    if score<50: return "00_49"
    if score<65: return "50_64"
    if score<80: return "65_79"
    if score<90: return "80_89"
    return "90_100"


def _score_diagnostics(scored:Sequence[ScoredTrade])->dict[str,Any]:
    labels=("00_49","50_64","65_79","80_89","90_100")
    buckets={k:[] for k in labels}
    for row in scored:
        buckets[_bucket_label(row.score)].append(float(row.trade.net_r))
    payload={k:_r_metrics(v) for k,v in buckets.items()}
    eligible=[payload[k] for k in labels if payload[k]["trades"]>=8 and payload[k]["expectancy_r"] is not None]
    monotonic=bool(len(eligible)>=3 and all(
        float(eligible[i]["expectancy_r"])<=float(eligible[i+1]["expectancy_r"])
        for i in range(len(eligible)-1)
    ))
    low=[float(x.trade.net_r) for x in scored if x.score<65]
    high=[float(x.trade.net_r) for x in scored if x.score>=80]
    return {
        "buckets":payload,
        "monotonic_expectancy":monotonic,
        "high_score_80_plus":_r_metrics(high),
        "low_score_below_65":_r_metrics(low),
        "high_minus_low_expectancy_r":(
            None if not high or not low else sum(high)/len(high)-sum(low)/len(low)
        ),
    }


def _actual_lot(
    desired:float,
    *,
    balance:float,
    trade:TournamentTrade,
    spec:BrokerLotSpec,
    tiers:Sequence[LeverageTier],
)->tuple[float|None,int]:
    lot=round(min(MAX_LOT,max(MIN_LOT,float(desired)))+1e-12,2)
    downgrades=0
    risk_price=abs(float(trade.entry_price)-float(trade.stop_loss))
    while lot>=MIN_LOT-1e-12:
        units=spec.contract_units_per_lot*lot
        notional=abs(float(trade.entry_price))*units
        symbol_lev=_symbol_leverage(tiers,notional)
        effective=ACCOUNT_LEVERAGE if symbol_lev is None else min(ACCOUNT_LEVERAGE,symbol_lev)
        margin=notional/effective
        planned_loss=risk_price*units*(1.0+max(0.0,float(trade.cost_r)))
        worst_equity=balance-planned_loss
        level=float("inf") if margin<=0 else 100.0*worst_equity/margin
        if margin<balance and level>MARGIN_FLOOR_PCT:
            return round(lot,2),downgrades
        lot=round(lot-0.01,2)
        downgrades+=1
    return None,downgrades


def _cash_path(
    scored:Sequence[ScoredTrade],
    *,
    map_id:str,
    spec:BrokerLotSpec,
    tiers:Sequence[LeverageTier],
)->dict[str,Any]:
    balance=100.0; peak=100.0; min_balance=100.0
    max_dd=0.0; max_dd_pct=0.0
    max_losing_streak=0; losing_streak=0
    hit1000_at=None; opened=0; skipped=0; downgrade_count=0
    desired_dist={}; actual_dist={}

    for row in sorted(scored,key=lambda x:ensure_utc(x.trade.entry_at)):
        trade=row.trade
        desired=_desired_lot(row.score,map_id)
        desired_dist[f"{desired:.2f}"]=desired_dist.get(f"{desired:.2f}",0)+1
        lot,downgrades=_actual_lot(
            desired,balance=balance,trade=trade,spec=spec,tiers=tiers
        )
        downgrade_count+=downgrades
        if lot is None:
            skipped+=1
            continue
        actual_dist[f"{lot:.2f}"]=actual_dist.get(f"{lot:.2f}",0)+1
        risk_price=abs(float(trade.entry_price)-float(trade.stop_loss))
        units=spec.contract_units_per_lot*lot
        pnl=float(trade.net_r)*risk_price*units
        balance+=pnl
        opened+=1
        min_balance=min(min_balance,balance)
        peak=max(peak,balance)
        dd=peak-balance
        max_dd=max(max_dd,dd)
        if peak>0:
            max_dd_pct=max(max_dd_pct,100.0*dd/peak)
        if pnl<0:
            losing_streak+=1
            max_losing_streak=max(max_losing_streak,losing_streak)
        else:
            losing_streak=0
        if hit1000_at is None and balance>=1000.0:
            hit1000_at=ensure_utc(trade.exit_at).isoformat()
        if balance<=0:
            break

    return {
        "map_id":map_id,
        "starting_balance_usd":100.0,
        "ending_balance_usd":float(balance),
        "net_profit_usd":float(balance-100.0),
        "return_pct":float((balance/100.0-1.0)*100.0),
        "minimum_realized_balance_usd":float(min_balance),
        "max_realized_drawdown_usd":float(max_dd),
        "max_realized_drawdown_pct":float(max_dd_pct),
        "max_losing_streak":int(max_losing_streak),
        "opened_trades":int(opened),
        "skipped_margin_guard":int(skipped),
        "lot_downgrade_steps":int(downgrade_count),
        "desired_lot_distribution":desired_dist,
        "actual_lot_distribution":actual_dist,
        "hit_1000":bool(hit1000_at is not None),
        "hit_1000_at":hit1000_at,
        "ruin":bool(balance<=0),
        "risk_pct_filter":None,
        "planned_stop_margin_floor_pct":MARGIN_FLOOR_PCT,
    }


def evaluate_v32(
    bars:Sequence[Bar],
    *,
    era_id:str,
    era_start,
    era_end,
    costs,
    pip_size:float,
    broker_spec:BrokerLotSpec,
    leverage_tiers:Sequence[LeverageTier],
)->dict[str,Any]:
    start=ensure_utc(era_start); end=ensure_utc(era_end)
    all_scored=_classic_scored_trades(bars,costs=costs,pip_size=pip_size)
    scored=tuple(
        x for x in all_scored
        if ensure_utc(x.trade.entry_at)>=start and ensure_utc(x.trade.entry_at)<end
    )
    diagnostics=_score_diagnostics(scored)
    paths={
        map_id:_cash_path(scored,map_id=map_id,spec=broker_spec,tiers=leverage_tiers)
        for map_id in LOT_MAPS
    }
    return {
        "research_version":RESEARCH_VERSION,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "live_execution_enabled":False,
        "promotion_eligible":False,
        "diagnostic_only":DIAGNOSTIC_ONLY,
        "era_id":era_id,
        "era_start":start.isoformat(),
        "era_end_exclusive":end.isoformat(),
        "scored_trades":len(scored),
        "score_contract":{
            "causal":True,
            "percentile_lookback_days":PERCENTILE_LOOKBACK,
            "percentile_uses_prior_rows_only":True,
            "components":[
                "abs(close-ema200)/atr14 prior-252 percentile",
                "abs(close-close_60)/atr14 prior-252 percentile",
                "abs(ema200-ema200_20)/atr14 prior-252 percentile if slope aligns with direction, else zero",
            ],
        },
        "lot_maps":{k:list(v) for k,v in LOT_MAPS.items()},
        "score_diagnostics":diagnostics,
        "cash_paths":paths,
        "decision_gate":{
            "flexible_sizing_supported":bool(
                diagnostics["monotonic_expectancy"]
                and diagnostics["high_minus_low_expectancy_r"] is not None
                and float(diagnostics["high_minus_low_expectancy_r"])>0.0
                and not paths["FLEX_001_TO_010"]["ruin"]
            ),
            "note":"Sizing cannot create alpha; flexible lot requires predictive setup-strength ordering.",
        },
    }
