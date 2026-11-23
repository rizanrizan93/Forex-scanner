"""Aggregate 32 R30 shards by predeclared validation metrics, fail closed."""
from __future__ import annotations
import hashlib, json
from pathlib import Path

TF=("H1","H4","D1","W1")
STARTS=range(0,128,16)
CONFIGS=16384
ROOT=Path("/tmp/r30-results")
OUT=Path("artifacts/r30")
OUT.mkdir(parents=True,exist_ok=True)

def aggregate(*,full=True):
    result={"contract":"RIZAN_R30_INDEPENDENT_TF_MEGA_AGGREGATE_V1",
            "evaluation_window":"2012-2026, per-source available last candle",
            "timeframes":{},"research_only":True,
            "execution_authority":False,"execution_influence":False,
            "not_exact_frozen_model_parity":True,
            "no_model_promotion":True,
            "all_data_and_shards_verified":False}
    all_total=0
    all_ok=True
    for tf in TF:
        rows=[]
        seen=set()
        for start in STARTS:
            filename=f"r30-{tf}-models-{start}.json"
            matches=list(ROOT.rglob(filename))
            if len(matches)!=1:
                raise RuntimeError(f"R30_MISSING_OR_DUPLICATED_SHARD:{tf}:{start}:{len(matches)}")
            row=json.loads(matches[0].read_text())
            if (row.get("contract")!="RIZAN_R30_CAUSAL_PER_TF_ZONE_REPLAY_V1"
                    or row.get("timeframe")!=tf
                    or row.get("direction_model_start")!=start
                    or row.get("direction_model_variants")!=16
                    or row.get("zone_config_variants")!=CONFIGS
                    or row.get("parameter_combinations_actually_evaluated")!=16*CONFIGS
                    or row.get("execution_authority") is not False
                    or row.get("execution_influence") is not False
                    or row.get("not_original_frozen_model_parity") is not True
                    or row.get("first_candle","")[:4]!="2012"
                    or row.get("last_candle","")[:4]!="2026"):
                raise ValueError(f"R30_INVALID_SHARD_CONTRACT:{tf}:{start}")
            if start==0:
                base_hash=row["source_shard_sha256"]
            elif row["source_shard_sha256"]!=base_hash:
                raise ValueError(f"R30_SOURCE_HASH_MISMATCH:{tf}:{start}")
            for c in row.get("top_candidates",[]):
                sig=(c["model_id"],c["zone_config"])
                if sig in seen:continue
                seen.add(sig)
                rows.append(c)
            all_total+=row["parameter_combinations_actually_evaluated"]
        # Rank exclusively on 2021-23 selection metrics, never test outcomes.
        rows.sort(key=lambda c:(c["selection"].get("wilson_lower95") or 0,
                                c["selection"].get("expectancy_usd_oz") or -99999,
                                c["selection"].get("n") or 0),reverse=True)
        best=rows[:5]
        result["timeframes"][tf]={
            "models_evaluated":128,
            "zone_configurations_per_model":CONFIGS,
            "combinations_evaluated":128*CONFIGS,
            "validated_candidates":len(rows),
            "selection_rule":"2021-2023 WILSON_LOWER95 THEN EXPECTANCY",
            "source_sha256_by_year":base_hash,
            "top_preselected_challengers":best,
            "warning":"Best D1/W1/H1/H4 is a NEW research challenger, not frozen model parity",
        }
    result["all_combinations_evaluated"]=all_total
    result["expected_total_combinations"]=len(TF)*128*CONFIGS
    result["all_data_and_shards_verified"]=(all_total==result["expected_total_combinations"])
    if not result["all_data_and_shards_verified"]:
        raise RuntimeError("R30_INCOMPLETE_TOTAL")
    outfile=OUT/"r30-combined-2012-2026.json"
    outfile.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R30_AGGREGATE_COMPLETE",
                      "total_evaluated":all_total,
                      "timeframes":{tf:{"valid":len(x["top_preselected_challengers"])}
                                    for tf,x in result["timeframes"].items()},
                      "research_only":True}),flush=True)
    return result

if __name__=="__main__":
    aggregate()
