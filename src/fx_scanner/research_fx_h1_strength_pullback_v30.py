from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import compute_metrics
from .models import Bar, ensure_utc
from .research_fx_cross_sectional_strength_v28 import (
    FX_SYMBOLS,
    PAIR_META,
    MIN_PAIR_COVERAGE,
    _atr_series,
    _cap_account,
    _frequency,
    _normalized_momentum,
    _stability,
    _strength_snapshot,
    simulate_symbol,
)
from .research_xau_m15_dual_strategy import M15ResearchCosts

RESEARCH_VERSION = "FX_H1_STRENGTH_PULLBACK_V30"
ARTIFACT_CONTRACT = "FX_H1_STRENGTH_PULLBACK_V30_EVIDENCE_1"
POLICY_EFFECT = "SHADOW_ONLY"
EXECUTION_INFLUENCE = False
DIAGNOSTIC_ONLY = True
DEVELOPMENT_FRACTION = 0.70
FREQUENCY_TARGET = 5.0


@dataclass(frozen=True, slots=True)
class PullbackVariant:
    variant_id: str
    momentum_hours: int
    edge_min: float
    top_k_per_hour: int
    pullback_tolerance_atr: float
    stop_atr: float
    target_r: float
    max_hold_hours: int
    cooldown_hours: int


VARIANTS = (
    PullbackVariant("V30_H24_E20_K3_P025_R150",24,20.0,3,0.25,1.25,1.50,12,4),
    PullbackVariant("V30_H24_E30_K3_P020_R175",24,30.0,3,0.20,1.25,1.75,16,6),
    PullbackVariant("V30_H24_E40_K2_P015_R200",24,40.0,2,0.15,1.50,2.00,20,8),
    PullbackVariant("V30_H48_E20_K3_P025_R150",48,20.0,3,0.25,1.25,1.50,16,6),
    PullbackVariant("V30_H48_E30_K3_P020_R175",48,30.0,3,0.20,1.50,1.75,20,8),
    PullbackVariant("V30_H48_E40_K2_P015_R200",48,40.0,2,0.15,1.50,2.00,24,8),
)


@dataclass(frozen=True, slots=True)
class PullbackSignal:
    variant_id: str
    symbol: str
    direction: str
    signal_index: int
    signal_at: Any
    edge: float
    atr: float


def _ema(values: Sequence[float], period: int) -> tuple[float | None, ...]:
    if len(values) < period:
        return tuple(None for _ in values)
    seed=sum(float(x) for x in values[:period])/period
    out:[float|None]=[None]*(period-1)+[seed]
    alpha=2.0/(period+1.0); prev=seed
    for value in values[period:]:
        prev=alpha*float(value)+(1.0-alpha)*prev
        out.append(prev)
    return tuple(out)


