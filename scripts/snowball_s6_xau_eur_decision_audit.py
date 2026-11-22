"""S6 independent XAU cash tier vs S5 independent EUR decision audit.
This is NOT a paired EUR+XAU portfolio, and cannot assert superiority of a venue.
"""
import argparse,json,hashlib
from collections import Counter
from pathlib import Path

STAGES=("100","125","250","1000")
TRAIN=range(2012,2019)
VALID=range(2019,2023)
RETRO=range(2023,2026)

def fold(years,cash,config,raw):
    m=[raw[y][config]["stages"][cash] for y in years]
    n=sum(x["n"] for x in m)
    p=sum(x["gross_profit_R"] for x in m)
    loss=sum(x["gross_loss_R"] for x in m)
    return {"n":n,"mean_R":sum(x["net_R"] for x in m)/n if n else None,
      "mean_stress_R":sum(x["net_stress_R"] for x in m)/n if n else None,
      "pf_base":p/loss if loss else None,
      "positive_stress_years":sum(x["net_stress_R"]>0 and x["n"]>=10 for x in m),
      "nonempty_years":sum(x["n"]>=10 for x in m),
      "annual_n":[x["n"] for x in m],
      "years":len(m)}

def main(root,eurfile):
    records={};provider={}
    for year in range(2012,2026):
        candidates=list(Path(root).rglob(f"s6_xau_{year}.json"))
        assert len(candidates)==1,(year,candidates)
        d=json.loads(candidates[0].read_text())
        assert d["year"]==year and d["configs"]==3456
        records[year]={r["config"]:r for r in d["rows"]}
        provider[str(year)]={k:v for k,v in d["provider"].items() if k!="monthly_sha256"}
    keys=set(records[2012])
    assert len(keys)==3456 and all(set(records[y])==keys for y in records)
    eur=json.loads(Path(eurfile).read_text())
    assert eur["configurations_considered"]==3456
    assert eur["qualified_train"]==0
    audit={}
    for cash in STAGES:
        tallies=Counter();best=[];eligible=[]
        for config in sorted(keys):
            t=fold(TRAIN,cash,config,records)
            if t["n"]>=90:
                tallies["n_ge_90"]+=1
                eligible.append((config,t))
                if t["mean_stress_R"]>0:tallies["mean_stress_positive"]+=1
                if t["mean_stress_R"]>.025:tallies["mean_stress_gt_0_025R"]+=1
                if t["pf_base"] is not None and t["pf_base"]>=1.12:tallies["pf_ge_1_12"]+=1
                if t["positive_stress_years"]>=5:tallies["positive_years_ge5"]+=1
            if t["n"]>=90 and t["mean_stress_R"]>.025 and t["pf_base"] is not None and t["pf_base"]>=1.12 and t["positive_stress_years"]>=5:
                tallies["all_gates"]+=1
        for config,t in sorted(eligible,key=lambda x:x[1]["mean_stress_R"],reverse=True)[:5]:
            best.append({"config":config,"training":t,
                "validation":fold(VALID,cash,config,records),
                "retrospective":fold(RETRO,cash,config,records)})
        # No future-data selection: diagnostic only for failed configs.
        sample="SWEEP_RECLAIM|BUY|LB12|H4_WITH|EUR_CORE_WIB|H60|SL1|TP1.5"
        probe={str(y):records[y][sample]["stages"][cash]["n"] for y in range(2019,2026)}
        audit[cash]={"training_counts":dict(tallies),
            "top_training_diagnostic_NOT_PROMOTED":best,
            "representative_setup_feasible_fills_2019_2025":probe}
    result={"study":"RIZAN_S6_XAU_VS_EUR_NOMINAL_CASH_TIER_DIAGNOSTIC",
      "frozen_v1_replay_or_wallet":False,
      "venues_comparable":False,
      "source_XAU":"3rd party Dukascopy-derived bid/ask pinned source",
      "source_EUR":"FXCM public bid/ask, different CFD provider",
      "xau_configurations_per_tier":3456,
      "eur_screen_model_count":eur["configurations_considered"],
      "eur_predeclared_train_qualifiers":eur["qualified_train"],
      "xau_by_cash":audit,
      "issuer_decision":"NO_SELECTION: XAU and EUR candidates fail robust training gate; a combined account cannot be evaluated from independently aggregated signals",
      "portfolio_combined_earnings_verified":False,
      "min_gold_contract_oz_assumed":1,
      "minimum_real_broker_lot_spec_verified":False,
      "tier_time_to_reach_verified":False,
      "target_10b_verified":False,
      "provider_diagnostics_by_year":provider,
      "limitations":["S6 XAU outcomes use nominal cash $100/$125/$250/$1000 separately, NOT progression or compounding",
        "S6 stress fixed extra costs on SAME OHLC trigger paths, no broker 2x full replay",
        "S5 EUR selected via historical grid; no profitable robust candidate",
        "2 venues + different spreads cannot imply reliable portfolio asset superiority",
        "2019–2025 outcomes already seen, not pristine untouched future holdout",
        "XAU per-cash entry feasibility assumes 1 oz min, 1:200, entry risk <=8%, margin50%",
        "No native Frozen V1 C# ledger parity, thus cannot infer terminal balance or DD"],
      "research_only":True,"execution_authority":False}
    dest=Path("artifacts/snowball_s6/s6_compare_xau_eur_cash_tiers.json")
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,indent=2,allow_nan=False))
    print("S6_CASH_AUDIT",json.dumps({
      "decision":result["issuer_decision"],
      "EUR_train_qualified":eur["qualified_train"],
      "XAU_stage_training_counts":{k:v["training_counts"] for k,v in audit.items()},
      "XAU_representative_feasible_100":audit["100"]["representative_setup_feasible_fills_2019_2025"]
      },allow_nan=False),flush=True)
    print("S6_BEST_TRAIN_DIAGNOSTIC",json.dumps(
      {k:v["top_training_diagnostic_NOT_PROMOTED"][:2] for k,v in audit.items()},
      allow_nan=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--xau-root",default="/tmp/snowball_s6")
    p.add_argument("--eur-aggregate",default="/tmp/eur/s5_eurusd_aggregate.json")
    a=p.parse_args()
    main(a.xau_root,a.eur_aggregate)
