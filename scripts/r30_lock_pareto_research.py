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
    def f_pct(v):return "—" if v is None else f"{100*v:.2f}%"
    lines=[
        "# RIZAN R30 — XAUUSD Direction Precision × Signal Frequency (2012–2026)",
        "",
        "**Research freeze: 23 November 2026. Read-only; no live model promotion.**",
        "",
        "## Dataset, target, and validation",
        "",
        "- Historical OHLC coverage: **2012–2026**. D1/W1 use original R9.8 daily archives; H1/H4 use SHA-verified 2012–2018 alternate archive plus original R10 2019–2026.",
        "- 2019 overlap check: independently generated H1/H4 candle CSV SHA256 is **identical** to original R10 for the same 2019 bars. This improves source continuity, but does not prove original 2012–2018 provenance is identical.",
        "- Evaluation **2019–2026**, after historical training and prior-year model selection. Next completed candle close-to-close direction. Annual 2026 ends at available source date.",
        "- Models: shallow logistic/HGB, regime/event features, 16 predeclared gate candidates and six thresholds, independently selected BUY/SELL.",
        "- Three objectives: Precision, Balanced, High Frequency. Historical price-based net uses only **assumed $0.70/oz cost**, not true broker executable spreads or slippage.",
        "- **None of the 2019–2026 evaluation years are a clean independent untouched holdout** due extensive prior RIZAN research; do not call the numbers forecast certainty.",
        "",
        "## Actual pooled results (all years 2019–2026)",
        "",
        "| TF | Variant | BUY correct/n | BUY acc | BUY avg net $/oz | SELL correct/n | SELL acc | SELL avg net $/oz | Total signals | Coverage |",
        "|---|---|---|---:|---:|---|---:|---:|---:|---:|"
    ]
    for tf in ("H1","H4","D1","W1"):
        for q in rows[tf][0]["variants"]:
            b=q["BUY"];v=q["SELL"]
            netb=b.get("net_mean_after_assumed_cost_usd_oz")
            nets=v.get("net_mean_after_assumed_cost_usd_oz")
            lines.append(
                f'| {tf} | {q["mode"]} | {b["correct"]}/{b["n"]} | {f_pct(b.get("accuracy"))} | '
                +('—' if netb is None else f'{netb:+.2f}')
                +f' | {v["correct"]}/{v["n"]} | {f_pct(v.get("accuracy"))} | '
                +('—' if nets is None else f'{nets:+.2f}')
                +f' | {q["signals"]} | {f_pct(q["coverage"])} |'
            )
    lines+=["","## Frozen winners and limitations","",
        "- **W1 BUY High Frequency: 96/152 = 63.16%**, net +$17.33/oz. Wilson lower95 about 55.25%, so statistical confidence does not establish true accuracy above 60%. Independent annual policy changes.",
        "- **H4 BUY Balanced: 449/810 = 55.43%**, net +$0.19/oz. H4 High Frequency: 653/1191 = 54.83%, net negative. More signals were obtained at the cost of lower accuracy and poorer mean return.",
        "- H1 and D1 do not achieve reliable net-positive directional precision under this search.",
        "- H4 precision in the 2024–2026-only research R29.1/R29.2 must **not** be confused with the more demanding 2019–2026 test.",
        "- No candidate satisfies simultaneous >60% BUY and SELL with positive net and annual stability in the same timeframe.",
        "- Source year filename **2026** in independent HF archive was detected to contain **2025 timestamps only** and excluded. Real 2026 intraday data comes strictly from the original R10 2026 shard.",
        "",
        "## W1 High Frequency: annual model and outcomes",
        "",
        "| Test year | Frozen prior-year-selected policy | BUY correct/n | BUY accuracy | BUY net $/oz |",
        "|---|---|---|---:|---:|"
    ]
    for q in annual["W1_BUY_HIGH_FREQUENCY"]:
        met=q["evaluation"];policy=q["chosen_previous_year_policy"]
        if met is None:
            lines.append(f'| {q["year"]} | none | — | — | — |')
        else:
            spec=("none" if policy is None else
                  f'{policy["model"]} / {policy["group"]} / {policy["gate"]} / {policy["threshold"]}')
            lines.append(f'| {q["year"]} | {spec} | {met["correct"]}/{met["n"]} | '
                         +f'{f_pct(met["accuracy"])} | {met["net_mean_usd_oz"]:+.2f} |')
    lines+=[
        "",
        "## Deployment status and evidence",
        "",
        "- **Status:** RESEARCH-FROZEN, not deployed as new BUY/SELL forecast. Must repeat against forward never-retuned candles and verify source/execution parity.",
        "- GitHub Actions original 2012–2026 daily research: [run 45182264766](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45182264766).",
        "- GitHub Actions 2012–2026 H1/H4 15-year splice and source overlap: [run 45184178972](https://github.com/rizanrizan93/Forex-scanner/actions/runs/45184178972).",
        "- Full machine-readable frozen annual policies, checksums and results: [RIZAN_R30_2012_2026_PARETO_RESEARCH_LOCK_20261123.json](./RIZAN_R30_2012_2026_PARETO_RESEARCH_LOCK_20261123.json).",
        "- Existing Frozen V1 cTrader LIVE, R28.1, R29.2 H4 research SHADOW remain untouched.",
        ""
    ]
    REPORT.write_text(chr(10).join(lines))
    print("R30_LOCK_COMPLETE",str(LOCK),sha(LOCK),flush=True)
    print("R30_REPORT_COMPLETE",str(REPORT),sha(REPORT),flush=True)
    return payload


if __name__=="__main__":
    lock()
