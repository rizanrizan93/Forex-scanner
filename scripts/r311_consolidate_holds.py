"""Consolidate predeclared R31.1 exploratory longer-hold results, no orders."""
from pathlib import Path
import json,hashlib,math

HERE=Path("artifacts/r311")
OUT=Path("research/RIZAN_R311_EXTENDED_NET_PROFIT_RESEARCH_LOCK_20261123.json")
MD=Path("research/RIZAN_R311_EXTENDED_NET_PROFIT_FINDINGS_20261123.md")
HORIZONS={"1W":(3,4,6,8),"1D":(3,5),"4h":(4,6)}
MODES=("max_net","net_dd","profit_frequency")
CONTRACT="RIZAN_R31_XAU_NET_PROFIT_FROZEN_RESEARCH_V1"
FOLLOW="RIZAN_R311_EXTENDED_HOLDS_20261123"


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def score():
    rows=[]
    for tf,hs in HORIZONS.items():
        for h in hs:
            for mode in MODES:
                file=HERE/f"r311-{tf}-h{h}-{mode}.json"
                x=json.loads(file.read_text())
                if (
                    x.get("contract")!=CONTRACT or x.get("exploratory_extension_id")!=FOLLOW
                    or x.get("research_after_inspecting_r31") is not True
                    or x.get("timeframe")!=tf or x.get("hold_candles")!=h
                    or x.get("mode")!=mode or x.get("research_only") is not True
                    or x.get("execution_authority") is not False
                    or x.get("backtest_entry")!="NEXT_BAR_OPEN"
                    or x.get("cost_scenario_main_usd_oz")!=2.
                    or x.get("evaluation_years")!=list(range(2019,2027))
                    or x.get("data_years")!=list(range(2012,2027))
                    or len(x.get("annual",[]))!=8
                ):
                    raise ValueError("R311_SOURCE_OR_CONTRACT_INVALID:"+str(file))
                allp=[]
                yearly=[]
                for year,report in zip(range(2019,2027),x["annual"]):
                    if report.get("year")!=year:raise ValueError("R311_NON_CHRONOLOGICAL_YEAR")
                    p=[r["net_usd_oz"] for r in report.get("trade_receipts",[])]
                    if len(p)!=report["total_trades"] or not math.isclose(
                        sum(p),report["net_profit_usd_per_1oz"],abs_tol=1e-5
                    ):
                        raise ValueError("R311_RAW_PNL_RECONCILIATION_FAILED")
                    allp.extend(p)
                    yearly.append(sum(p))
                if not math.isclose(
                    sum(allp),x["hypothetical_net_profit_usd_per_1oz"],abs_tol=1e-5
                ):raise ValueError("R311_OVERALL_PNL_RECONCILIATION_FAILED")
                c5=sum(allp)-3*len(allp)
                if not math.isclose(
                    c5,x["cost_sensitivity_net_profit"]["5.0"],abs_tol=1e-5
                ):raise ValueError("R311_COST5_SCENARIO_INVALID")
                gains=sum(p for p in allp if p>0)
                losses=-sum(p for p in allp if p<0)
                pf=gains/losses if losses>0 else None
                row={
                    "tf":tf,"hold":h,"mode":mode,"n":len(allp),
                    "net_usd_fixed_1oz_cost2":sum(allp),
                    "net_usd_fixed_1oz_cost5":c5,
                    "max_realized_drawdown_usd_fixed_1oz":x["hypothetical_max_realized_drawdown_usd_per_1oz"],
                    "profit_factor_cost2":pf,
                    "positive_years":sum(y>0 for y in yearly),
                    "net_by_year":dict(zip(range(2019,2027),yearly)),
                    "source_sha256":checksum(file),
                }
                row["robust_selection_gate"]=bool(
                    len(allp)>=30 and row["positive_years"]>=5
                    and row["net_usd_fixed_1oz_cost5"]>0
                    and pf is not None and pf>1.1
                )
                rows.append(row)
    baseline={}
    for tf,hs in HORIZONS.items():
        file=HERE/f"r311-baseline-{tf}.json"
        x=json.loads(file.read_text())
        if (
            x.get("exploratory_extension_id")!=FOLLOW
            or x.get("research_after_inspecting_r31") is not True
            or x.get("execution_authority") is not False
            or set(x.get("baselines",{}))!=set(f"h{i}" for i in hs)
        ):
            raise ValueError("R311_UNOPTIMIZED_BASELINE_MISSING:"+tf)
        baseline[tf]={
            str(h):{
                "best_fixed_control_name":max(x["baselines"][f"h{h}"],key=lambda k:x["baselines"][f"h{h}"][k]["net_usd_per_1oz_cost2"]),
                "best_fixed_control_net_cost2":max(v["net_usd_per_1oz_cost2"] for v in x["baselines"][f"h{h}"].values()),
                "all_controls":x["baselines"][f"h{h}"]
            } for h in hs
        }
    r=sorted(rows,key=lambda q:q["net_usd_fixed_1oz_cost2"],reverse=True)
    robust=[q for q in r if q["robust_selection_gate"]]
    return r,baseline,robust


