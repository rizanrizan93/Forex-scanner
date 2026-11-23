"""R31 aggregation: strict 32-shard completeness and validation-only ranking.

Each per-TF winner is selected by 2021-23 qualifying trade count and
positive expectancy/profit factor; 2024-26 is only retrospective disclosure.
No auto-promotion to live signals or Frozen V1. Fail on absent data.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT=Path("/tmp/r31-results")
OUT=Path("artifacts/r31")
TF=("H1","H4","D1","W1")
MODEL_STARTS=tuple(range(0,256,32))
EXPECTED_PER_SHARD=32*4096*8
EXPECTED_TOTAL=4*256*4096*8
TIERS=("volume_55","precision_60")


def eligible(row,tf,tier):
    v=row["validation"]
    min_n={"H1":65,"H4":30,"D1":12,"W1":5}[tf]
    return (
        v["n"]>=min_n
        and v["win_rate"] is not None
        and v["win_rate"]>= (.55 if tier=="volume_55" else .60)
        and v["net_usd_oz"]>0
        and v["expectancy_usd_oz"]>0
        and v["profit_factor"] is not None
        and v["profit_factor"]>=1.12
    )


def aggregate():
    report={
        "contract":"RIZAN_R31_HIGH_COVERAGE_PARETO_REPLAY_AGGREGATE_V1",
        "timeframes":{},"expected_total_evaluations":EXPECTED_TOTAL,
        "actual_total_evaluations":0,"all_shards_validated":False,
        "frozen_model_parity":False,"research_only":True,
        "execution_authority":False,"execution_influence":False,
        "promoted_to_live":False,
        "objective":"Max 2021-2023 no-overlap trades with win_rate >=55% or >=60%, PF>=1.12, expectancy>0, >=2 profitable years",
        "observed_years":"2012-2026",
        "test_caveat":"2024-2026 already previously studied; not a pristine forward holdout",
        "sources":{},
        "comparability_warning":"H1/H4 Dukascopy H1-derived BID, D1/W1 HistData-derived; different provider/session",
    }
    for tf in TF:
        source=None;models=set();candidate_pools={k:[] for k in TIERS}
        all_count=0;events=None
        for start in MODEL_STARTS:
            filename=f"r31-{tf}-models-{start}.json"
            files=list(ROOT.rglob(filename))
            if len(files)!=1:
                raise RuntimeError(f"R31_SHARD_MISSING_DUPLICATE:{tf}:{start}:{len(files)}")
            data=json.loads(files[0].read_text())
            if (data.get("contract")!="RIZAN_R31_HIGH_COVERAGE_PRECISION_PER_TF_REPLAY_V1"
                    or data.get("tf")!=tf
                    or data.get("model_start")!=start
                    or data.get("direction_model_variants")!=32
                    or data.get("zone_rule_variants")!=4096
                    or data.get("exit_policy_variants")!=8
                    or data.get("expected_evaluations")!=EXPECTED_PER_SHARD
                    or data.get("actual_evaluations")!=EXPECTED_PER_SHARD
                    or data.get("execution_authority") is not False
                    or data.get("execution_influence") is not False
                    or data.get("frozen_model_parity") is not False
                    or data.get("research_only") is not True
                    or not str(data.get("data_first","")).startswith("2012-")
                    or not str(data.get("data_last","")).startswith("2026-")):
                raise RuntimeError(f"R31_SHARD_CONTRACT_INVALID:{tf}:{start}")
            if source is None:
                source=data["source_shard_sha256"]
                events=data["source_tf_retest_events"]
            elif source!=data["source_shard_sha256"] or events!=data["source_tf_retest_events"]:
                raise RuntimeError(f"R31_INCONSISTENT_PRICE_HISTORY:{tf}:{start}")
            all_count+=EXPECTED_PER_SHARD
            models.update(range(start,start+32))
            for tier in TIERS:
                src=data.get("tiers",{}).get(tier)
                if src is None:raise RuntimeError(f"R31_MISSING_TIER:{tf}:{start}:{tier}")
                for item in src["most_trades_candidates"]:
                    if not eligible(item,tf,tier):
                        raise RuntimeError(f"R31_REPORTED_PASS_UNQUALIFIED:{tf}:{start}:{tier}")
                    if not start<=item["model_id"]<start+32:
                        raise RuntimeError("R31_MODEL_ID_OUT_OF_RANGE")
                    candidate_pools[tier].append(item)
        if models!=set(range(256)) or all_count!=256*4096*8:
            raise RuntimeError(f"R31_SOURCE_TF_INCOMPLETE:{tf}")
        tiers={}
        for name in TIERS:
            unique={}
            for x in candidate_pools[name]:
                k=(x["model_id"],x["config_id"],x["reward_risk_target"],x["holding_bars"])
                if k not in unique:unique[k]=x
            sorted_rows=sorted(unique.values(),
                key=lambda x:(x["validation"]["n"],x["validation"]["wilson_lower95"],
                              x["validation"]["profit_factor"] or 0),reverse=True)
            tiers[name]={
                "qualifying_challengers_in_shard_toplists":len(sorted_rows),
                "status":"QUALIFIED_RESEARCH_CHALLENGER" if sorted_rows else "NO_VALIDATED_PASS",
                "top_by_validation_trade_count":sorted_rows[:5],
                "minimum_forward_trades_for_recommendation":
                    {"H1":60,"H4":25,"D1":12,"W1":6}[tf],
            }
        report["timeframes"][tf]={
            "source":("DUKASCOPY_H1_BID" if tf in ("H1","H4")
                      else "HISTDATA_DAILY_SOURCE"),
            "source_hashes":source,
            "source_tf_retest_events":events,
            "models":256,"zone_configs":4096,"exit_policies":8,
            "configs_evaluated":all_count,
            "tiers":tiers
        }
        report["actual_total_evaluations"]+=all_count
    if report["actual_total_evaluations"]!=EXPECTED_TOTAL:
        raise RuntimeError("R31_ACTUAL_CONFIG_COUNT_MISMATCH")
    report["all_shards_validated"]=True
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/"r31-high-coverage-precision-2012-2026-aggregate.json"
    path.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"stage":"R31_AGGREGATE_COMPLETE",
        "actual_evaluations":report["actual_total_evaluations"],
        "timeframes":{tf:{
            tier:{"qualifying":row["tiers"][tier]["qualifying_challengers_in_shard_toplists"],
                  "best_val_n":(row["tiers"][tier]["top_by_validation_trade_count"][0]["validation"]["n"]
                     if row["tiers"][tier]["top_by_validation_trade_count"] else None),
                  "best_test_n":(row["tiers"][tier]["top_by_validation_trade_count"][0]["retrospective_2024_2026"]["n"]
                     if row["tiers"][tier]["top_by_validation_trade_count"] else None)}
            for tier in TIERS}
        for tf,row in report["timeframes"].items()}
    }),flush=True)
    return report


if __name__=="__main__":
    aggregate()