def _aggregate_h4(rows: Sequence[Bar]) -> tuple[Bar,...]:
    buckets={}
    for row in rows:
        stamp=ensure_utc(row.timestamp)
        h=(stamp.hour//4)*4
        key=stamp.replace(hour=h,minute=0,second=0,microsecond=0)
        buckets.setdefault(key,[]).append(row)
    out=[]
    for key in sorted(buckets):
        group=sorted(buckets[key],key=lambda x:ensure_utc(x.timestamp))
        if len(group)!=4:
            continue
        out.append(Bar(
            symbol=group[0].symbol,timeframe="H4",timestamp=key,
            open=float(group[0].open),
            high=max(float(x.high) for x in group),
            low=min(float(x.low) for x in group),
            close=float(group[-1].close),
            tick_count=sum(int(x.tick_count) for x in group),
            spread_avg=sum(float(x.spread_avg) for x in group)/4.0,
            spread_max=max(float(x.spread_max) for x in group),
        ))
    return tuple(out)


def _h4_trend_context(rows: Sequence[Bar]):
    h4=_aggregate_h4(rows)
    closes=[float(x.close) for x in h4]
    e20=_ema(closes,20); e50=_ema(closes,50)
    close_times=tuple(ensure_utc(x.timestamp)+timedelta(hours=4) for x in h4)
    return h4,e20,e50,close_times


def extract_pullback_signals(
    datasets: Mapping[str,Sequence[Bar]],
    *,
    variant: PullbackVariant,
) -> tuple[PullbackSignal,...]:
    rows={s:tuple(sorted(v,key=lambda x:ensure_utc(x.timestamp)))
          for s,v in datasets.items() if s in PAIR_META}
    idx_time={}; momentum={}; atrs={}; ema20={}; h4ctx={}; timeline=set()
    for symbol,values in rows.items():
        idx_time[symbol]={ensure_utc(x.timestamp):i for i,x in enumerate(values)}
        timeline.update(idx_time[symbol])
        momentum[symbol]=_normalized_momentum(values,variant.momentum_hours)
        atrs[symbol]=_atr_series(values)
        ema20[symbol]=_ema([float(x.close) for x in values],20)
        h4ctx[symbol]=_h4_trend_context(values)

    last_signal={}
    output=[]
    for stamp in sorted(timeline):
        pair_scores={}; current={}
        for symbol,values in rows.items():
            i=idx_time[symbol].get(stamp)
            if i is None: continue
            current[symbol]=i
            m=momentum[symbol][i]
            if m is not None: pair_scores[symbol]=float(m)
        if len(pair_scores)<12: continue
        strengths=_strength_snapshot(pair_scores)
        candidates=[]

        for symbol,i in current.items():
            base,quote=PAIR_META[symbol]
            b=strengths.get(base); q=strengths.get(quote)
            if b is None or q is None or min(b[1],q[1])<MIN_PAIR_COVERAGE:
                continue
            edge=max(-100.0,min(100.0,(b[0]-q[0])/2.0))
            if abs(edge)<variant.edge_min: continue

            atr=atrs[symbol][i]; e=ema20[symbol][i]
            if atr is None or e is None or not isfinite(float(atr)) or float(atr)<=0: continue

            h4,e4_20,e4_50,h4_closes=h4ctx[symbol]
            count=bisect_right(h4_closes,stamp+timedelta(hours=1))
            if count<=0: continue
            hidx=count-1
            if hidx<50 or e4_20[hidx] is None or e4_50[hidx] is None: continue
            hclose=float(h4[hidx].close)
            h20=float(e4_20[hidx]); h50=float(e4_50[hidx])
            trend=None
            if hclose>h20>h50: trend="LONG"
            elif hclose<h20<h50: trend="SHORT"
            if trend is None: continue

            direction="LONG" if edge>0 else "SHORT"
            if direction!=trend: continue

            bar=rows[symbol][i]
            rng=float(bar.high)-float(bar.low)
            if rng<=0: continue
            ema=float(e); av=float(atr)
            valid=False
            if direction=="LONG":
                valid=bool(
                    float(bar.low)<=ema+variant.pullback_tolerance_atr*av
                    and float(bar.close)>ema
                    and float(bar.close)>float(bar.open)
                    and (float(bar.close)-float(bar.low))/rng>=0.60
                )
            else:
                valid=bool(
                    float(bar.high)>=ema-variant.pullback_tolerance_atr*av
                    and float(bar.close)<ema
                    and float(bar.close)<float(bar.open)
                    and (float(bar.high)-float(bar.close))/rng>=0.60
                )
            if not valid: continue

            last=last_signal.get(symbol)
            if last is not None and (stamp-last).total_seconds()<variant.cooldown_hours*3600:
                continue
            candidates.append((abs(edge),symbol,direction,i,edge,av))

        candidates.sort(key=lambda x:(-x[0],x[1]))
        used=set(); chosen=0
        for _,symbol,direction,i,edge,av in candidates:
            base,quote=PAIR_META[symbol]
            if base in used or quote in used: continue
            output.append(PullbackSignal(
                variant_id=variant.variant_id,symbol=symbol,direction=direction,
                signal_index=i,signal_at=stamp,edge=float(edge),atr=av,
            ))
            used.update((base,quote)); last_signal[symbol]=stamp; chosen+=1
            if chosen>=variant.top_k_per_hour: break
    return tuple(output)


def evaluate_v30(
    datasets: Mapping[str,Sequence[Bar]],
    *,
    pip_sizes: Mapping[str,float],
    base_costs: Mapping[str,M15ResearchCosts],
    stressed_costs: Mapping[str,M15ResearchCosts],
)->dict[str,Any]:
    all_times=sorted({ensure_utc(x.timestamp) for values in datasets.values() for x in values})
    split_time=all_times[int(len(all_times)*DEVELOPMENT_FRACTION)]
    dev_dates=sorted({x.date() for x in all_times if x<split_time})
    hold_dates=sorted({x.date() for x in all_times if x>=split_time})
    evaluations=[]

    for variant in VARIANTS:
        signals=extract_pullback_signals(datasets,variant=variant)
        by_symbol={}
        for s in signals: by_symbol.setdefault(s.symbol,[]).append(s)
        base_all=[]; stress_all=[]
        for symbol,sigs in by_symbol.items():
            base_all.extend(simulate_symbol(
                datasets[symbol],signals=sigs,variant=variant,
                pip_size=pip_sizes[symbol],costs=base_costs[symbol],
            ))
            stress_all.extend(simulate_symbol(
                datasets[symbol],signals=sigs,variant=variant,
                pip_size=pip_sizes[symbol],costs=stressed_costs[symbol],
            ))
        base_all=_cap_account(base_all); stress_all=_cap_account(stress_all)
        db=tuple(t for t in base_all if ensure_utc(t.entry_at)<split_time and ensure_utc(t.exit_at)<split_time)
        ds=tuple(t for t in stress_all if ensure_utc(t.entry_at)<split_time and ensure_utc(t.exit_at)<split_time)
        hb=tuple(t for t in base_all if ensure_utc(t.entry_at)>=split_time)
        hs=tuple(t for t in stress_all if ensure_utc(t.entry_at)>=split_time)
        dm=compute_metrics(db); dms=compute_metrics(ds)
        hm=compute_metrics(hb); hms=compute_metrics(hs)
        stability=_stability(ds)
        df=_frequency(db,dev_dates); hf=_frequency(hb,hold_dates)
        passed=bool(
            dms.completed_trades>=300
            and dms.profit_factor is not None and dms.profit_factor>=1.05
            and dms.expectancy_r is not None and dms.expectancy_r>=0.02
            and stability["positive_fraction"]>=2/3
        )
        evaluations.append({
            "variant":asdict(variant),"signals":len(signals),
            "development_base":dm.payload(),"development_stressed":dms.payload(),
            "development_frequency":df,"stability":stability,
            "development_passed":passed,
            "holdout_base":hm.payload(),"holdout_stressed":hms.payload(),
            "holdout_frequency":hf,
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
            h["completed_trades"]>=150
            and h["profit_factor"] is not None and h["profit_factor"]>=1.10
            and h["expectancy_r"] is not None and h["expectancy_r"]>=0.05
            and f["mean_trades_per_day"]>=FREQUENCY_TARGET
            and f["days_ge_5_fraction"]>=0.50
        )
    return {
        "research_version":RESEARCH_VERSION,"policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,"live_execution_enabled":False,
        "diagnostic_only":DIAGNOSTIC_ONLY,"promotion_eligible":False,
        "xau_untouched":True,"symbols":sorted(datasets),"split_time":str(split_time),
        "variants":evaluations,
        "selected_variant":None if selected is None else selected["variant"]["variant_id"],
        "holdout_pass":holdout_pass,"forward_shadow_candidate":bool(holdout_pass),
        "frequency_target_mean_trades_per_day":FREQUENCY_TARGET,
        "note":(
            "V30 combines relative currency strength with H4 trend and an H1 EMA20 "
            "pullback/rejection trigger. It is a non-XAU satellite lane only."
        ),
    }
