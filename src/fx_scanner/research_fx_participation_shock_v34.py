from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from statistics import mean, pstdev
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION="FX_PARTICIPATION_SHOCK_H1_V34"
ARTIFACT_CONTRACT="FX_PARTICIPATION_SHOCK_H1_V34_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
DIAGNOSTIC_ONLY=True

SYMBOLS=(
    "EURUSD","GBPUSD","USDJPY","USDCHF","USDCAD","AUDUSD","NZDUSD",
    "EURJPY","GBPJPY","EURGBP","AUDJPY","CADJPY","EURCHF","EURAUD","GBPAUD",
)
DEVELOPMENT_FRACTION=0.70
MAX_ACCOUNT_POSITIONS=10
TIMEFRAME_SECONDS=3600

@dataclass(frozen=True,slots=True)
class ParticipationVariant:
    variant_id:str
    tick_lookback:int
    tick_z_min:float
    body_atr_min:float
    close_location_min:float
    persistence_bars:int
    stop_atr:float
    target_r:float
    max_hold_hours:int
    cooldown_hours:int

VARIANTS=(
    ParticipationVariant("V34_Z15_B050_C075_P1_R125",96,1.5,0.50,0.75,1,1.25,1.25,8,3),
    ParticipationVariant("V34_Z20_B050_C080_P1_R150",96,2.0,0.50,0.80,1,1.25,1.50,10,4),
    ParticipationVariant("V34_Z20_B075_C080_P1_R175",96,2.0,0.75,0.80,1,1.50,1.75,12,4),
    ParticipationVariant("V34_Z25_B075_C085_P1_R200",96,2.5,0.75,0.85,1,1.50,2.00,16,6),
    ParticipationVariant("V34_Z15_B050_C075_P2_R150",48,1.5,0.50,0.75,2,1.25,1.50,10,4),
    ParticipationVariant("V34_Z20_B060_C080_P2_R175",48,2.0,0.60,0.80,2,1.50,1.75,12,6),
)

@dataclass(frozen=True,slots=True)
class ParticipationSignal:
    variant_id:str
    symbol:str
    direction:str
    signal_index:int
    signal_at:Any
    atr:float
    tick_z:float
    body_atr:float
    close_location:float


def _atr_series(rows:Sequence[Bar],period:int=14)->tuple[float|None,...]:
    if len(rows)<period+1:
        return tuple(None for _ in rows)
    tr=[0.0]
    for i in range(1,len(rows)):
        pc=float(rows[i-1].close)
        tr.append(max(
            float(rows[i].high)-float(rows[i].low),
            abs(float(rows[i].high)-pc),
            abs(float(rows[i].low)-pc),
        ))
    out:[float|None]=[None]*len(rows)
    running=sum(tr[1:period+1])/period
    out[period]=running
    for i in range(period+1,len(rows)):
        running=((running*(period-1))+tr[i])/period
        out[i]=running
    return tuple(out)


def _tick_z(rows:Sequence[Bar],lookback:int)->tuple[float|None,...]:
    out:[float|None]=[None]*len(rows)
    for i in range(lookback,len(rows)):
        prior=[float(x.tick_count) for x in rows[i-lookback:i]]
        sigma=pstdev(prior)
        if sigma<=1e-12:
            continue
        out[i]=(float(rows[i].tick_count)-mean(prior))/sigma
    return tuple(out)


def extract_signals(
    rows:Sequence[Bar],*,variant:ParticipationVariant
)->tuple[ParticipationSignal,...]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    if not bars:
        return ()
    atrs=_atr_series(bars)
    ticks=_tick_z(bars,variant.tick_lookback)
    out=[]
    last_i=-10_000
    warm=max(variant.tick_lookback,20)
    for i in range(warm,len(bars)-2):
        if i-last_i<variant.cooldown_hours:
            continue
        bar=bars[i]
        stamp=ensure_utc(bar.timestamp)
        if stamp.hour==21:
            continue
        atr=atrs[i]; z=ticks[i]
        if atr is None or z is None or float(atr)<=0 or float(z)<variant.tick_z_min:
            continue
        rng=float(bar.high)-float(bar.low)
        if rng<=0:
            continue
        body=abs(float(bar.close)-float(bar.open))
        body_atr=body/float(atr)
        if body_atr<variant.body_atr_min:
            continue
        if float(bar.close)>float(bar.open):
            direction="LONG"
            location=(float(bar.close)-float(bar.low))/rng
        elif float(bar.close)<float(bar.open):
            direction="SHORT"
            location=(float(bar.high)-float(bar.close))/rng
        else:
            continue
        if location<variant.close_location_min:
            continue

        if variant.persistence_bars>1:
            ok=True
            for j in range(1,variant.persistence_bars):
                prev=bars[i-j]
                if direction=="LONG" and not float(prev.close)>float(prev.open):
                    ok=False; break
                if direction=="SHORT" and not float(prev.close)<float(prev.open):
                    ok=False; break
            if not ok:
                continue

        out.append(ParticipationSignal(
            variant_id=variant.variant_id,symbol=bars[0].symbol,
            direction=direction,signal_index=i,signal_at=stamp,atr=float(atr),
            tick_z=float(z),body_atr=float(body_atr),close_location=float(location),
        ))
        last_i=i
    return tuple(out)


