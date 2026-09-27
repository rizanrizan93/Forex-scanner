from __future__ import annotations

import json, os
from pathlib import Path
from typing import Any, Sequence

from .research_xau_v229_be_management_v244 import (
    ARTIFACT_CONTRACT, EXECUTION_AUTHORITY, EXECUTION_INFLUENCE,
    LIVE_EXECUTION_ENABLED, MANAGEMENT_VARIANTS, POLICY_EFFECT, RESEARCH_VERSION,
)
from .research_xau_v229_historical_v242 import effective_trades, summarize_trades

ERAS={"2012_2018":(2012,2018),"2019_2024":(2019,2024),"2025_2026_YTD":(2025,2026)}
OFFICIAL={"win_rate_min":0.55,"profit_factor_min":1.30,"expectancy_r_min":0.15,"aggregate_trades_min":250}

def _dir()->Path:
    p=Path(os.getenv("XAU_V244_SHARD_DIR","/tmp/xau-v244-shards"))
    if not p.exists(): raise SystemExit(f"XAU_V244_SHARD_DIR_NOT_FOUND:{p}")
    return p

def _out()->Path:
    return Path(os.getenv("XAU_V244_FULL_OUTPUT","artifacts/xau-v229-be-management-v244-full.json"))

def _load(p:Path)->list[dict[str,Any]]:
    rows=[]
    for f in sorted(p.rglob("xau-v229-be-management-v244-*.json")):
        x=json.loads(f.read_text())
        if "year" in x: rows.append(x)
    rows.sort(key=lambda x:int(x["year"]))
    return rows

def _filter(rows:Sequence[dict[str,Any]],*,variant:str,cost:str)->list[dict[str,Any]]:
    return [dict(r) for r in rows if str(r.get("management_variant"))==variant and str(r.get("cost_mode"))==cost]

def _dd(rows:Sequence[dict[str,Any]])->float:
    done=[dict(r) for r in rows if str(r.get("state")) in {"WIN","LOSS","BREAKEVEN"}]
    done.sort(key=lambda r:(str(r.get("exit_at") or ""),str(r.get("entry_at") or "")))
    eq=peak=dd=0.0
    for r in done:
        eq+=float(r.get("net_r") or 0.0); peak=max(peak,eq); dd=max(dd,peak-eq)
    return float(dd)

def _metrics(rows:Sequence[dict[str,Any]])->dict[str,Any]:
    m=dict(summarize_trades(rows)); m["max_drawdown_r"]=_dd(rows)
    m["be_activated"]=sum(bool(r.get("be_activated")) for r in rows)
    m["be_stop_hits"]=sum(str(r.get("reason") or "").startswith("BE_STOP") for r in rows)
    return m

def _eras(rows:Sequence[dict[str,Any]])->dict[str,Any]:
    return {name:_metrics([dict(r) for r in rows if lo<=int(r.get("year") or 0)<=hi]) for name,(lo,hi) in ERAS.items()}

def _breakdown(rows:Sequence[dict[str,Any]],field:str,values:Sequence[Any])->dict[str,Any]:
    out={}
    for v in values:
        out[str(v)]=_metrics([dict(r) for r in rows if str(r.get(field) or "").upper()==str(v).upper()])
    return out

def _gate(m:dict[str,Any])->dict[str,Any]:
    checks={
      "trade_count":int(m.get("completed") or 0)>=OFFICIAL["aggregate_trades_min"],
      "win_rate":m.get("win_rate") is not None and float(m["win_rate"])>=OFFICIAL["win_rate_min"],
      "profit_factor":m.get("profit_factor_r") is not None and float(m["profit_factor_r"])>=OFFICIAL["profit_factor_min"],
      "expectancy":m.get("expectancy_r") is not None and float(m["expectancy_r"])>=OFFICIAL["expectancy_r_min"],
    }
    return {"checks":checks,"all_numeric_gates_met":all(checks.values()),"thresholds":dict(OFFICIAL)}

