"""R32 read-only auditor: independently recalculate all 12 complete receipts.

Rank historical hypothetical profit, eligible signal frequency and a 3D
Pareto frontier. All model selections were PREVIOUS 2 years only; however
research-process historical peeking occurred in R30/R31/R31.1. No orders.
"""
from __future__ import annotations
import hashlib,json,math
from pathlib import Path

ROOT=Path("artifacts/r32")
OUT=Path("research/RIZAN_R32_XAU_PROFIT_FREQUENCY_ATR_LOCK_20261123.json")
MD=Path("research/RIZAN_R32_XAU_PROFIT_FREQUENCY_ATR_FINDINGS_20261123.md")
TFS=("1W","1D","4h","1h")
MODES=("max_net","max_signals","profit_frequency")
CONTRACT="RIZAN_R32_PROFIT_AND_SIGNAL_FREQUENCY_2012_2026_V1"
REFS={
    "W1_EMA_BUY_4weeks":dict(n=75,net=2825.987,dd=570.133,
                             pf=2.698673934251519,positive_years=6),
    "D1_EMA_ADX_BUY_5days":dict(n=193,net=2294.642,dd=349.355,
                                pf=1.6354155878608094,positive_years=6),
}


def audit():
    entries=[]
    for tf in TFS:
        for mode in MODES:
            file=ROOT/f"r32-{tf}-{mode}.json"
            raw=file.read_bytes()
            x=json.loads(raw)
            src=x.get("source",{})
            if (x.get("contract")!=CONTRACT or x.get("tf")!=tf
                or x.get("mode")!=mode
                or x.get("historical_years")!=list(range(2012,2027))
                or x.get("evaluation_years")!=list(range(2019,2027))
                or x.get("research_only") is not True
                or x.get("execution_authority") is not False
                or x.get("execution_influence") is not False
                or x.get("forward_verified") is not False
                or x.get("notionals_or_compounding_modelled") is not False
                or len(x.get("annual",[]))!=8):
                raise ValueError("R32_SOURCE_OR_EXECUTION_CONTRACT_INVALID:"+str(file))
            if tf in ("1h","4h"):
                if src.get("scope")!="spliced":
                    raise ValueError("R32_BAD_INTRADAY_SOURCE")
            elif src.get("scope")!="FULL_D1_W1_FROM_2012":
                raise ValueError("R32_BAD_DAILY_SOURCE")
            obs=[]
            annual=[]
            for yr,q in zip(range(2019,2027),x["annual"]):
                if q.get("year")!=yr:raise ValueError("R32_MISSING_YEAR")
                rows=q.get("trades",[])
                if q["n"]!=len(rows):
                    raise ValueError("R32_ANNUAL_SIGNALS_NOT_TRADES")
                val=sum(t["net_cost2_usd_1oz"] for t in rows)
                if not math.isclose(val,q["net"],abs_tol=1e-6):
                    raise ValueError("R32_ANNUAL_PNL_MISMATCH")
                if rows and any(
                    t["exit_bar"]<=t["signal_bar"]
                    or t["entry_time"]>t["exit_time"]
                    for t in rows
                ):raise ValueError("R32_NON_CAUSAL_TRADE")
                annual.append({"year":yr,"n":len(rows),"net":val,
                               "policy":q.get("selected")})
                obs.extend(rows)
            ids=[t["signal_bar"] for t in obs]
            if ids!=sorted(ids):raise ValueError("R32_PORTFOLIO_NOT_CHRONOLOGICAL")
            for earlier,later in zip(obs,obs[1:]):
                if later["signal_bar"]<earlier["exit_bar"]:
                    raise ValueError("R32_CROSS_YEAR_POSITION_OVERLAP")
            pnl=[t["net_cost2_usd_1oz"] for t in obs]
            net=sum(pnl)
            n=len(obs)
            if (n!=x["total_trades"]
                or not math.isclose(net,x["net_usd_1oz_cost2"],abs_tol=1e-6)
                or not math.isclose(net-3*n,x["net_usd_1oz_cost5"],abs_tol=1e-6)):
                raise ValueError("R32_TOTAL_COST_PROFIT_MISMATCH")
            e=0.
            peak=0.
            dd=0.
            for q in pnl:
                e+=q
                peak=max(peak,e)
                dd=max(dd,peak-e)
            if not math.isclose(dd,x["max_realized_dd_usd_1oz"],abs_tol=1e-6):
                raise ValueError("R32_UNVERIFIED_DRAWDOWN")
            good=sum(p for p in pnl if p>0)
            bad=-sum(p for p in pnl if p<0)
            pf=(good/bad) if bad>0 else None
            if pf is not None and not math.isclose(
                pf,x["profit_factor_cost2"],abs_tol=1e-6
            ):raise ValueError("R32_PROFIT_FACTOR_NOT_REPRODUCED")
            posyears=sum(a["net"]>0 for a in annual)
            if posyears!=x["positive_years"]:
                raise ValueError("R32_ANNUAL_STABILITY_MISMATCH")
            p={
                "tf":tf,"mode":mode,"gross_notional":"one fixed troy ounce",
                "candidates_considered":x["candidate_count"],
                "n":n,"net_cost2_usd_oz":net,"net_cost5_usd_oz":net-3*n,
                "profit_factor_cost2":pf,
                "max_realized_dd_usd_oz":dd,
                "profit_to_dd":net/dd if dd else None,
                "positive_years":posyears,
                "annual":annual,
                "source_sha256":hashlib.sha256(raw).hexdigest(),
                "robust":(
                    n>=50 and posyears>=5 and net-3*n>0
                    and pf is not None and pf>1.1
                ),
            }
            entries.append(p)
    return entries