def _cost_r(*,risk_price:float,bars_held:int,pip_size:float,costs:M15ResearchCosts)->float:
    elapsed_days=max(0,bars_held)*TIMEFRAME_SECONDS/86400.0
    pips=(
        float(costs.spread_pips)*float(costs.spread_multiplier)
        +float(costs.slippage_pips)*float(costs.slippage_multiplier)
        +float(costs.commission_pips_round_trip)
        +float(costs.swap_pips_per_day)*elapsed_days
    )
    return pips/(risk_price/pip_size)


def simulate(
    rows:Sequence[Bar],*,signals:Sequence[ParticipationSignal],
    variant:ParticipationVariant,pip_size:float,costs:M15ResearchCosts,
)->tuple[TournamentTrade,...]:
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    out=[]
    next_free=0
    for s in signals:
        entry_i=s.signal_index+1
        if entry_i<next_free or entry_i>=len(bars):
            continue
        entry=float(bars[entry_i].open)
        risk=float(variant.stop_atr)*float(s.atr)
        if risk<=0:
            continue
        stop=entry-risk if s.direction=="LONG" else entry+risk
        target=entry+variant.target_r*risk if s.direction=="LONG" else entry-variant.target_r*risk
        last=min(len(bars)-1,entry_i+variant.max_hold_hours)
        exit_i=last; exit_px=float(bars[last].close); gross=None; reason="TIME_EXIT"
        for j in range(entry_i,last+1):
            b=bars[j]
            if s.direction=="LONG":
                stop_hit=float(b.low)<=stop; target_hit=float(b.high)>=target
            else:
                stop_hit=float(b.high)>=stop; target_hit=float(b.low)<=target
            if stop_hit:
                gross=-1.0; exit_i=j; exit_px=stop
                reason="STOP_FIRST_AMBIGUOUS" if target_hit else "STOP_HIT"
                break
            if target_hit:
                gross=variant.target_r; exit_i=j; exit_px=target; reason="TARGET_HIT"
                break
        if gross is None:
            gross=(exit_px-entry)/risk if s.direction=="LONG" else (entry-exit_px)/risk
        held=exit_i-entry_i
        cost=_cost_r(risk_price=risk,bars_held=held,pip_size=pip_size,costs=costs)
        out.append(TournamentTrade(
            variant.variant_id,s.symbol,s.direction,s.signal_at,
            ensure_utc(bars[entry_i].timestamp),ensure_utc(bars[exit_i].timestamp),
            s.signal_index,exit_i,entry,exit_px,s.atr,stop,target,
            float(gross),float(cost),float(gross-cost),held,reason,
        ))
        next_free=exit_i+1
    return tuple(out)


def _cap_account(trades:Sequence[TournamentTrade])->tuple[TournamentTrade,...]:
    accepted=[]; active=[]
    for trade in sorted(trades,key=lambda x:(ensure_utc(x.entry_at),x.symbol)):
        entry=ensure_utc(trade.entry_at)
        active=[x for x in active if ensure_utc(x.exit_at)>entry]
        if len(active)>=MAX_ACCOUNT_POSITIONS:
            continue
        accepted.append(trade); active.append(trade)
    return tuple(accepted)


def _frequency(trades:Sequence[TournamentTrade],dates:Sequence[Any])->dict[str,Any]:
    counts={d:0 for d in sorted(set(dates))}
    for t in trades:
        d=ensure_utc(t.entry_at).date()
        if d in counts: counts[d]+=1
    vals=list(counts.values())
    return {
        "trading_days":len(vals),"trades":sum(vals),
        "mean_trades_per_day":0.0 if not vals else sum(vals)/len(vals),
        "days_ge_1_fraction":0.0 if not vals else sum(v>=1 for v in vals)/len(vals),
        "days_ge_3_fraction":0.0 if not vals else sum(v>=3 for v in vals)/len(vals),
        "days_ge_5_fraction":0.0 if not vals else sum(v>=5 for v in vals)/len(vals),
        "max_trades_in_day":0 if not vals else max(vals),
    }