def _positive(m:dict[str,Any])->bool:
    return int(m.get("completed") or 0)>=30 and m.get("profit_factor_r") is not None and float(m["profit_factor_r"])>1 and m.get("expectancy_r") is not None and float(m["expectancy_r"])>0

def run()->int:
    shards=_load(_dir())
    if len(shards)<15: raise SystemExit(f"XAU_V244_EXPECTED_15_SHARDS:{len(shards)}")
    plans=[]; trades=[]
    for s in shards:
        plans.extend(dict(r) for r in s.get("plans") or [])
        trades.extend(dict(r) for r in s.get("trades") or [])
    effective,_=effective_trades(plans,trades)

    reports={}
    for variant in MANAGEMENT_VARIANTS:
        base_rows=_filter(effective,variant=variant,cost="BASE")
        stress_rows=_filter(effective,variant=variant,cost="STRESS")
        base=_metrics(base_rows); stress=_metrics(stress_rows)
        be=_eras(base_rows); se=_eras(stress_rows)
        reports[variant]={
          "base":base,"stress":stress,"base_eras":be,"stress_eras":se,
          "base_source":_breakdown(base_rows,"candidate_source",["H4","H1","M15"]),
          "base_slot":_breakdown(base_rows,"slot",[1,2,3,4]),
          "official_base":_gate(base),"official_stress":_gate(stress),
          "all_stress_eras_positive":all(_positive(x) for x in se.values()),
        }

    baseline=reports["BASELINE"]["base"]
    for variant,rep in reports.items():
        b=rep["base"]
        rep["delta_vs_baseline"]={
          "profit_factor_r":None if b.get("profit_factor_r") is None or baseline.get("profit_factor_r") is None else float(b["profit_factor_r"])-float(baseline["profit_factor_r"]),
          "expectancy_r":None if b.get("expectancy_r") is None or baseline.get("expectancy_r") is None else float(b["expectancy_r"])-float(baseline["expectancy_r"]),
          "max_drawdown_r":float(b.get("max_drawdown_r") or 0)-float(baseline.get("max_drawdown_r") or 0),
        }

    candidates=[
      v for v,r in reports.items() if v!="BASELINE"
      and int(r["base"].get("completed") or 0)>=250
      and float(r["base"].get("profit_factor_r") or 0)>=1.10
      and float(r["base"].get("expectancy_r") or -999)>=0.05
      and float(r["stress"].get("profit_factor_r") or 0)>=1.05
      and float(r["stress"].get("expectancy_r") or -999)>=0.02
      and bool(r["all_stress_eras_positive"])
    ]

    payload={
      "artifact_contract":f"{ARTIFACT_CONTRACT}_FULL_2012_2026_1",
      "research_version":RESEARCH_VERSION,"symbol":"XAUUSD",
      "years":[int(s["year"]) for s in shards],"year_count":len(shards),
      "management_variants":list(MANAGEMENT_VARIANTS),
      "reports":reports,
      "forward_shadow_candidates":candidates,
      "decision":"FORWARD_SHADOW_CANDIDATE_FOUND" if candidates else "NO_ROBUST_BE_VARIANT_FOUND",
      "validation_classification":"RETROSPECTIVE_MANAGEMENT_ABLATION_NOT_INDEPENDENT_OOS",
      "promotion":{"execution_promotion_allowed":False,"independent_oos_pass":False,"forward_demo_pass":False},
      "policy_effect":POLICY_EFFECT,"execution_influence":EXECUTION_INFLUENCE,
      "execution_authority":EXECUTION_AUTHORITY,"live_execution_enabled":LIVE_EXECUTION_ENABLED,
    }
    p=_out(); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(payload,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print("XAU_V244_FULL",json.dumps({v:{"pf":r["base"]["profit_factor_r"],"exp":r["base"]["expectancy_r"],"stress_pf":r["stress"]["profit_factor_r"]} for v,r in reports.items()}),"candidates="+(",".join(candidates) if candidates else "NONE"),"execution_authority=0")
    return 0

if __name__=="__main__": raise SystemExit(run())