def pareto(entries):
    out=[]
    for a in entries:
        if a["net_cost2_usd_oz"]<=0 or a["n"]==0:
            continue
        dominated=any(
            b is not a and
            b["net_cost2_usd_oz"]>=a["net_cost2_usd_oz"] and
            b["n"]>=a["n"] and
            b["max_realized_dd_usd_oz"]<=a["max_realized_dd_usd_oz"] and
            (b["net_cost2_usd_oz"]>a["net_cost2_usd_oz"]
             or b["n"]>a["n"] or
             b["max_realized_dd_usd_oz"]<a["max_realized_dd_usd_oz"])
            for b in entries
        )
        if not dominated:out.append(a)
    return out


def run():
    data=audit()
    if len(data)!=12:raise ValueError("R32_EXPECTED_TWELVE_SOURCE_RESULTS")
    net=sorted(data,key=lambda x:x["net_cost2_usd_oz"],reverse=True)
    count=sorted((x for x in data if x["net_cost5_usd_oz"]>0),
                 key=lambda x:x["n"],reverse=True)
    stable=sorted((x for x in data if x["robust"]),
                  key=lambda x:x["net_cost2_usd_oz"],reverse=True)
    report={
        "contract":"RIZAN_R32_PROFIT_AND_SIGNALS_LOCK_2012_2026_V1",
        "symbol":"XAUUSD","source":"R30 2012-26 authenticated OHLC",
        "evaluation_years":"2019-2026 (2026 partial)",
        "evaluation_configurations":len(data),
        "total_candidate_scans_cumulative":sum(q["candidates_considered"] for q in data),
        "best_net":net[0],"most_trades_still_positive_at_cost5":count[0] if count else None,
        "robust_winners":stable,"pareto_frontier":pareto(data),
        "baseline_previous_R31_1":REFS,
        "all_results":data,
        "research_only":True,"execution_authority":False,
        "live_promotion":False,
        "limitations":[
            "Selection used previous two years but 2019-26 research folds were inspected repeatedly",
            "Optimized against many entry and exit models; winner's curse and model-selection bias",
            "ATR OHLC stop-first intrabar conservative, but opens/stops/targets not real broker fills",
            "One 1oz position per timeframe; concurrent multi-timeframe portfolio not modelled",
            "Realized drawdown misses floating drawdown and margin risk",
            "2/5 USD cost assumptions exclude measured spread, swap, broker slippage",
            "No automatic ForexScanner signals or cTrader orders",
        ],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    lines=[
        "# RIZAN R32 — Profit + Profitable Signal Count (2012–2026)",
        "",
        "**Research-only. No Frozen V1 or ForexScanner changes.**",
        "",
        "All results are **hypothetical USD per 1 fixed ounce** (not compounded account balance). Entry from next OPEN, OHLC-based ATR trailing/stop/target. Main cost assumption $2/oz, tested $5/oz.",
        "",
        "| TF | Objective | Signals | Net @ $2/oz | Net @ $5/oz | PF | Max realized DD | Positive years |",
        "|---|---|---:|---:|---:|---:|---:|---:|"
    ]
    for a in net:
        lines.append(
            f'| {a["tf"]} | {a["mode"]} | {a["n"]} | '
            f'{a["net_cost2_usd_oz"]:+,.2f} | {a["net_cost5_usd_oz"]:+,.2f} | '
            +('—' if a["profit_factor_cost2"] is None else f'{a["profit_factor_cost2"]:.2f}')
            +f' | {a["max_realized_dd_usd_oz"]:,.2f} | {a["positive_years"]}/8 |'
        )
    lines+=["","## Read-only selection and baseline",
        "",
        f'- Previous simple W1 EMA BUY 4-week baseline: 75 trades, +$2,825.99/oz (PF 2.70), 6/8 positive years.',
        f'- Previous simple D1 EMA+ADX BUY 5-day baseline: 193 trades, +$2,294.64/oz, 6/8 positive years.',
        "- A new R32 candidate is not an improvement merely because of more trades or higher gross profit; compare same 1oz exposure, $5 cost, and positive years.",
        "- No 2019–26 clean pristine OOS remains because many strategy versions have already inspected those years.",
        "- ATR stop loss is not a hard loss limit when price gaps or broker liquidity breaks.",
        "- Do not deploy based on backtests. Forward never-retuned historical-to-live handoff is required.",
        "",
        "## Evidence",
        "",
        "- [R32 original complete multi-timeframe GitHub Actions evidence](https://github.com/rizanrizan93/Forex-scanner/actions/workflows/r32_profit_frequency_atr.yml)",
        "- [Machine-readable research checkpoint](./RIZAN_R32_XAU_PROFIT_FREQUENCY_ATR_LOCK_20261123.json)",
        ""]
    MD.write_text("\n".join(lines))
    print(json.dumps({"stage":"R32_AUDIT_COMPLETE",
       "best_net":{k:net[0][k] for k in ("tf","mode","net_cost2_usd_oz","n","positive_years")},
       "robust":len(stable),"best_frequency":count[0]["n"] if count else None,
       "source_scans":report["total_candidate_scans_cumulative"]},allow_nan=False),flush=True)
    return report

if __name__=="__main__":run()
