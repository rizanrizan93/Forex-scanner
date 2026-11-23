"""Reproducible NOT-READY receipt for frozen R18/R27/R24 live directions.

This script checks the exact archived 2026 selections and source availability.
It NEVER infers a direction from historical accuracy, freshness alone or
future-vintage features. A separate, parity-proven live scorer is required.
"""
from __future__ import annotations
from datetime import UTC,datetime
import argparse,json
from pathlib import Path
import pandas as pd

REF=Path("research_reference/research/archive/xau_r281")
R18=REF/"44957921767/14727659960/r18-asymmetric.json"
R24=REF/"44962650523/14730481343/r24-crossover-1W.json"
R24_SOURCE=REF/"44962650523/14730481343/r24-source-manifest.json"
R27=REF/"44965849048/14731403073/r27-coverage-1W.json"


def load(p):
    if not p.is_file():raise FileNotFoundError(f"MISSING_ARCHIVED_EVIDENCE:{p}")
    return json.loads(p.read_text())


def audited(now):
    ts=pd.Timestamp(now)
    if ts.tzinfo is None:raise ValueError("READINESS_REQUIRES_UTC_TIMESTAMP")
    ts=ts.tz_convert("UTC")
    r18=load(R18)["results"]["1D"]
    r24=load(R24)
    r27=load(R27)
    manifest=load(R24_SOURCE)
    year=2026
    r18_year=next(row for row in r18["annual"] if row["year"]==year)
    r27_year=next(row for row in r27["annual"] if row["year"]==year)
    # R24 may have no valid 2026 test rows after the news source cut off.
    r24_year=next((row for row in r24["annual"] if row["year"]==year),None)
    r18_cfg=r18_year["sell_rule"]
    r27_cfg=r27_year["policies"]["0.7"]["config"][1]
    r24_cfg=(r24_year or {}).get("policies",{}).get("crossover_news_buy_cot_sell",{}).get("sell_config")
    if not isinstance(r18_cfg,dict) or not isinstance(r27_cfg.get("head"),dict):
        raise ValueError("FROZEN_2026_ANNUAL_CONFIG_NOT_RECONSTRUCTIBLE")
    if r18_cfg["group"]!="hybrid" or r27_cfg["head"]["group"]!="macro":
        raise ValueError("FROZEN_2026_HEAD_CONFIG_CHANGED")
    news_through=pd.Timestamp(manifest["news"]["available_through"]).tz_convert("UTC")
    if not news_through < ts:
        raise ValueError("ARCHIVED_NEWS_WINDOW_ASSUMPTION_CHANGED")
    def row(tf,side,version,config,blockers):
        return {
            "tf":tf,"side":side,"version":version,"state":"NOT_READY",
            "direction":"WAIT","historical_config_present":config is not None,
            "original_model_live_parity":"NOT_ESTABLISHED",
            "execution_authority":False,"execution_influence":False,
            "blockers":blockers,
        }
    rows={
        "D1_R18_SELL":row("D1","SELL","R18",r18_cfg,[
            "Frozen annual selection exists, but independently fitted live model and source-feature parity not established",
            "Treasury/FOMC vintage and daily-candle alignment not proven point-in-time for current broker",
        ]),
        "W1_R27_BUY":row("W1","BUY","R27",r27_cfg,[
            "Macro/COT original annual feature matrix has no validated contemporaneous broker inference",
            "R27 extension and post-conflict winner must be parity checked on original matching sample",
            "COT availability_proxy is report date +14 calendar days, not independently verified true release time",
        ]),
        "W1_R24_SELL":row("W1","SELL","R24",r24_cfg,[
            "R24 retrospective news/consensus source is not current",
            "R24 62.50 percent win rate depends on paired opposite BUY head conflict resolution",
            "Live COT/news/FOMC provenance and exact 2026 feature parity not established",
        ]),
    }
    return {
        "contract":"RIZAN_BEST_SIDE_MACRO_READINESS_V1",
        "as_of":ts.isoformat(),"research_only":True,
        "execution_authority":False,"execution_influence":False,
        "news_source_last_available":news_through.isoformat(),
        "last_cot_report_in_archived_source":manifest["cot"]["last_report"],
        "last_treasury_day_in_archived_source":manifest["treasury"]["DGS2"]["last"],
        "rows":rows,
        "warning":"READINESS ONLY. No D1/W1 signals or permission to place orders.",
    }


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="artifacts/best_side_macro_readiness.json")
    args=parser.parse_args()
    report=audited(datetime.now(UTC))
    p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({key:{"state":r["state"],"blockers":r["blockers"]}
                      for key,r in report["rows"].items()}))