def run():
    ranked,baseline,robust=score()
    if len(ranked)!=24:raise ValueError("R311_RESULTS_NOT_COMPLETE")
    oldlock=Path("research/RIZAN_R31_XAU_MAX_NET_2012_2026_RESEARCH_LOCK_20261123.json")
    old=json.loads(oldlock.read_text())
    previous=old["top_raw_net"][0]
    if previous["net_profit_usd_per_fixed_1oz"]<1000 or old.get("variants_tested")!=30:
        raise ValueError("R311_PREVIOUS_RESEARCH_NOT_VERIFIED")
    report={
        "contract":"RIZAN_R311_EXTENDED_HOLD_PARETO_RESEARCH_V1",
        "source_study":FOLLOW,
        "symbol":"XAUUSD","historical_price_years":"2012-2026",
        "evaluation_years":"2019-2026 (2026 partial)",
        "tested_extended_models":len(ranked),
        "previous_R31_max_net":previous,
        "research_only":True,"execution_authority":False,
        "live_deploy_allowed":False,"blind_test":False,
        "updated_after_inspecting_previous_outcomes":True,
        "top_net":ranked[:8],
        "robust_at_cost5_and_5positive_years":robust,
        "baseline":baseline,
        "all_results":ranked,
        "limitations":[
            "Extended horizons selected AFTER observing the R31 2025 W1 profit spike",
            "All profits are hypothetical fixed 1 troy oz position, no compounding, no real broker fills",
            "Price bars are rehosted 2012-18 and original R10 2019-26; audited boundary",
            "2019-26 years were inspected in prior RIZAN experiments, not untouched holdout",
            "Maximum realized-close drawdown excludes floating stop-out and margin risk",
            "Cost sensitivity at 2 and 5 USD/oz is not measured FP Markets spread or overnight swap",
            "Trend baseline comparisons are diagnostic, not proof of live alpha",
            "Cannot promote a live W1 or cBot strategy from backtest alone"
        ]
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    lines=[
        "# RIZAN R31.1 — XAUUSD Extended Holding Net Profit, 2012–2026",
        "",
        "**Exploratory research: no forward verification or live promotion.**",
        "",
        "All outcomes are hypothetical USD for fixed one troy ounce, at $2/oz assumed cost, without leverage or compounding. Later 2026 is partial.",
        "",
        f"## {len(ranked)} additional holding-period and mode combinations",
        "",
        "| TF | Hold bars | Mode | Trades | Net $/1oz | Max realized DD $/1oz | Net at $5 cost | Positive years |",
        "|---|---:|---|---:|---:|---:|---:|---:|"
    ]
    for x in ranked:
        lines.append(
            f'| {x["tf"]} | {x["hold"]} | {x["mode"]} | {x["n"]} | '
            f'{x["net_usd_fixed_1oz_cost2"]:+,.2f} | '
            f'{x["max_realized_drawdown_usd_fixed_1oz"]:,.2f} | '
            f'{x["net_usd_fixed_1oz_cost5"]:+,.2f} | '
            f'{x["positive_years"]}/8 |'
        )
    lines+=["","## Fixed, no-refitting baseline controls","",
        "A higher raw net is not enough. In particular, W1 long-hold profits can be dominated by market-wide gold appreciation and the 2025 trend.",
        "",
        "| TF | Hold | Best constant control | Net $/1oz |",
        "|---|---:|---|---:|"]
    for tf in HORIZONS:
        for h,q in baseline[tf].items():
            lines.append(f'| {tf} | {h} | {q["best_fixed_control_name"]} | {q["best_fixed_control_net_cost2"]:+,.2f} |')
    lines+=["","## Research decision","",
        (f'- {len(robust)} configurations passed minimum 5 positive years, >=30 trades and net-positive at $5 cost.'
         if robust else "- No new R31.1 configuration passed the 5 positive-year + $5 cost + PF>1.1 + 30 trade gate."),
        "- Any result selected after viewing 2025 W1 behavior is exploratory. Independent prospective testing and measured executable broker transaction costs are mandatory before considering adoption.",
        "- Frozen V1, R28, R29, R30, ForexScanner and cTrader orders unchanged.",
        ""]
    MD.write_text("\n".join(lines))
    print(json.dumps({"stage":"R311_EVIDENCE_LOCK_COMPLETE","count":len(ranked),
        "top":ranked[0],"robust_count":len(robust),"path":str(OUT),
        "report":str(MD)},allow_nan=False),flush=True)
    return report


if __name__=="__main__":run()
