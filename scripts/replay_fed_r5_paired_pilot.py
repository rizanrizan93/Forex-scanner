"""R5 causal-time pilot: historical XAU M1 V4 after 2023-09-20 FOMC.

The technical entries use ONLY bars closed by evaluation time;
macro input is historical USMPD completed event-window response (EX-POST
oracle, not archived live). Never invoke R5 true PIT alignment with these
retrospective features. This is an observational paired FALSIFICATION
sample, not a production-eligible backtest.

Prespecified 2023-09-20 FOMC date; do not select events by outcomes.
"""
from __future__ import annotations
from collections import Counter
from datetime import date
from pathlib import Path
import argparse, hashlib, json, math
import pandas as pd
from scripts.replay_fed_macro_2019_2026_r1 import event_plan
from scripts.replay_fed_macro_event_pilot_r1 import PINNED_SOURCE_SHA,fetch_official
from scripts.replay_fed_information_shock_r4 import source_join,classify
from scripts.replay_rejection_v2_outcomes import load_csv,future,COST
from fx_scanner.rejection_v2_research import calculate,completed
from research.fed_expectation_r1.fomc_continuation_observation_r5 import evaluate_continuation

TARGET_DATE="2023-09-20"
RULES=("MP2_TIPS10_DXY","POLICY_OIS1Y_TIPS10_SP500_VETO",
       "OIS1Y_TIPS10_DXY")
AFTER_EVENT_SCREEN_MINUTES=90

