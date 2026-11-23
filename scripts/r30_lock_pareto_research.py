"""Freeze actually replayed R30 signal-count Pareto candidates from original receipts.

No selection on this script's own user-visible test metric; only saves locked
historical evidence. Explicitly mark year-varying selections as research,
not one current live model. Never order or modify main/ForexScanner.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path

ROOT=Path("artifacts/r30_final")
RECEIPTS=Path("artifacts/r30_pareto")
LOCK=Path("research/RIZAN_R30_2012_2026_PARETO_RESEARCH_LOCK_20261123.json")
REPORT=Path("research/RIZAN_R30_2012_2026_PARETO_FINDINGS_20261123.md")
EXPECTED={
    "H1":{"scope":"spliced","years":8},
    "H4":{"scope":"spliced","years":8},
    "D1":{"scope":"FULL_D1_W1_FROM_2012","years":8},
    "W1":{"scope":"FULL_D1_W1_FROM_2012","years":8},
}
SOURCES={
    "H1":("r30-pareto-1h-spliced.json",14822199178),
    "H4":("r30-pareto-4h-spliced.json",14822942278),
    "D1":("r30-pareto-1D-archived.json",14820918464),
    "W1":("r30-pareto-1W-archived.json",14822830211),
}
CONTRACT="RIZAN_R30_2012_2026_MULTIOBJECTIVE_LOCK_20261123_V1"


def sha(x):
    return hashlib.sha256(Path(x).read_bytes()).hexdigest()


def fetch():
    doc={}
    for tf,(filename,id) in SOURCES.items():
        path=RECEIPTS/filename
        raw=json.loads(path.read_text())
        source=raw["historical_scope_actual"]
        if (raw.get("contract")!="RIZAN_R30_XAU_PARETO_OOSLIKE_2012_2026_V1"
            or raw.get("timeframe")!=tf
            or raw.get("research_only") is not True
            or raw.get("execution_authority") is not False
            or source.get("scope")!=EXPECTED[tf]["scope"]
            or raw.get("eval_years")!=list(range(2019,2027))
            or len(raw["annual_results"])!=3):
            raise ValueError("R30_EVIDENCE_CONTRACT_OR_SCOPE_MISMATCH:"+tf)
        years=source.get("actual_years") or []
        if set(years)!=set(range(2012,2027)):
            raise ValueError("R30_CLAIMED_FULL_SOURCE_MISSING:"+tf)
        doc[tf]=(raw,sha(path),id)
    return doc


def lock():
    rows=fetch()
    w1=rows["W1"][0]
    h4=rows["H4"][0]
    def item(d,mode):
        x=next(v for v in d["variants"] if v["mode"]==mode)
        return x
    hi=item(w1,"frequency")
    med=item(h4,"balanced")
    many=item(h4,"frequency")
    if (hi["BUY"]["n"],hi["BUY"]["correct"])!=(152,96) or hi["BUY"]["net_mean_after_assumed_cost_usd_oz"]<=0:
        raise ValueError("R30_W1_FREEQUENCY_NOT_REPRODUCED")
    if (med["BUY"]["n"],med["BUY"]["correct"])!=(810,449):
        raise ValueError("R30_H4_BALANCED_NOT_REPRODUCED")
    if (many["BUY"]["n"],many["BUY"]["correct"])!=(1191,653):
        raise ValueError("R30_H4_HIGH_FREQUENCY_NOT_REPRODUCED")
    qa={}
    for tf in ("1h","4h"):
        p=RECEIPTS/f"r30-2019-vendor-overlap-{tf}.json"
        x=json.loads(p.read_text())
        if (x.get("contract")!="R30_EXTERNAL_VS_R10_XAU_2019_OVERLAP_QA_V1"
            or x.get("source1_sha256")!=x.get("source2_sha256")
            or x.get("median_abs_close_diff_usd")!=0
            or x.get("p95_abs_close_diff_usd")!=0
            or x.get("next_candle_label_agreement")!=1.
            or x.get("common_bars",0)<(2000 if tf=="1h" else 500)):
            raise ValueError("R30_VENDOR_BOUNDARY_PRICE_MISMATCH:"+tf)
        qa[tf]=x
    annual={
        "W1_BUY_HIGH_FREQUENCY":[
            {"year":q["year"],
             "chosen_previous_year_policy":q["sides"]["BUY"]["selected"],
             "evaluation":q["sides"]["BUY"]["actual"]}
            for q in w1["annual_results"]["frequency"]],
        "H4_BUY_BALANCED":[
            {"year":q["year"],
             "chosen_previous_year_policy":q["sides"]["BUY"]["selected"],
             "evaluation":q["sides"]["BUY"]["actual"]}
            for q in h4["annual_results"]["balanced"]]
    }
    payload={
        "contract":CONTRACT,"symbol":"XAUUSD","history_requested":"2012-2026",
        "evaluation_years":"2019-2026","timeframes":list(SOURCES),
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"forexscanner_live_promotion":False,
        "per_timeframe":{
            tf:{
                "price_source_scope":rows[tf][0]["historical_scope_actual"],
                "run_artifact_id":rows[tf][2],
                "receipt_sha256":rows[tf][1],
                "variants":rows[tf][0]["variants"],
                "pareto_frontier":rows[tf][0]["pareto_frontier"],
            }
            for tf in SOURCES
        },
        "frozen_research_winner":{
            "W1_BUY_HIGH_FREQUENCY":hi["BUY"],
            "H4_BUY_BALANCED":med["BUY"],
            "H4_BUY_MAXIMUM_FREQUENCY":many["BUY"],
        },
        "annual_locked_policies":annual,
        "vendor_boundary_audit_2019":qa,
        "risks":[
            "No untouched forward test; 2019–26 had been researched repeatedly",
            "H1/H4 2012–18 independent redistributed HistData-like copy, 2019–26 original R10, exact 2019 overlapping candle bytes",
            "W1 63.16% historical 96/152, Wilson lower95 55.25% does not prove population accuracy >60%",
            "W1 high-frequency annual trained model/gates vary by year; NOT one deployed fixed cBot",
            "H4 2012–26 Balanced 55.43% 449/810, not >60%",
            "H4 high-frequency 54.83% 653/1191 and net mean NEGATIVE",
            "Estimated after-cost return 0.70 USD/oz is not executable FP Markets bid/ask/slippage",
            "No model has cleared BOTH BUY and SELL >60% in same timeframe with net-positive long-run expectancy",
            "Must not replace R28/R29 frozen snapshots or Frozen V1 trading"
        ],
    }
    LOCK.parent.mkdir(parents=True,exist_ok=True)
    LOCK.write_text(json.dumps(payload,indent=2,allow_nan=False)+"\n")
    for tf in SOURCES:
        print("R30_LOCK",tf,json.dumps({
            "scope":rows[tf][0]["historical_scope_actual"]["scope"],
            "variants":[{
                "mode":q["mode"],"BUY":q["BUY"],"SELL":q["SELL"],
                "signals":q["signals"],"coverage":q["coverage"]
            } for q in rows[tf][0]["variants"]]
        }),flush=True)
    print("R30_LOCK_COMPLETE",str(LOCK),sha(LOCK),flush=True)
    return payload


if __name__=="__main__":
    lock()
