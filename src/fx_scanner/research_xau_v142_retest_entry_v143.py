from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from statistics import median
from typing import Any, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_multisymbol_m15_breakout_v18 import (
    MAX_HOLD_BARS,
    MIN_RISK_ATR,
    _cost_r,
    extract_signals,
)
from .research_xau_2025_bootstrap_onset_forensic_v122 import build_v122_feature_frame
from .research_xau_capital_compatibility_v129 import _simulate
from .research_xau_champion_onset_reaccel_v123 import build_reaccel_route_frame
from .research_xau_false_onset_forensic_v125 import annotate_compressed_epochs
from .research_xau_hierarchical_regime_router_v35 import build_h1_context
from .research_xau_multihorizon_100usd_v20 import M15_VARIANTS, _dedupe, _limit_concurrency
from .research_xau_v110_robustness_v111 import assemble_v110_selector
from .research_xau_v132_h1_confirmation_v134 import _apply_h1, _route_c2
from .research_xau_v134_h3_robustness_v135 import START, RECENT, frozen_h3

RESEARCH_VERSION="XAU_V142_RETEST_ENTRY_V143"
ARTIFACT_CONTRACT="XAU_V142_RETEST_ENTRY_V143_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

ENTRY_MODES=(
    "BASELINE_NEXT_OPEN",
    "BREAKOUT_LEVEL_RETEST_2BAR",
    "DISPLACEMENT_BODY50_RETEST_2BAR",
    "FVG50_RETEST_3BAR",
)
RETEST_BARS={"BREAKOUT_LEVEL_RETEST_2BAR":2,"DISPLACEMENT_BODY50_RETEST_2BAR":2,"FVG50_RETEST_3BAR":3}


def _metrics(trades):
    return compute_metrics(tuple(trades)).payload()


def _period(trades,start,end):
    a,b=ensure_utc(start),ensure_utc(end)
    return tuple(t for t in trades if a<=ensure_utc(t.entry_at)<b)


def _variant_lookback(sig):
    for variant in M15_VARIANTS:
        if variant.variant_id==sig.variant_id:
            return int(variant.lookback_m15)
    raise ValueError("V143_UNKNOWN_VARIANT")


def _entry_level(bars,sig,mode):
    i=sig.signal_index
    row=bars[i]
    if mode=="BREAKOUT_LEVEL_RETEST_2BAR":
        lb=_variant_lookback(sig)
        prior=bars[i-lb:i]
        return max(float(x.high) for x in prior) if sig.direction=="LONG" else min(float(x.low) for x in prior)
    if mode=="DISPLACEMENT_BODY50_RETEST_2BAR":
        return 0.5*(float(row.open)+float(row.close))
    if mode=="FVG50_RETEST_3BAR":
        if i<2:
            return None
        left=bars[i-2]
        if sig.direction=="LONG" and float(row.low)>float(left.high):
            return 0.5*(float(row.low)+float(left.high))
        if sig.direction=="SHORT" and float(row.high)<float(left.low):
            return 0.5*(float(row.high)+float(left.low))
        return None
    raise ValueError("V143_UNKNOWN_ENTRY_MODE")


def _retest_trades(rows,signals,*,mode,costs,pip_size):
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    out=[]
    candidates=0
    fills=0
    for sig in signals:
        level=_entry_level(bars,sig,mode)
        if level is None:
            continue
        candidates+=1
        max_wait=RETEST_BARS[mode]
        fill_i=None
        for j in range(sig.signal_index+1,min(len(bars),sig.signal_index+1+max_wait)):
            if float(bars[j].low)<=float(level)<=float(bars[j].high):
                fill_i=j
                break
        if fill_i is None:
            continue
        fills+=1
        entry=float(level)
        stop=float(sig.stop)
        risk=entry-stop if sig.direction=="LONG" else stop-entry
        if not isfinite(risk) or risk<=0 or risk<MIN_RISK_ATR*float(sig.atr):
            continue
        target=entry+sig.reward_r*risk if sig.direction=="LONG" else entry-sig.reward_r*risk
        risk_pips=risk/float(pip_size)
        last_i=min(len(bars)-1,fill_i+MAX_HOLD_BARS)
        trade=None
        for j in range(fill_i,last_i+1):
            bar=bars[j]
            if sig.direction=="LONG":
                stop_hit=float(bar.low)<=stop
                target_hit=float(bar.high)>=target
            else:
                stop_hit=float(bar.high)>=stop
                target_hit=float(bar.low)<=target
            raw_target=target_hit
            if j==fill_i:
                target_hit=False
            held=j-fill_i
            cost=_cost_r(risk_pips=risk_pips,bars_held=held,costs=costs)
            if stop_hit:
                gross=-1.0
                trade=TournamentTrade(
                    sig.variant_id,sig.symbol,sig.direction,sig.signal_at,
                    ensure_utc(bars[fill_i].timestamp),ensure_utc(bar.timestamp),
                    sig.signal_index,j,entry,stop,sig.atr,stop,target,
                    gross,cost,gross-cost,held,
                    "STOP_FIRST_AMBIGUOUS" if raw_target else "STOP_HIT",
                )
                break
            if target_hit:
                gross=sig.reward_r
                trade=TournamentTrade(
                    sig.variant_id,sig.symbol,sig.direction,sig.signal_at,
                    ensure_utc(bars[fill_i].timestamp),ensure_utc(bar.timestamp),
                    sig.signal_index,j,entry,target,sig.atr,stop,target,
                    gross,cost,gross-cost,held,"TARGET_HIT",
                )
                break
        if trade is None:
            if last_i<fill_i+MAX_HOLD_BARS:
                continue
            bar=bars[last_i]
            exit_price=float(bar.close)
            gross=(exit_price-entry)/risk if sig.direction=="LONG" else (entry-exit_price)/risk
            cost=_cost_r(risk_pips=risk_pips,bars_held=MAX_HOLD_BARS,costs=costs)
            trade=TournamentTrade(
                sig.variant_id,sig.symbol,sig.direction,sig.signal_at,
                ensure_utc(bars[fill_i].timestamp),ensure_utc(bar.timestamp),
                sig.signal_index,last_i,entry,exit_price,sig.atr,stop,target,
                gross,cost,gross-cost,MAX_HOLD_BARS,"TIME_EXIT",
            )
        out.append(trade)
    return tuple(out),{"raw_entry_candidates":candidates,"raw_fills":fills,"raw_fill_rate":0.0 if candidates==0 else fills/candidates}


