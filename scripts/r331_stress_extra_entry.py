"""R33.1: verify extra-entry uplift survives annual and trade-size stress.

All 15 original R33 JSON receipts are re-audited from completed GitHub
replay, not a refit or rerun with tuned historical parameters. Selection
bias remains: winner inspected across fifteen researched variants and
2019-26 periods already viewed. Bootstrap by YEAR is merely a diagnostic.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT=Path("artifacts/r33")
OUT=Path("research/RIZAN_R331_W1_D1_EXTRA_ENTRY_ROBUSTNESS_20261124.json")
REPORT=Path("research/RIZAN_R331_W1_D1_EXTRA_ENTRY_ROBUSTNESS_20261124.md")
MODES=("max_net","max_signals","profit_frequency")
GATES=("any","d1_ema","d1_adx","d1_breakout","prior_week_ema")
BASE_N=75
BASE_NET=2825.987
YEARS=tuple(range(2019,2027))
CONTRACT="RIZAN_R331_EXPLORATORY_EXTRA_ENTRY_STRESS_REPORT_V1"

def audit():
    rows=[]
    baseline_signatures=None
    for mode in MODES:
        for gate in GATES:
            file=ROOT/f"r33-{mode}-{gate}.json"
            raw=file.read_bytes()
            q=json.loads(raw)
            result=q["result"]
            if (q.get("contract")!="RIZAN_R33_W1_D1_IDLE_EXTRA_ENTRY_NO_OVERLAP_20261124_V1"
                or q.get("mode")!=mode or q.get("gate")!=gate
                or q.get("research_only") is not True
                or q.get("execution_authority") is not False
                or q.get("max_portfolio_exposure_oz")!=1.
                or result.get("main_trades")!=BASE_N
                or result.get("additional_trades")+BASE_N!=result.get("total_trades")):
                raise ValueError("R331_UNVERIFIED_OR_INCOMPLETE_SOURCE")
            trades=result["trade_receipts"]
            mains=sorted((
                t["entry_time"],t["exit_time"],t["net_cost2_usd_oz"]
            ) for t in trades if t["kind"]=="main")
            overlays=[t for t in trades if t["kind"]=="overlay"]
            if len(mains)!=BASE_N or sum(1 for t in overlays if t.get("preempted"))>len(overlays):
                raise ValueError("R331_INVALID_ORIGINAL_MAIN_OR_OVERLAY")
            if baseline_signatures is None:baseline_signatures=mains
            elif mains!=baseline_signatures:
                raise ValueError("R331_MAIN_W1_BASELINE_WAS_CHANGED")
            base_sum=sum(x[2] for x in mains)
            if not math.isclose(base_sum,BASE_NET,abs_tol=1e-5):
                raise ValueError("R331_FROZEN_BASELINE_PROFIT_NOT_REPRODUCED")
            extra=np.array([float(t["net_cost2_usd_oz"]) for t in overlays],float)
            extra_sum=float(extra.sum())
            if not math.isclose(extra_sum+BASE_NET,result["net_cost2_usd_per_1oz"],abs_tol=1e-5):
                raise ValueError("R331_INCREMENTAL_PROFIT_NOT_RECONCILED")
            if not math.isclose(extra_sum,result["incremental_net_vs_frozen_w1"],abs_tol=1e-5):
                raise ValueError("R331_SOURCE_INCREMENTAL_MISMATCH")
            e_year={
                str(y):float(sum(t["net_cost2_usd_oz"] for t in overlays
                                 if t["entry_year"]==y))
                for y in YEARS
            }
            rng=np.random.default_rng(3301)
            vec=np.array(list(e_year.values()),float)
            sampled=np.sum(rng.choice(vec,size=(20000,8),replace=True),axis=1)
            best=np.max(extra) if len(extra) else 0.
            worst=np.min(extra) if len(extra) else 0.
            standalone_pf=(float(extra[extra>0].sum()/-extra[extra<0].sum())
                           if np.any(extra<0) else None)
            row={
                "mode":mode,"gate":gate,"total_trades":result["total_trades"],
                "extra_trades":len(extra),
                "extra_wins":int((extra>0).sum()),"extra_losses":int((extra<0).sum()),
                "extra_net_cost2_usd_oz":extra_sum,
                "extra_net_cost5_usd_oz":extra_sum-3*len(extra),
                "extra_net_cost10_usd_oz":extra_sum-8*len(extra),
                "combined_net_cost2_usd_oz":float(result["net_cost2_usd_per_1oz"]),
                "combined_net_cost5_usd_oz":float(result["net_cost5_usd_per_1oz"]),
                "yearly_extra_net_cost2":e_year,
                "yearly_positive_extra":int(sum(v>0 for v in e_year.values())),
                "extra_years_with_trades":int(sum(
                    any(t["entry_year"]==y for t in overlays) for y in YEARS)),
                "extra_net_excluding_2025":extra_sum-e_year["2025"],
                "extra_net_2019_2022":float(sum(e_year[str(y)] for y in range(2019,2023))),
                "extra_net_2023_2026":float(sum(e_year[str(y)] for y in range(2023,2027))),
                "largest_single_extra_profit":float(best),
                "largest_single_extra_loss":float(worst),
                "standalone_extra_profit_factor":standalone_pf,
                "leave_one_year_out_min_extra_net":extra_sum-max(vec),
                "bootstrap_year_block_95pct_interval":list(map(float,np.quantile(sampled,[.025,.975]))),
                "bootstrap_annual_resample_positive_fraction":float(np.mean(sampled>0)),
                "original_receipt_sha256":hashlib.sha256(raw).hexdigest(),
                "passes_hard_operational_profit_constraints":bool(
                    len(extra)>0 and extra_sum>0 and
                    extra_sum-3*len(extra)>0 and
                    result["positive_years"]>=6 and
                    result["max_realized_dd_usd_per_1oz"]<=570.133*1.25),
            }
            rows.append(row)
    return sorted(rows,key=lambda t:t["extra_net_cost2_usd_oz"],reverse=True)

def run():
    data=audit()
    if len(data)!=15:raise ValueError("R331_ALL_15_REPLAY_RECEIPTS_REQUIRED")
    champion=data[0]
    result={
        "contract":CONTRACT,
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"live_promotion":False,
        "forward_validated":False,
        "historical_data":"XAUUSD D1+W1 2012-2026",
        "evaluated_years":"2019-2026, 2026 partial",
        "frozen_base_W1":{"net_cost2_usd_oz":BASE_NET,"trades":BASE_N},
        "reviewed_variants":15,"best_incremental_candidate":champion,
        "all_candidates":data,
        "risk_warnings":[
            "Resampling annual PnL is not an independent out-of-sample hypothesis test",
            "Many historical strategies and 2019–26 years examined; winner selection inflates apparent bootstrap confidence",
            "Positive contributions may be dominated by isolated large trend trades",
            "No executable FP Markets spreads, swaps, financing, broker latency or slippage",
            "Realized-close DD omits floating loss, margin and tail gaps",
            "Original R32 annual policy changes; no permanent future frozen live configuration",
            "Research only and no change to frozen V1 or ForexScanner/CTRADER"
        ],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    report=[
        "# RIZAN R33.1 — W1 + D1 Additional-Entry Risk Stress",
        "",
        "**Historical exploratory evidence only; NOT prospectively validated.**",
        "",
        "Existing W1 trend base: 75 signals, +$2,825.99/1oz under assumed $2/oz cost. R33 D1 overlays execute only when W1 is not active, and never exceed 1oz combined exposure.",
        "",
        "| D1 source | Filter | Extra trades | Extra net @ $2/oz | Extra net @ $5/oz | Extra net @ $10/oz | Excluding 2025 |",
        "|---|---|---:|---:|---:|---:|---:|"
    ]
    for q in data:
        report.append(
            f'| {q["mode"]} | {q["gate"]} | {q["extra_trades"]} | '
            f'{q["extra_net_cost2_usd_oz"]:+,.2f} | '
            f'{q["extra_net_cost5_usd_oz"]:+,.2f} | '
            f'{q["extra_net_cost10_usd_oz"]:+,.2f} | '
            f'{q["extra_net_excluding_2025"]:+,.2f} |'
        )
    report+=["",
        "## Most profitable additional-entry rule, by annual contribution",
        "",
        "| Year | Extra net $/1oz (cost $2) |",
        "|---|---:|"
    ]
    for y,q in champion["yearly_extra_net_cost2"].items():
        report.append(f'| {y} | {q:+,.2f} |')
    lo,hi=champion["bootstrap_year_block_95pct_interval"]
    report+=["",
        "## Cautions",
        "",
        f'- Selected after 15 tested combinations: {champion["mode"]} with {champion["gate"]}.',
        f'- Incremental 2019–2022 total {champion["extra_net_2019_2022"]:+,.2f}; 2023–2026 total {champion["extra_net_2023_2026"]:+,.2f}.',
        f'- Remove 2025 incremental PnL: {champion["extra_net_excluding_2025"]:+,.2f}. Largest individual profit {champion["largest_single_extra_profit"]:+,.2f}, loss {champion["largest_single_extra_loss"]:+,.2f}.',
        f'- Bootstrap resampling 8 calendar-year outcomes, 20k draws: 95% diagnostic interval [{lo:+,.2f}, {hi:+,.2f}]. THIS IS NOT a forward confidence interval after multiple historical searches.',
        "- Execution spread/overnight swap and floating drawdown not yet measured, so cannot promote to LIVE.",
        "",
        "## Evidence",
        "",
        "- [Original 15 R33 XAU backtests](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45255941738)",
        "- [Machine-readable risk evidence](./RIZAN_R331_W1_D1_EXTRA_ENTRY_ROBUSTNESS_20261124.json)",
        ""]
    REPORT.write_text("\n".join(report))
    print(json.dumps({
        "stage":"R331_ROBUSTNESS_COMPLETE",
        "best":{"mode":champion["mode"],"gate":champion["gate"],
                "n":champion["extra_trades"],
                "net2":champion["extra_net_cost2_usd_oz"],
                "net5":champion["extra_net_cost5_usd_oz"],
                "ex2025":champion["extra_net_excluding_2025"],
                "bootstrap_year_ci":champion["bootstrap_year_block_95pct_interval"]},
        "passed_historic_operation_gates":sum(
            q["passes_hard_operational_profit_constraints"] for q in data),
    },allow_nan=False),flush=True)
    return result

if __name__=="__main__":run()
