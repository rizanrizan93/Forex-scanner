"""R32L: merge 2012-2026 real source-TF liquidity-sweep parameter shards.

Do not conflate source-TF entry replay with missing historical M5 evidence.
No production model or order authority. 2024-2026 is retrospection only.
"""
from __future__ import annotations
import json
from pathlib import Path

TF=("H1","H4","D1","W1")
STARTS=range(0,256,32)
TOTAL=4*256*4096*8
ROOT=Path("/tmp/r32l-results")
OUT=Path("artifacts/r32l")


def aggregate():
    result={
        "contract":"RIZAN_R32L_DENSE_COVERAGE_AGGREGATE_V1",
        "replay_family":"NEW_SOURCE_TF_LIQUIDITY_SWEEP_FAILED_BREAKOUT_PROXY_MODELS",
        "M5_replay_completed":False,
        "M5_blocker":"Dukascopy minute API HTTP 403 in pilot run 45256100542",
        "source_tf_entry_only":True,
        "frozen_R25_R11_R292_R18_R27_R24_historical_parity":False,
        "actual_total_evaluations":0,
        "expected_total_evaluations":TOTAL,
        "all_shards_verified":False,
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"frozen_model_parity":False,
        "no_auto_promotion":True,
        "timeframes":{}
    }
    for tf in TF:
        source=None;events=None
        candidates={"volume_55":[],"precision_60":[]}
        misses={"volume_55":[],"precision_60":[]}
        unprofitable={"volume_55":[],"precision_60":[]}
        broad=[]
        count=0;inspected=0
        for start in STARTS:
            filename=f"r32l-{tf}-models-{start}.json"
            paths=list(ROOT.rglob(filename))
            if len(paths)!=1:
                raise RuntimeError(f"R32L_MISSING_SHARD:{tf}:{start}:{len(paths)}")
            v=json.loads(paths[0].read_text())
            if (v.get("contract")!="RIZAN_R32L_DENSE_COVERAGE_AUDIT_V1"
                or v.get("tf")!=tf or v.get("model_start")!=start
                or v.get("direction_models")!=32
                or v.get("zone_configs")!=4096
                or v.get("exit_variants")!=8
                or v.get("actual_evaluations")!=1048576
                or v.get("expected_evaluations")!=1048576
                or not v.get("data_first","").startswith("2012-")
                or not v.get("data_last","").startswith("2026-")
                or v.get("frozen_model_parity") is not False
                or v.get("execution_authority") is not False
                or v.get("execution_influence") is not False
                or v.get("research_only") is not True):
                raise RuntimeError(f"R32L_INVALID_RESULTS:{tf}:{start}")
            if source is None:
                source=v["source_shard_sha256"]
                events=v["source_events"]
            elif source!=v["source_shard_sha256"] or events!=v["source_events"]:
                raise RuntimeError(f"R32L_SOURCE_HASH_MISMATCH:{tf}:{start}")
            count+=v["actual_evaluations"]
            inspected+=v["exact_validated_candidates"]
            for tier in ("volume_55","precision_60"):
                data=v["tiers"][tier]
                candidates[tier]+=data["largest_passed"]
                misses[tier]+=data["largest_win_floor_but_failed_other_gates"]
                unprofitable[tier]+=data["largest_positive_pf_but_failed_other_gates"]
                broad+=data["largest_sample_regardless_of_profit"]
        if count!=256*4096*8:
            raise RuntimeError(f"R32L_TF_INCOMPLETE:{tf}")
        tiers={}
        for tier in ("volume_55","precision_60"):
            p=candidates[tier]
            p.sort(key=lambda x:(x["validation"]["n"],x["validation"]["wilson_lower95"],
                                 x["validation"]["profit_factor"] or 0),reverse=True)
            unique={}
            for z in p:
                k=(z["model_id"],z["config_id"],z["reward_risk_target"],z["holding_bars"])
                unique.setdefault(k,z)
            best=list(unique.values())
            best.sort(key=lambda x:(x["validation"]["n"],x["validation"]["wilson_lower95"]),
                      reverse=True)
            misses[tier].sort(key=lambda x:(x["validation"]["n"],x["validation"]["win_rate"] or 0),
                              reverse=True)
            unprofitable[tier].sort(key=lambda x:x["validation"]["n"],reverse=True)
            tiers[tier]={
                "pass":bool(best),"stored_pass_count":len(best),
                "best_by_validation_trade_count":best[:4],
                "largest_meeting_win_floor_but_failing_other_gates":misses[tier][:3],
                "largest_positive_pf_but_failing_other_gates":unprofitable[tier][:3],
            }
        broad.sort(key=lambda x:x["validation"]["n"],reverse=True)
        result["timeframes"][tf]={
            "source_shard_sha256":source,
            "zone_events":events,
            "model_configs_reranked":count,
            "exact_validation_candidates":inspected,
            "tiers":tiers,
            "highest_volume_regardless_of_profit":broad[:2],
            "warning":"2024-26 outcomes are retrospective only and cannot choose the candidate",
        }
        result["actual_total_evaluations"]+=count
    if result["actual_total_evaluations"]!=TOTAL:
        raise RuntimeError("R32L_COMBINATION_COUNT_MISMATCH")
    result["all_shards_verified"]=True
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/"r32l-source-tf-liquidity-sweep-2012-2026.json"
    path.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({
        "stage":"R32L_AGGREGATE_COMPLETE",
        "actual_evaluations":result["actual_total_evaluations"],
        "timeframes":{tf:{
            tier:{"pass":r["tiers"][tier]["pass"],
                  "best_validation_trades":(
                      r["tiers"][tier]["best_by_validation_trade_count"][0]["validation"]["n"]
                      if r["tiers"][tier]["best_by_validation_trade_count"] else None
                  ),
                  "best_retro_trades":(
                      r["tiers"][tier]["best_by_validation_trade_count"][0]["retrospective_2024_2026"]["n"]
                      if r["tiers"][tier]["best_by_validation_trade_count"] else None
                  )}
            for tier in ("volume_55","precision_60")}
        for tf,r in result["timeframes"].items()},
        "promotion_authority":False
    }),flush=True)
    return result


if __name__=="__main__":
    aggregate()
