"""R33 audit 15 historically simulated W1+ D1 extra entry portfolios.

Independently check recorded price PnL, two cost cases, annual receipts,
max one-ounce nonoverlapping exposure and baseline unchanged. Do not
promote an outcome selected from repeatedly revisited historical data.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

ROOT=Path("artifacts/r33")
LOCK=Path("research/RIZAN_R33_W1_D1_IDLE_ALPHA_FROZEN_20261124.json")
REPORT=Path("research/RIZAN_R33_W1_D1_IDLE_ALPHA_FINDINGS_20261124.md")
MODES=("max_net","max_signals","profit_frequency")
GATES=("any","d1_ema","d1_adx","d1_breakout","prior_week_ema")
BASE_N=75
BASE_NET=2825.987


def audit():
    out=[]
    for mode in MODES:
        for gate in GATES:
            path=ROOT/f"r33-{mode}-{gate}.json"
            raw=path.read_bytes()
            o=json.loads(raw)
            r=o["result"]
            if (o.get("contract")!="RIZAN_R33_W1_D1_IDLE_EXTRA_ENTRY_NO_OVERLAP_20261124_V1"
                or o.get("mode")!=mode or o.get("gate")!=gate
                or o.get("evaluation_years")!=list(range(2019,2027))
                or o.get("baseline_trades")!=BASE_N
                or not math.isclose(o.get("baseline_net_cost2_usd_per_1oz"),BASE_NET,abs_tol=1e-5)
                or o.get("max_portfolio_exposure_oz")!=1.
                or o.get("max_concurrent_positions")!=1
                or o.get("research_only") is not True
                or o.get("execution_authority") is not False
                or o.get("execution_influence") is not False
                or o.get("forward_verified") is not False
                or o.get("pyramiding") is not False
                or o.get("leverage") is not False):
                raise ValueError("R33_MODEL_CONTRACT_INVALID:"+path.name)
            trades=r["trade_receipts"]
            if (len(trades)!=r["total_trades"]
                or sum(x["kind"]=="main" for x in trades)!=BASE_N
                or sum(x["kind"]=="overlay" for x in trades)!=r["additional_trades"]
                or r["main_trades"]!=BASE_N):
                raise ValueError("R33_TRADE_COUNT_UNREPRODUCIBLE")
            pnl=[float(x["net_cost2_usd_oz"]) for x in trades]
            net=sum(pnl)
            if (not math.isclose(net,r["net_cost2_usd_per_1oz"],abs_tol=1e-5)
                or not math.isclose(net-3*len(pnl),r["net_cost5_usd_per_1oz"],abs_tol=1e-5)
                or not math.isclose(net-BASE_NET,r["incremental_net_vs_frozen_w1"],abs_tol=1e-5)):
                raise ValueError("R33_PROFIT_COST_NOT_RECONCILED")
            in_order=sorted(trades,key=lambda x:x["entry_time"])
            for a,z in zip(in_order,in_order[1:]):
                if a["exit_time"]>z["entry_time"]:
                    raise ValueError("R33_OVERLAP_INVALID")
            p=0.
            peak=0.
            dd=0.
            for q in pnl:
                p+=q;peak=max(peak,p);dd=max(dd,peak-p)
            if not math.isclose(dd,r["max_realized_dd_usd_per_1oz"],abs_tol=1e-5):
                raise ValueError("R33_REALIZED_DRAWDOWN_UNREPRODUCIBLE")
            annual={}
            for y in range(2019,2027):
                vals=[q["net_cost2_usd_oz"] for q in trades if q["entry_year"]==y]
                if (r["annually"][str(y)]["n"]!=len(vals)
                    or not math.isclose(sum(vals),r["annually"][str(y)]["net"],abs_tol=1e-5)):
                    raise ValueError("R33_ANNUAL_TRADES_INVALID")
                annual[str(y)]={"n":len(vals),"net":sum(vals)}
            n=len(trades)
            row={
                "mode":mode,"gate":gate,"n":n,
                "additional_trades":r["additional_trades"],
                "net_cost2_usd_oz":net,"net_cost5_usd_oz":net-3*n,
                "incremental_net_cost2_usd_oz":net-BASE_NET,
                "dd_realized_usd_oz":dd,
                "positive_years":r["positive_years"],
                "profit_factor":r["profit_factor_cost2"],
                "annual":annual,
                "source_receipt_sha256":hashlib.sha256(raw).hexdigest(),
                "increases_profit_and_frequency":n>BASE_N and net>BASE_NET,
                "passes_conservative_all":{
                    "more_trades":n>BASE_N,
                    "higher_net_cost2":net>BASE_NET,
                    "higher_net_cost5":net-3*n>BASE_NET-3*BASE_N,
                    "positive_years_at_least_six":r["positive_years"]>=6,
                    "dd_no_worse_than_25pct":dd<=570.133*1.25
                }
            }
            row["promote_to_live"]=False
            out.append(row)
    return sorted(out,key=lambda x:x["net_cost2_usd_oz"],reverse=True)


def seal():
    rows=audit()
    if len(rows)!=15:raise ValueError("R33_EXPECTED_15_RUNS")
    q=sorted(rows,key=lambda r:(r["additional_trades"],r["net_cost2_usd_oz"]),reverse=True)
    good=[r for r in rows if r["increases_profit_and_frequency"]]
    strict=[r for r in rows if all(r["passes_conservative_all"].values())]
    lock={
        "contract":"RIZAN_R33_W1_D1_SINGLE_OUNCE_RESEARCH_LOCK_20261124_V1",
        "symbol":"XAUUSD",
        "history":"2012-2026","evaluation":"2019-2026, partial last year",
        "research_only":True,"execution_authority":False,
        "execution_influence":False,"live_promotion":False,
        "forward_validated":False,
        "constant_exposure":"max 1 oz combined W1+D1",
        "n_configs_tested":len(rows),
        "baseline":{"n":BASE_N,"net_cost2_usd_oz":BASE_NET,
                    "net_cost5_usd_oz":BASE_NET-3*BASE_N,
                    "original_unoptimized":"R31.1 W1 EMA BUY hold 4 weeks"},
        "highest_net":rows[0],
        "most_additional_trades":q[0],
        "profit_and_trade_improvement":good,
        "strict_improvement":strict,
        "all_configs":rows,
        "limitations":[
            "D1 source annual strategies selected in previous two calendar years, BUT multiple replay researches 2019–2026 are not blind holdouts",
            "Five post-hoc D1 extra-entry gates tested after seeing R32.1; selection bias possible",
            "W1 primary trades never overlap D1 overlays, position cap one troy ounce",
            "Assumed $2/$5 per oz costs; FP Markets spread, swap, real slippage, margin not measured",
            "Conservative next-Monday W1 reavailability; intrabar stop/MAE and margin risk not modelled",
            "No ForexScanner, Frozen V1 or cTrader LIVE changes and no deployment authority",
        ]
    }
    LOCK.parent.mkdir(parents=True,exist_ok=True)
    LOCK.write_text(json.dumps(lock,indent=2,allow_nan=False)+"\n")
    lines=[
        "# RIZAN R33 — D1 Add-on During W1 EMA Idle Windows (2012–2026)",
        "",
        "**Research-only, no live trading model promoted.**",
        "",
        "Original primary W1 EMA BUY 4-week: **75 trades, +$2,825.99 per fixed troy ounce** at hypothetical $2/oz round-trip cost, 6/8 positive test years.",
        "",
        "R33 D1 candidates are frozen prior-year R32 D1 signals; evaluation 2019–2026, 2026 incomplete. Extra D1 trades only when W1 primary is flat; at next W1 open, D1 is closed first. Combined exposure never exceeds 1 troy ounce.",
        "",
        "| D1 source | Closed-candle filter | Total trades | Added | Net @ $2 | Net @ $5 | Increment vs baseline | Realized DD | Positive years |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|"
    ]
    for r in rows:
        lines.append(
            f'| {r["mode"]} | {r["gate"]} | {r["n"]} | {r["additional_trades"]} | '
            f'{r["net_cost2_usd_oz"]:+,.2f} | {r["net_cost5_usd_oz"]:+,.2f} | '
            f'{r["incremental_net_cost2_usd_oz"]:+,.2f} | '
            f'{r["dd_realized_usd_oz"]:,.2f} | {r["positive_years"]}/8 |'
        )
    lines+=["",
        "## Decision",
        "",
        f'- {len(good)} configurations increased BOTH trade count and simulated net vs original 75-trade W1 strategy.',
        f'- {len(strict)} configurations also improved $5/oz net with >=6 positive years and DD <=1.25× baseline.',
        "- Even a positive finding would remain exploratory rather than independent forward confirmation due to reuse of 2019–2026 research years.",
        "- Do not deploy any R33 signal to live, do not modify Frozen V1 or ForexScanner forecast controls.",
        "",
        "## Evidence",
        "",
        "- [Actual GitHub Actions run: R33 W1 + D1 overlay](https://github.com/rizanrizan93/Forex-scanner/actions/workflows/r33_w1_d1_idle_alpha.yml)",
        "- [Reproducible machine-readable result receipt](./RIZAN_R33_W1_D1_IDLE_ALPHA_FROZEN_20261124.json)",
        ""
    ]
    REPORT.write_text("\n".join(lines))
    print(json.dumps({"stage":"R33_AUDIT_COMPLETE","count":len(rows),
        "top":{"mode":rows[0]["mode"],"gate":rows[0]["gate"],
               "net":rows[0]["net_cost2_usd_oz"],"n":rows[0]["n"]},
        "max_frequency":{"mode":q[0]["mode"],"gate":q[0]["gate"],
                         "extra":q[0]["additional_trades"],"net":q[0]["net_cost2_usd_oz"]},
        "improves_both":len(good),"strict":len(strict)}),flush=True)
    return lock

if __name__=="__main__":seal()