def _h3_retest(rows,*,mode,evaluation_end,pip_size,costs):
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    if mode=="BASELINE_NEXT_OPEN":
        trades=frozen_h3(bars,evaluation_end=end,pip_size=pip_size,costs=costs)
        return trades,{"raw_entry_candidates":None,"raw_fills":None,"raw_fill_rate":None}

    pieces=[]
    raw_candidate=raw_fill=0
    for variant in M15_VARIANTS:
        signals=extract_signals(bars,variant=variant)
        trades,stats=_retest_trades(bars,signals,mode=mode,costs=costs,pip_size=pip_size)
        pieces.extend(trades)
        raw_candidate+=stats["raw_entry_candidates"]
        raw_fill+=stats["raw_fills"]
    raw=_limit_concurrency(_dedupe(tuple(pieces)))

    frame=build_v122_feature_frame(bars)
    _,epoch_defs=build_reaccel_route_frame(frame,route_id="COMPRESSED_REACCEL")
    _,selector_all,_=assemble_v110_selector(bars,costs=costs,pip_size=pip_size,evaluation_end=end)
    records=annotate_compressed_epochs(frame,epoch_defs,selector_all)
    c2=_route_c2(raw,records,evaluation_end=end)
    h3=_apply_h1(c2,h1_context=build_h1_context(bars),mode="STRICT")
    return h3,{"raw_entry_candidates":raw_candidate,"raw_fills":raw_fill,"raw_fill_rate":0.0 if raw_candidate==0 else raw_fill/raw_candidate}


def _risk_stats(trades):
    vals=[abs(float(t.entry_price)-float(t.stop_loss))/float(t.atr_at_signal) for t in trades if float(t.atr_at_signal)>0]
    if not vals:return {"n":0}
    vals=sorted(vals)
    return {"n":len(vals),"median_risk_atr":float(median(vals)),"p25_risk_atr":float(vals[int(.25*(len(vals)-1))]),"p75_risk_atr":float(vals[int(.75*(len(vals)-1))])}


def _capital(trades,*,broker_spec,leverage_tiers):
    return _simulate(trades,spec=broker_spec,tiers=leverage_tiers,starting_balance=100.0,account_leverage=100.0,margin_cap_pct=50.0)


def evaluate_v143(rows:Sequence[Bar],*,evaluation_end,pip_size,costs,broker_spec,leverage_tiers):
    end=ensure_utc(evaluation_end)
    out={}
    for mode in ENTRY_MODES:
        trades,fill=_h3_retest(rows,mode=mode,evaluation_end=end,pip_size=pip_size,costs=costs)
        full=_period(trades,START,end); recent=_period(trades,RECENT,end)
        out[mode]={
            "full_metrics":_metrics(full),"recent_metrics":_metrics(recent),
            "full_live100":_capital(full,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
            "recent_live100":_capital(recent,broker_spec=broker_spec,leverage_tiers=leverage_tiers),
            "risk_stats_full":_risk_stats(full),"risk_stats_recent":_risk_stats(recent),
            "fill_stats":fill,
        }
    return {
        "research_version":RESEARCH_VERSION,"artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,"execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,"live_execution_enabled":False,
        "contract":{
            "same_signal_family":"V20 M15 L12/L20","same_causal_route":"V132 C2",
            "same_h1_permission":"V134 STRICT","same_stop":"original local-6 extreme + 0.15 ATR",
            "same_min_risk_atr":MIN_RISK_ATR,"same_reward_r":True,"same_max_hold":True,
            "entry_modes":list(ENTRY_MODES),"no_parameter_grid":True,
            "fill_rule":"limit level must be touched after signal; same fill-bar stop is counted conservatively; fill-bar target is not credited",
            "capital":"$100 / 1:100 / 20% risk / 50% margin cap","execution_authority":False,
        },
        "entries":out,
        "note":"V143 tests execution-price improvement while retaining the proven structural stop. A promising mode still requires independent stress/timing validation.",
    }