def replay(d, *,manifest,event,expost_source_sha):
    if manifest.get("source")!="HISTDATA_XAUUSD_M1" or manifest.get("failed_periods"):
        raise ValueError("SOURCE_MANIFEST_REJECTED")
    frame=d[["open","high","low","close"]].astype(float).copy()
    if not isinstance(frame.index,pd.DatetimeIndex) or frame.index.tz is None or (
            frame.index.has_duplicates or not frame.index.is_monotonic_increasing):
        raise ValueError("UNTRUSTED_HISTORICAL_M1_INDEX")
    frame.index=frame.index.tz_convert("UTC")
    cut=pd.Timestamp(event["window_end_utc"])
    if cut.tzinfo is None:raise ValueError("NO_FOMC_RELEASE_CLOCK")
    cut=cut.tz_convert("UTC")
    if event.get("r4_source_join")!="VERIFIED_DATE_WINDOW_AND_EVENT_CLOCK":
        raise ValueError("UNTRUSTED_OFFICIAL_EVENT_MATCH")
    if not event.get("r4_features"):raise ValueError("MISSING_FOMC_PRICE_RESPONSE_FACTORS")
    directions={rule:classify(event["r4_features"],rule) for rule in RULES}
    counts=Counter()
    observations=[]
    state=[]
    last_by_key={}
    last_continuation_by_rule_side={}
    continuation_cooldown_minutes=60
    # Restrict to FIRST pattern of each direction/model at each meeting.
    # Exact closed M1 following the PREDEFINED completed official window.
    # Restrict scan to 90 clock minutes, not 90 observed candles.
    eligible_index=frame.index[(frame.index+pd.Timedelta(minutes=1)>=cut)&(
        frame.index+pd.Timedelta(minutes=1)<cut+pd.Timedelta(minutes=AFTER_EVENT_SCREEN_MINUTES))]
    for idx in eligible_index:
        i=frame.index.get_loc(idx)
        at=idx+pd.Timedelta(minutes=1)
        if i<6100:counts["not_enough_htf_history"]+=1;continue
        row=frame.iloc[i]
        try:
            res=calculate(frame.iloc[:i+1],now=at,
                bid=float(row.close)-COST/2,ask=float(row.close)+COST/2,
                quote_at=at,prior_events=state)
        except (ValueError,KeyError,TypeError):
            counts["technical_data_or_htf_unavailable"]+=1
            continue
        state=res["rejection_events"]
        counts["screened_m1_closes"]+=1
        # Independent post-event momentum path: OBSERVATIONAL ONLY,
        # separate from V4. Never described as approved R5 entry.
        unique_sides=sorted({side for side in directions.values()
                            if side in ("BUY","SELL")})
        for side in unique_sides:
            try:
                m5=completed(frame.iloc[:i+1],5,at)
                observation=evaluate_continuation(
                    frame.iloc[:i+1],m5,at=at,side=side,
                    bid=float(row.close)-COST/2,
                    ask=float(row.close)+COST/2,
                    atr_m5=res["atr_m5"])
            except (ValueError,TypeError,KeyError):
                counts["continuation_data_unavailable"]+=1;continue
            if observation["event_detected"]:
                counts["continuation_raw_"+side]+=1
                for rule,macro_side in directions.items():
                    if macro_side!=side:continue
                    counts["continuation_"+rule+"_same_side_raw"]+=1
                    key_cont=(rule,side)
                    if key_cont in last_continuation_by_rule_side:
                        counts["continuation_"+rule+"_deduplicated_overlap"]+=1
                        continue
                    # One FOMC meeting = one candidate per rule and side,
                    # even if the first label is censored. No selecting a
                    # later winning overlap after the first failed clock.
                    last_continuation_by_rule_side[key_cont]=at
                    label=future(frame,i,side,60,3,3)
                    if label is None:
                        counts["continuation_"+rule+"_h1_censored"]+=1
                        continue
                    counts["continuation_"+rule+"_h1_evaluable"]+=1
                    if label["net_end"]>0:
                        counts["continuation_"+rule+"_h1_direction_right"]+=1
        for setup in res["v4_setups"]:
            side=setup["side"]
            counts["v4_"+side+"_"+setup["entry_status"]]+=1
            key=(side,setup["setup_type"])
            raw=setup["entry_status"]=="ENTRY_CANDIDATE"
            pattern=setup["stage"] in ("MSS_CONFIRMED","RECLAIM_DETECTED")
            if not (raw or pattern):continue
            counts["observed_pattern_"+side]+=1
            for rule,macro in directions.items():
                if macro not in ("BUY","SELL"):
                    counts["rule_"+rule+"_WAIT"]+=1
                    continue
                if side!=macro:
                    counts["rule_"+rule+"_opposite_side_blocked"]+=1
                    continue
                counts["rule_"+rule+"_same_side_patterns"]+=1
                if not raw:
                    counts["rule_"+rule+"_v4_technical_blocked"]+=1
                    continue
                cooldown_key=(rule,side,setup["setup_type"])
                if (cooldown_key in last_by_key and
                    (at-last_by_key[cooldown_key]).total_seconds()<3600):
                    counts["rule_"+rule+"_cooldown_blocked"]+=1;continue
                label=future(frame,i,side,60,3,3)
                if label is None:
                    counts["rule_"+rule+"_h1_price_censored"]+=1;continue
                # Research-only ex-post macro tag, not R5 production-eligible.
                observations.append({
                    "at_utc":at.isoformat(),
                    "rule":rule,"oracle_macro_direction":macro,
                    "v4_side":side,"v4_setup_type":setup["setup_type"],
                    "v4_stage":setup["stage"],"v4_entry_status":setup["entry_status"],
                    "h1_terminal_direction_correct_after_0p50_cost":bool(label["net_end"]>0),
                    "h1_net_end_usd_oz":round(label["net_end"],4),
                    "macro_historical_source":"RETROSPECTIVE_USMPD_NOT_POINT_IN_TIME",
                    "eligible_live":False
                })
                last_by_key[cooldown_key]=at
                counts["rule_"+rule+"_observational_paired_event"]+=1
    return {
        "contract":"FED_R5_EXPOST_MACRO_V4_PAIRED_REAL_M1_FALSIFICATION_PILOT",
        "fomc_event":event["event_id"],
        "fomc_communication_window":event["window"],
        "official_window_end_utc":cut.isoformat(),
        "input_history_rows":len(frame),
        "prespecified_screen_minutes":AFTER_EVENT_SCREEN_MINUTES,
        "continuation_same_side_cooldown_minutes":continuation_cooldown_minutes,
        "continuation_event_unit":"FIRST M1 STRUCTURE BREAK PER RULE/SIDE/FOMC MEETING; all other M1 observations correlated",
        "continuation_pick_policy":"FIRST_RAW_DETECTION_EVEN_IF_FORWARD_LABEL_CENSORED",
        "macro_oracle_directions":directions,
        "continuation_is_OBSERVATION_ONLY_not_a_V4_entry":True,
        "official_source_sha256":expost_source_sha,
        "xau_source_sha256":manifest.get("sha256_csv"),
        "counters":dict(counts),
        "observations":observations,
        "true_macro_pit_buy_n":0,
        "true_macro_pit_sell_n":0,
        "production_eligible":False,
        "authority_to_execute":False,
        "limitations":[
            "Official USMPD factors are ex-post, never archived realtime inputs",
            "Single previously-studied FOMC example is NOT an independent holdout",
            "Bid/ask spread synthetic $0.50/oz; no broker fills, carry or commission",
            "V4 may find no technically eligible entries even if oracle macro direction is strong",
            "Barriers are evaluated only on consecutive observed M1, otherwise censored",
            "Entry research cannot approve any LIVE trades",
        ],
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    mf=Path(str(a.csv)+".provenance.json")
    if not mf.exists():raise ValueError("M1_REAL_SOURCE_PROVENANCE_REQUIRED")
    manifest=json.loads(mf.read_text())
    if hashlib.sha256(a.csv.read_bytes()).hexdigest()!=manifest.get("sha256_csv"):
        raise ValueError("PRICE_SOURCE_SHA_MISMATCH")
    raw=fetch_official()
    if hashlib.sha256(raw).hexdigest()!=PINNED_SOURCE_SHA:
        raise ValueError("OFFICIAL_FOMC_SOURCE_SHA_MISMATCH")
    events=event_plan(raw,2023)
    sample=[e for e in events if e.get("date")==TARGET_DATE]
    if len(sample)!=1:raise ValueError("FOMC_EVENT_NOT_UNIQUE")
    matched,failures=source_join(sample,raw)
    if failures:raise ValueError("OFFICIAL_EVENT_JOIN_FAILED")
    output=replay(load_csv(a.csv),manifest=manifest,event=matched[0],
                  expost_source_sha=PINNED_SOURCE_SHA)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(output,indent=2,allow_nan=False)+"\n")
    print("FED_R5_REAL_M1_PAIRED_PILOT",json.dumps({
        k:v for k,v in output.items() if k!="observations"},allow_nan=False))
if __name__=="__main__":main()
