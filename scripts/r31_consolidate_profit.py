"""RIZAN R31 final immutable ranked evidence; no trading promotion.

Read all 30 FULL historical replay receipts, validate each annual trade PnL,
then rank highest hypothetical one-ounce NET profit alongside drawdown and
cost sensitivities. This script cannot create orders or broker positions.
"""
from __future__ import annotations
import hashlib,json,math
from pathlib import Path
from collections import defaultdict

ROOT=Path("artifacts/r31")
OUT=Path("research/RIZAN_R31_XAU_MAX_NET_2012_2026_RESEARCH_LOCK_20261123.json")
REPORT=Path("research/RIZAN_R31_XAU_MAX_NET_2012_2026_FINDINGS_20261123.md")
EXPECTED={
    "1h":(1,2,4),
    "4h":(1,2,3),
    "1D":(1,2),
    "1W":(1,2),
}
MODES=("max_net","net_dd","profit_frequency")
CONTRACT="RIZAN_R31_XAU_NET_PROFIT_FROZEN_RESEARCH_V1"
COST=(.7,2.,5.)
MIN_TRADE=45
MIN_POS_YEARS=5


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load():
    rows=[]
    for tf,hs in EXPECTED.items():
        for hold in hs:
            for mode in MODES:
                filename=f"r31-{tf}-h{hold}-{mode}.json"
                path=ROOT/filename
                raw=path.read_bytes()
                x=json.loads(raw)
                if (x.get("contract")!=CONTRACT or x.get("timeframe")!=tf
                    or x.get("hold_candles")!=hold or x.get("mode")!=mode
                    or x.get("research_only") is not True
                    or x.get("execution_authority") is not False
                    or x.get("execution_influence") is not False
                    or x.get("forward_verified") is not False
                    or x.get("evaluation_years")!=list(range(2019,2027))
                    or x.get("cost_scenario_main_usd_oz")!=2.
                    or x.get("partial_2026") is not True
                    or x.get("backtest_entry")!="NEXT_BAR_OPEN"
                    or x.get("position_rule")!="MAX_ONE_1OZ_POSITION_PER_TIMEFRAME_NO_OVERLAP"
                    or len(x.get("annual",[]))!=8):
                    raise ValueError("R31_RESULT_CONTRACT_MISMATCH:"+filename)
                sc=x.get("price_source",{})
                if tf in ("1h","4h"):
                    if sc.get("scope")!="spliced" or set(map(int,sc.get("actual_years",[])))!=set(range(2012,2027)):
                        raise ValueError("R31_INTRADAY_ARCHIVE_INCOMPLETE:"+filename)
                elif sc.get("scope")!="FULL_D1_W1_FROM_2012":
                    raise ValueError("R31_DAILY_ARCHIVE_INCOMPLETE:"+filename)
                pnl=[]
                yearly=[]
                for y,a in enumerate(x["annual"],start=2019):
                    if a["year"]!=y:
                        raise ValueError("R31_YEAR_ORDER_MISMATCH:"+filename)
                    n=len(a.get("trade_receipts",[]))
                    if n!=a["total_trades"] or n!=a["signals_buy"]+a["signals_sell"]:
                        raise ValueError("R31_TRADE_COUNT_MISMATCH:"+filename)
                    receipts=a["trade_receipts"]
                    idx=[v["bar_index"] for v in receipts]
                    if idx!=sorted(idx) or len(set(idx))!=len(idx):
                        raise ValueError("R31_OVERLAPPING_SIGNAL_INDEX_MISMATCH:"+filename)
                    values=[float(v["net_usd_oz"]) for v in receipts]
                    if not math.isclose(sum(values),a["net_profit_usd_per_1oz"],abs_tol=1e-7):
                        raise ValueError("R31_ANNUAL_PROFIT_NOT_REPRODUCIBLE:"+filename)
                    pnl.extend(values)
                    yearly.append(float(a["net_profit_usd_per_1oz"]))
                net=sum(pnl)
                n=len(pnl)
                if n!=x["total_trades"] or not math.isclose(
                    net,x["hypothetical_net_profit_usd_per_1oz"],abs_tol=1e-6
                ):
                    raise ValueError("R31_TOTAL_PROFIT_MISMATCH:"+filename)
                peak=0.
                curve=0.
                drawdown=0.
                for p in pnl:
                    curve+=p
                    peak=max(peak,curve)
                    drawdown=max(drawdown,peak-curve)
                if not math.isclose(
                    drawdown,x["hypothetical_max_realized_drawdown_usd_per_1oz"],abs_tol=1e-5
                ):
                    raise ValueError("R31_DRAW_DOWN_MISMATCH:"+filename)
                for c in COST:
                    expected=net+(2.-c)*n
                    if not math.isclose(expected,x["cost_sensitivity_net_profit"][str(c)],abs_tol=1e-5):
                        raise ValueError("R31_COST_SCENARIO_MISMATCH:"+filename)
                gains=sum(p for p in pnl if p>0)
                losses=-sum(p for p in pnl if p<0)
                pf=(gains/losses if losses>0 else None)
                positive=sum(y>0 for y in yearly)
                row={
                    "tf":tf,"hold":hold,"mode":mode,
                    "evaluated_strategies":x["candidate_rules_considered"],
                    "profit_positive_selection_cases":x["strategy_evaluations_with_positive_validation_profit"],
                    "signals":n,
                    "net_profit_usd_per_fixed_1oz":net,
                    "gross_profit_factor_after_2usd_cost":pf,
                    "profit_to_realized_dd":net/drawdown if drawdown else None,
                    "max_realized_drawdown_usd_per_fixed_1oz":drawdown,
                    "positive_test_years":positive,
                    "net_at_0_7_cost":x["cost_sensitivity_net_profit"]["0.7"],
                    "net_at_5_cost":x["cost_sensitivity_net_profit"]["5.0"],
                    "net_by_year":{str(y):round(p,5) for y,p in zip(range(2019,2027),yearly)},
                    "original_receipt_sha256":sha(raw),
                    "filename":filename,
                    "robust_eligible":n>=MIN_TRADE and positive>=MIN_POS_YEARS and
                        net>0 and x["cost_sensitivity_net_profit"]["5.0"]>0 and
                        (pf is not None and pf>1.1)
                }
                rows.append(row)
    return rows


