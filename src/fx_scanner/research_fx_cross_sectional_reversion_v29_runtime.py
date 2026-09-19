from __future__ import annotations

import json
import os
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path

from .config import load_project_config
from .execution.factory import build_ctrader_research_feed
from .execution.policy import load_execution_policy
from .exceptions import CollectorUnavailable
from .models import ensure_utc
from .research_fx_cross_sectional_reversion_v29 import (
    ARTIFACT_CONTRACT,FX_SYMBOLS,RESEARCH_VERSION,evaluate_v29,
)
from .research_xau_m15_dual_strategy import infer_spread_proxy_pips
from .research_xau_m15_dual_strategy_runtime import _costs,_validation_cfg
from .storage.supabase_operational import SupabaseOperationalStore

UTC=timezone.utc
WORKER_NAME="ctrader_fx_cross_sectional_reversion_v29"
HISTORY_TARGET=15_000
MIN_HISTORY=10_000
PAGE_BARS=5_000
MAX_PAGES=4
TIMEFRAME_SECONDS=3600
CONNECT_BACKOFF=(0.0,2.0,5.0)


def _feed(policy):
    last=None
    for delay in CONNECT_BACKOFF:
        if delay: time.sleep(delay)
        try:
            feed=build_ctrader_research_feed(policy,FX_SYMBOLS)
            feed.ensure_connected()
            return feed
        except CollectorUnavailable as exc:
            last=exc
            if "connection timeout" not in str(exc).lower(): raise
    raise CollectorUnavailable("V29_CTRADER_CONNECT_RETRY_EXHAUSTED") from last


def _fetch(feed,symbol,as_of):
    merged={}; cursor=as_of; previous=None; pages=[]
    for page in range(1,MAX_PAGES+1):
        remaining=HISTORY_TARGET-len(merged)
        if remaining<=0: break
        count=min(PAGE_BARS,remaining)
        got=tuple(feed.historical_bars(
            symbol,"H1",
            from_time=cursor-timedelta(seconds=count*TIMEFRAME_SECONDS*3),
            to_time=cursor,count=count,
        ))
        if not got: break
        for row in got: merged[row.timestamp]=row
        earliest=min(x.timestamp for x in got)
        pages.append({"page":page,"received":len(got),"merged":len(merged),
                      "earliest":earliest.isoformat(),
                      "latest":max(x.timestamp for x in got).isoformat()})
        if previous is not None and earliest>=previous: break
        previous=earliest; cursor=earliest-timedelta(seconds=1)
    rows=tuple(sorted(merged.values(),key=lambda x:x.timestamp))
    closed=tuple(x for x in rows if ensure_utc(x.timestamp)+timedelta(hours=1)<=as_of)
    return (closed[-HISTORY_TARGET:] if len(closed)>HISTORY_TARGET else closed,pages)


def run()->int:
    cfg=load_project_config(None); policy=load_execution_policy(None)
    if str(policy.ctrader.get("environment","")).upper()!="DEMO":
        raise SystemExit("V29_DEMO_ONLY")
    if not bool(policy.ctrader.get("require_demo",False)):
        raise SystemExit("V29_REQUIRE_DEMO")
    pair_cfg={p.symbol:p for p in cfg.pairs}
    if any(s not in pair_cfg for s in FX_SYMBOLS):
        raise SystemExit("V29_PAIR_CONFIG_MISMATCH")

    now=datetime.now(tz=UTC); validation=_validation_cfg()
    datasets={}; pip_sizes={}; base_costs={}; stressed_costs={}; evidence={}
    feed=_feed(policy)
    try:
        for symbol in FX_SYMBOLS:
            try:
                bars,pages=_fetch(feed,symbol,now)
            except CollectorUnavailable as exc:
                evidence[symbol]={"bars":0,"error":str(exc)}; continue
            pair=pair_cfg[symbol]
            spread=infer_spread_proxy_pips(bars,pip_size=float(pair.pip_size)) if bars else {
                "available":False,"median_pips":None
            }
            evidence[symbol]={"bars":len(bars),"pages":pages,"spread_proxy":spread}
            if len(bars)<MIN_HISTORY or not bool(spread.get("available")): continue
            bc,sc=_costs(validation,float(spread["median_pips"]))
            datasets[symbol]=bars; pip_sizes[symbol]=float(pair.pip_size)
            base_costs[symbol]=bc; stressed_costs[symbol]=sc
    finally:
        try: feed.close()
        except Exception: pass

    details={
        "research_version":RESEARCH_VERSION,"environment":"DEMO",
        "policy_effect":"SHADOW_ONLY","execution_influence":False,
        "observed_at":now.isoformat(),"history_target_per_symbol":HISTORY_TARGET,
        "data_evidence":evidence,
    }
    if len(datasets)<13:
        details["decision"]={"stage":"DATA_INSUFFICIENT","usable_symbols":sorted(datasets),"promotion_eligible":False}
    else:
        details["decision"]=evaluate_v29(
            datasets,pip_sizes=pip_sizes,base_costs=base_costs,stressed_costs=stressed_costs,
        )
    try:
        SupabaseOperationalStore.from_env().write_heartbeat(
            WORKER_NAME,healthy=True,lag_seconds=0.0,details=details
        )
    except Exception as exc:
        details["heartbeat_write_error"]=f"{type(exc).__name__}:{exc}"

    path=Path(os.getenv("V29_EVIDENCE_OUTPUT","artifacts/fx-cross-sectional-reversion-v29.json"))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({"artifact_contract":ARTIFACT_CONTRACT,"contains_secrets":False,"details":details},
                               indent=2,sort_keys=True,default=str)+"\n")
    d=details["decision"]
    if d.get("stage")=="DATA_INSUFFICIENT":
        print(f"V29_RESULT stage=DATA_INSUFFICIENT usable={d['usable_symbols']} artifact={path}")
    else:
        print(
            "V29_RESULT "
            f"symbols={len(d['symbols'])} selected={d['selected_variant']} "
            f"holdout_pass={int(d['holdout_pass'])} candidate={int(d['forward_shadow_candidate'])} "
            f"promotion_eligible=0 artifact={path}"
        )
        for row in d["variants"]:
            dm=row["development_stressed"]; hm=row["holdout_stressed"]
            df=row["development_frequency"]; hf=row["holdout_frequency"]
            print(
                "V29_VARIANT "
                f"id={row['variant']['variant_id']} signals={row['signals']} "
                f"dev_n={dm['completed_trades']} dev_pf={dm['profit_factor']} dev_exp={dm['expectancy_r']} "
                f"dev_day={df['mean_trades_per_day']} stable={row['stability']['positive_fraction']} "
                f"passed={int(row['development_passed'])} "
                f"hold_n={hm['completed_trades']} hold_pf={hm['profit_factor']} hold_exp={hm['expectancy_r']} "
                f"hold_day={hf['mean_trades_per_day']} ge5={hf['days_ge_5_fraction']}"
            )
    return 0


if __name__=="__main__":
    raise SystemExit(run())
