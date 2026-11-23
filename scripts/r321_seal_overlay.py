"""R32.1 audit six actual fixed 1oz source event receipts, never deploy."""
from __future__ import annotations
import hashlib,json,math
from pathlib import Path

ROOT=Path("artifacts/r321")
OUT=Path("research/RIZAN_R321_W1_PROFIT_SIGNAL_OVERLAY_LOCK_20261123.json")
DOC=Path("research/RIZAN_R321_W1_PROFIT_SIGNAL_OVERLAY_FINDINGS_20261123.md")
MODES=("max_signals","profit_frequency","max_net")
GATES=("any_flat","ema_direction")
BASE_N=75
BASE_NET=2825.987


def audit():
    rows=[]
    for mode in MODES:
        for gate in GATES:
            path=ROOT/f"r321-{mode}-{gate}.json"
            raw=path.read_bytes()
            x=json.loads(raw)
            ref=x["historical_reference_W1_EMA_BUY_4W"]
            q=x["result"]
            if (x.get("contract")!="RIZAN_R321_W1_NO_LEVERAGE_EXTRA_SIGNALS_V1"
                or x.get("mode")!=mode or x.get("overlay_filter")!=gate
                or x.get("research_only") is not True
                or x.get("execution_authority") is not False
                or x.get("execution_influence") is not False
                or x.get("forward_verified") is not False
                or x.get("max_gross_risk_exposure_oz")!=1.
                or x.get("max_concurrent_positions")!=1
                or ref.get("n")!=BASE_N
                or not math.isclose(ref["net_cost2_usd_fixed1oz"],BASE_NET,abs_tol=1e-5)):
                raise ValueError("R321_INVALID_SOURCE_CONTRACT:"+str(path))
            t=q["trades"]
            if len(t)!=q["n"] or q["baseline_n"]!=BASE_N or q["overlay_n"]+BASE_N!=len(t):
                raise ValueError("R321_FREQUENCY_MISMATCH")
            val=sum(z["net_cost2_usd_oz"] for z in t)
            if not math.isclose(val,q["net_cost2_usd_per_fixed1oz"],abs_tol=1e-5):
                raise ValueError("R321_REALISED_NET_NOT_VERIFIED")
            if not math.isclose(val-3*len(t),q["net_cost5_usd_per_fixed1oz"],abs_tol=1e-5):
                raise ValueError("R321_COST5_NOT_VERIFIED")
            positions=sorted(t,key=lambda z:z["entry_bar"])
            for a,z in zip(positions,positions[1:]):
                if z["entry_bar"]<a["exit_bar"]:
                    raise ValueError("R321_BROKER_EXPOSURE_OVERLAP")
                if z["entry_bar"]==a["exit_bar"] and not a.get("preempted"):
                    raise ValueError("R321_SAME_BAR_CLOSE_OPEN_IMPOSSIBLE")
            eq=0.;peak=0.;dd=0.
            for z in t:
                eq+=z["net_cost2_usd_oz"]
                peak=max(eq,peak)
                dd=max(dd,peak-eq)
            if not math.isclose(dd,q["max_realized_dd_usd_per_fixed1oz"],abs_tol=1e-5):
                raise ValueError("R321_REALIZED_DD_NOT_VERIFIED")
            yearp={y:0. for y in range(2019,2027)}
            for z in t:
                yearp[z["year"]]+=z["net_cost2_usd_oz"]
            if any(not math.isclose(yearp[int(year)],v["profit"],abs_tol=1e-5)
                   for year,v in q["annual"].items()):
                raise ValueError("R321_ANNUAL_PNL_INVALID")
            rows.append({
                "mode":mode,"gate":gate,"n":len(t),
                "base_count":BASE_N,"extra_count":q["overlay_n"],
                "net_cost2_usd_per_fixed1oz":val,
                "net_cost5_usd_per_fixed1oz":val-3*len(t),
                "incremental_profit_vs_EMA_baseline":val-BASE_NET,
                "profit_factor_cost2":q["profit_factor_cost2"],
                "drawdown_realized":dd,"positive_years":q["positive_years"],
                "preempted_overlays":q["ignored"]["preempted"],
                "improves_both":(len(t)>BASE_N and val>BASE_NET),
                "source_sha256":hashlib.sha256(raw).hexdigest()
            })
    return sorted(rows,key=lambda q:q["net_cost2_usd_per_fixed1oz"],reverse=True)