def _fold_stability(trades:Sequence[TournamentTrade])->dict[str,Any]:
    vals=tuple(sorted(trades,key=lambda x:ensure_utc(x.entry_at)))
    if len(vals)<180:
        return {"positive_fraction":0.0,"folds":[]}
    folds=[]
    for k in range(3):
        lo=int(len(vals)*k/3); hi=int(len(vals)*(k+1)/3)
        m=compute_metrics(vals[lo:hi])
        passed=bool(
            m.completed_trades>=40 and m.profit_factor is not None and m.profit_factor>1.0
            and m.expectancy_r is not None and m.expectancy_r>0.0
        )
        folds.append({"fold":k+1,"passed":passed,"metrics":m.payload()})
    return {"positive_fraction":sum(x["passed"] for x in folds)/3.0,"folds":folds}


def evaluate_v34(
    datasets:Mapping[str,Sequence[Bar]],*,pip_sizes:Mapping[str,float],
    base_costs:Mapping[str,M15ResearchCosts],stressed_costs:Mapping[str,M15ResearchCosts],
)->dict[str,Any]:
    all_times=sorted({ensure_utc(x.timestamp) for rows in datasets.values() for x in rows})
    split=all_times[int(len(all_times)*DEVELOPMENT_FRACTION)]
    dev_dates=sorted({x.date() for x in all_times if x<split})
    hold_dates=sorted({x.date() for x in all_times if x>=split})
    evaluations=[]
    for variant in VARIANTS:
        base_all=[]; stress_all=[]; raw_signals=0
        for symbol,rows in datasets.items():
            sig=extract_signals(rows,variant=variant)
            raw_signals+=len(sig)
            base_all.extend(simulate(rows,signals=sig,variant=variant,pip_size=pip_sizes[symbol],costs=base_costs[symbol]))
            stress_all.extend(simulate(rows,signals=sig,variant=variant,pip_size=pip_sizes[symbol],costs=stressed_costs[symbol]))
        base_all=_cap_account(base_all); stress_all=_cap_account(stress_all)
        db=tuple(x for x in base_all if ensure_utc(x.entry_at)<split and ensure_utc(x.exit_at)<split)
        ds=tuple(x for x in stress_all if ensure_utc(x.entry_at)<split and ensure_utc(x.exit_at)<split)
        hb=tuple(x for x in base_all if ensure_utc(x.entry_at)>=split)
        hs=tuple(x for x in stress_all if ensure_utc(x.entry_at)>=split)
        dm=compute_metrics(db); dms=compute_metrics(ds); hm=compute_metrics(hb); hms=compute_metrics(hs)
        stability=_fold_stability(ds)
        passed=bool(
            dms.completed_trades>=500 and dms.profit_factor is not None and dms.profit_factor>=1.05
            and dms.expectancy_r is not None and dms.expectancy_r>=0.02
            and stability["positive_fraction"]>=2/3
        )
        evaluations.append({
            "variant":asdict(variant),"raw_signals":raw_signals,
            "development_base":dm.payload(),"development_stressed":dms.payload(),
            "development_frequency":_frequency(db,dev_dates),"stability":stability,
            "development_passed":passed,
            "holdout_base":hm.payload(),"holdout_stressed":hms.payload(),
            "holdout_frequency":_frequency(hb,hold_dates),
        })

    eligible=[x for x in evaluations if x["development_passed"]]
    eligible.sort(key=lambda x:(
        float(x["stability"]["positive_fraction"]),
        float(x["development_stressed"]["expectancy_r"]),
        float(x["development_stressed"]["profit_factor"]),
        float(x["development_frequency"]["mean_trades_per_day"]),
    ),reverse=True)
    selected=eligible[0] if eligible else None
    holdout_pass=False
    if selected is not None:
        h=selected["holdout_stressed"]; f=selected["holdout_frequency"]
        holdout_pass=bool(
            h["completed_trades"]>=200 and h["profit_factor"] is not None and h["profit_factor"]>=1.10
            and h["expectancy_r"] is not None and h["expectancy_r"]>=0.05
            and f["mean_trades_per_day"]>=1.0
        )
    return {
        "research_version":RESEARCH_VERSION,"policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,"live_execution_enabled":False,
        "promotion_eligible":False,"diagnostic_only":DIAGNOSTIC_ONLY,
        "family":"BROKER_PARTICIPATION_SHOCK_CONTINUATION",
        "uses_price_breakout_level":False,"uses_ema_pullback":False,
        "uses_liquidity_sweep":False,"uses_cross_sectional_rank":False,
        "symbols":sorted(datasets),"split_time":split.isoformat(),
        "variants":evaluations,
        "selected_variant":None if selected is None else selected["variant"]["variant_id"],
        "holdout_pass":holdout_pass,
        "forward_shadow_candidate":bool(holdout_pass),
        "note":"Tick-count participation shock plus candle efficiency/close-location. Broker-native H1 only; XAU excluded.",
    }