def run():
    rows=load()
    if len(rows)!=30:raise ValueError("R31_INCOMPLETE_30_RUN_MATRIX")
    ranked=sorted(rows,key=lambda x:x["net_profit_usd_per_fixed_1oz"],reverse=True)
    robust=sorted((x for x in rows if x["robust_eligible"]),
                  key=lambda x:x["net_profit_usd_per_fixed_1oz"],reverse=True)
    bytf={
        tf:sorted((x for x in rows if x["tf"]==tf),
                  key=lambda x:x["net_profit_usd_per_fixed_1oz"],reverse=True)[:3]
        for tf in EXPECTED
    }
    ddrank=sorted(
        (x for x in rows if x["profit_to_realized_dd"] is not None and x["net_profit_usd_per_fixed_1oz"]>0),
        key=lambda x:x["profit_to_realized_dd"],reverse=True
    )
    report={
        "contract":"RIZAN_R31_LARGE_SCALE_PROFIT_REPORT_20261123_V1",
        "symbol":"XAUUSD","history":"2012-2026",
        "evaluation_years":"2019-2026, 2026 partial",
        "source":"R30 SHA-verified spliced H1/H4 and original R9.8 D1/W1",
        "frozen_from_run_name":"R31 XAU 2012-2026 Large Scale Max Net Profit Cost Drawdown Research",
        "original_replay_contract":CONTRACT,
        "variants_tested":len(rows),
        "sum_distinct_rules_across_variants":sum(r["evaluated_strategies"] for r in rows),
        "research_only":True,"live_promotion":False,
        "execution_authority":False,"execution_influence":False,
        "hypothetical_cost_main_usd_oz":2.,
        "additional_cost_sensitivity_usd_oz":[.7,5.],
        "trade_unit":"constant 1 troy ounce, max one position per timeframe",
        "top_raw_net":ranked[:10],
        "top_under_predeclared_robustness_filters":robust[:10],
        "top_profit_to_drawdown":ddrank[:10],
        "top_by_timeframe":bytf,
        "all_results":rows,
        "robustness_required":{
            "minimum_trades":MIN_TRADE,"minimum_positive_years":MIN_POS_YEARS,
            "positive_net_even_at_cost_5_per_oz":True,
            "profit_factor_after_cost_2_min":1.1,
        },
        "limitations":[
            "Historical trading proxy only: next-bar OPEN->future CLOSE, not measured fills, commissions or swap",
            "Profit in USD for one fixed oz; cannot be described as account equity, profit dollars per lot, or compound balance",
            "No true FP Markets spread/slippage/liquidity; 0.7,2,5 USD/oz all scenarios",
            "Realized drawdown omits adverse intrabar excursion and broker margin/liquidation risk",
            "More candidate search creates substantial data-mining and multiple-comparison risk",
            "2019–26 evaluation years are not pristine holdouts after earlier research",
            "2026 partial coverage and annual policy variation; forward validation required",
            "No order generation, no cBot changes, no changes to frozen R28/R29/R30 ForexScanner models",
        ],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    lines=[
        "# RIZAN R31 — XAUUSD Net Profit First 2012–2026",
        "",
        "Research frozen, **no live promotion or cBot edits**.",
        "",
        "All amounts are *hypothetical* USD for a constant **one troy ounce per position** with a **$2/oz cost scenario**. They are NOT account balances or executable profits. 2019–2026 walk-forward (partial 2026).",
        "",
        f"## Scanned {len(rows)} independently replayed TF × holding period × selection-mode variants",
        "",
        "| TF | Hold bars | Mode | Trades | Net $/1oz | Max realized DD $/1oz | Net/DD | Net at $5 cost | Positive years |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|"
    ]
    for item in ranked:
        dd=item["max_realized_drawdown_usd_per_fixed_1oz"]
        ratio=item["profit_to_realized_dd"]
        lines.append(
            f'| {item["tf"]} | {item["hold"]} | {item["mode"]} | {item["signals"]} | '
            f'{item["net_profit_usd_per_fixed_1oz"]:+,.2f} | {dd:,.2f} | '
            f'{ratio:.2f} | ' if ratio is not None else
            f'| {item["tf"]} | {item["hold"]} | {item["mode"]} | {item["signals"]} | '
            f'{item["net_profit_usd_per_fixed_1oz"]:+,.2f} | {dd:,.2f} | — | '
        )
        lines[-1]+=f'{item["net_at_5_cost"]:+,.2f} | {item["positive_test_years"]}/8 |'
    if robust:
        p=robust[0]
        lines+=["","## Highest net passing robustness filters","",
                f'- {p["tf"]} hold {p["hold"]} ({p["mode"]}), {p["signals"]} trades, net {p["net_profit_usd_per_fixed_1oz"]:+,.2f} USD/1oz, maximum realized DD {p["max_realized_drawdown_usd_per_fixed_1oz"]:,.2f} USD/1oz.',
                "- This is a research-only candidate. The minimum 45 trades, 5 positive years, net positive under $5 assumed cost, and PF>1.10 do not prove reproducible live profitability."]
    else:
        lines+=["","## Robustness verdict","",
                "- None of the 30 tested policies passed the predeclared five-year and conservative-cost robustness gates. No winner suitable for promotion."]
    lines+=["","## Audit caveats","",
        "- 2012–2018 H1/H4 are independent historical rehosted candles with 2019 byte-identical overlap to original R10; source boundary logged.",
        "- Exit is H-th future completed close; next open is an optimistic fill proxy, not executable FP Markets bid/ask.",
        "- No compounded account value, lot size, leverage, spread measurement or margin model.",
        "- Training and selection use previous 2 fully matured calendar years; entire search had earlier exploratory research on 2019–26. Overfit possible.",
        "- Drawdown is realized-close based and understates potential floating drawdown.",
        "- Preserve the original 30 JSON receipts; never choose a live model based on this historical rank alone.",
        "",
        "## Next actions","",
        "- Research only: additional time splits, multiple vendor source checks, FP Markets spread/slippage measurements, prospective never-retuned shadow receipts and MFE/MAE.",
        "- No changes to Frozen V1, R28, R29, R30 or ForexScanner signal permissions.",
        ""]
    REPORT.write_text("\n".join(lines))
    print(json.dumps({"stage":"R31_LOCKED","count":len(rows),
        "top_raw":ranked[0],"top_robust":robust[0] if robust else None,
        "report":str(REPORT),"lock":str(OUT)},allow_nan=False),flush=True)
    return report


if __name__=="__main__":run()