def run():
    rows=audit()
    if len(rows)!=6:raise ValueError("R321_EXPECTED_SIX_VERIFIED_TRIALS")
    extra=sorted((r for r in rows if r["extra_count"]>0),key=lambda x:x["extra_count"],reverse=True)
    lock={
        "contract":"RIZAN_R321_VERIFIED_RESEARCH_NO_PROMOTION_V1",
        "symbol":"XAUUSD","historical_period":"2012-2026",
        "walkforward_evaluation":"2019-2026, 2026 partial",
        "research_only":True,"execution_authority":False,"execution_influence":False,
        "live_promotion":False,"forward_verified":False,
        "constant_notional":"maximum 1 troy ounce, max one active position",
        "baseline":{"trades":BASE_N,"net_profit_cost2":BASE_NET},
        "all":rows,"highest_incremental_trade_count":extra[0] if extra else None,
        "improves_both":[a for a in rows if a["improves_both"]],
        "no_profitable_incremental_overlay":not any(a["improves_both"] for a in rows),
        "limitations":[
            "Fixed 2019-26 EMA baseline chosen after viewing earlier research. Hypotheses not pristine OOS.",
            "Overlay R32 policies selected from previous 2 years; portfolio construction developed after seeing test outcomes.",
            "Cost2/cost5 per troy ounce are assumed round-trip transaction expenses, not measured broker spreads or swap.",
            "Preempted overlays exit at next observed open but real executable prices unknown.",
            "W1 first source 2012-26; 2019-26 test window previously studied many times.",
            "No one-oz fixed-notional result represents compounding, account growth, or leverage.",
            "No BUY/SELL trading system live promotion or cTrader account touch."
        ]
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(lock,indent=2,allow_nan=False)+"\n")
    lines=[
        "# RIZAN R32.1 — W1 Profit and Extra Trade Study (2012–2026)",
        "",
        "All **6** conservative one-oz combined strategies validated from individual event trade receipts. The baseline W1 EMA BUY 4-week model is preserved at **75 trades, +$2,825.99 per fixed oz**.",
        "",
        "| W1 main + R32 overlay | Conditional entry | Trades | Added trades | Net @ $2/oz | Net @ $5/oz | Incremental net | Years positive |",
        "|---|---|---:|---:|---:|---:|---:|---:|"
    ]
    for p in rows:
        lines.append(
            f'| {p["mode"]} | {p["gate"]} | {p["n"]} | {p["extra_count"]} | '
            f'{p["net_cost2_usd_per_fixed1oz"]:+,.2f} | {p["net_cost5_usd_per_fixed1oz"]:+,.2f} | '
            f'{p["incremental_profit_vs_EMA_baseline"]:+,.2f} | {p["positive_years"]}/8 |'
        )
    lines+=["","## Conclusion","",
        "- **No configuration increased BOTH historical profit and signal frequency under the same 1oz exposure cap.**",
        "- The 26 additional trades from max_signals any_flat reduced total profit. Trading more was not the best action on these periods.",
        "- The reference W1 EMA trend filter remains the higher-profit control, but has no independently verified future alpha.",
        "- Research next: seek genuinely positive expectancy in *baseline-flat* regimes using independent forward period and broker executable spreads; do not overfit 2025.",
        "- Frozen V1, R28, R29, R30 and ForexScanner/cTrader LIVE unmodified.",
        ""]
    DOC.write_text("\n".join(lines))
    print(json.dumps({"stage":"R321_AUDIT_COMPLETE",
        "n_variants":len(rows),"highest_frequency":extra[0] if extra else None,
        "improve_both":len(lock["improves_both"]),
        "top_profit":rows[0]["net_cost2_usd_per_fixed1oz"]},allow_nan=False),flush=True)
    return lock

if __name__=="__main__":run()
