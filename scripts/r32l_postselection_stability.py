"""R32L post-selection stability audit across ALL 32 uploaded result shards.

Not a fresh OOS: 2024-26 has been studied repeatedly. No model selected
FOR trading from its hindsight metrics. This audit only counts consistency
among candidates already selected from 2012-23 development/validation.
"""
from __future__ import annotations
import glob,json
from pathlib import Path

TF=("H1","H4","D1","W1")
MIN_RETRO_N={"H1":55,"H4":20,"D1":12,"W1":8}
ROOT=Path("/tmp/r32l-results")
OUT=Path("artifacts/r32l")


def audit():
    result={
        "contract":"RIZAN_R32L_POSTSELECTION_RETROSPECTIVE_STABILITY_AUDIT_V1",
        "run_source":45257172812,
        "status":"RESEARCH_DIAGNOSTIC_ONLY",
        "selection_window":"2012-2023",
        "retrospective_window":"2024-2026_PREVIOUSLY_STUDIED_NOT_PRISTINE",
        "timeframes":{},"research_only":True,
        "execution_authority":False,"execution_influence":False,
        "frozen_model_parity":False,"not_M5":True,
    }
    for tf in TF:
        selected={}
        source=None
        n_shards=0
        for start in range(0,256,32):
            filename=f"r32l-{tf}-models-{start}.json"
            paths=list(ROOT.rglob(filename))
            if len(paths)!=1:raise RuntimeError(f"R32L_AUDIT_MISSING:{tf}:{start}")
            d=json.loads(paths[0].read_text())
            if (d.get("contract")!="RIZAN_R32L_DENSE_COVERAGE_AUDIT_V1"
                  or d.get("model_start")!=start or d.get("tf")!=tf
                  or d.get("actual_evaluations")!=1048576):
                raise RuntimeError(f"R32L_AUDIT_BAD_CONTRACT:{tf}:{start}")
            sha=d["source_shard_sha256"]
            if source is None:source=sha
            elif sha!=source:raise RuntimeError(f"R32L_AUDIT_SOURCE_MISMATCH:{tf}")
            n_shards+=1
            for tier in ("volume_55","precision_60"):
                for c in d["tiers"][tier]["largest_passed"]:
                    k=(c["model_id"],c["config_id"],
                       c["reward_risk_target"],c["holding_bars"])
                    if k in selected:continue
                    selected[k]=c
        # Audit the preselected validation winners only. No retro re-ranking
        # to select a production model.
        tested=list(selected.values())
        survived=[]
        retro_pos=[]
        for c in tested:
            v=c["validation"]
            t=c["retrospective_2024_2026"]
            s=c["retrospective_stress_extra_0_8_usd_oz"]
            pos=sum(t["annual"][str(y)]["net_usd_oz"]>0 for y in range(2024,2027))
            if (t["n"]>=MIN_RETRO_N[tf] and t["net_usd_oz"]>0
                    and t["profit_factor"] is not None and t["profit_factor"]>=1.10
                    and t["win_rate"] is not None and t["win_rate"]>=.55
                    and pos>=2 and s["net_usd_oz"]>0
                    and s["profit_factor"] is not None and s["profit_factor"]>=1.02):
                survived.append(c)
            if t["net_usd_oz"]>0:
                retro_pos.append(c)
        # Descriptive percentile distribution never used for model selection.
        sorted_by_validation=sorted(tested,
             key=lambda c:(c["validation"]["n"],
                           c["validation"]["wilson_lower95"] or 0),reverse=True)
        result["timeframes"][tf]={
            "shards_checked":n_shards,
            "historical_price_provenance":source,
            "unique_preselected_validation_configs":len(tested),
            "retrospective_net_positive":len(retro_pos),
            "survivors_all_retro_stress_gates":len(survived),
            "min_retrospective_trades":MIN_RETRO_N[tf],
            "validation_top_three_then_retrospective":[
                {"model_id":c["model_id"],"config_id":c["config_id"],
                 "reward_risk_target":c["reward_risk_target"],
                 "validation":c["validation"],
                 "retrospective_2024_2026":c["retrospective_2024_2026"],
                 "cost_stress":c["retrospective_stress_extra_0_8_usd_oz"]}
                for c in sorted_by_validation[:3]],
            "warning":"Survival is diagnostic, NOT forward evidence or promotion"
        }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"r32l-postselection-stability-audit-2012-2026.json").write_text(
        json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R32L_AUDIT_DONE",
        "summary":{tf:{"unique":x["unique_preselected_validation_configs"],
                       "retro_positive":x["retrospective_net_positive"],
                       "survive":x["survivors_all_retro_stress_gates"]}
                   for tf,x in result["timeframes"].items()}}),flush=True)
    return result

if __name__=="__main__":
    audit()
