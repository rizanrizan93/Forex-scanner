from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any

from .research_xau_h4_h1_m15_m5_portfolio_v233_aggregate import (
    _account_matrix,
    _dt,
    _load_v231_reversal,
    _rolling_three_year,
    _trade_metrics,
)

CONT_VERSION = "XAU_H4_VOLATILITY_CASCADE_M5_V236_1"
RESEARCH_VERSION = "XAU_H4_VOLATILITY_CASCADE_M5_PORTFOLIO_V236_1"
ARTIFACT_CONTRACT = "XAU_H4_VOLATILITY_CASCADE_M5_PORTFOLIO_V236_FULL_1"

MIN_TRAIN_TRADES = 80
MIN_TRAIN_PF = 1.05
MIN_POSITIVE_TRAIN_YEARS = 4


def _load(root: str) -> list[dict[str, Any]]:
    files = sorted(glob.glob(os.path.join(root, "**", "xau-h4-volatility-cascade-m5-v236-*.json"), recursive=True))
    if not files:
        raise RuntimeError("V236_SHARDS_MISSING")
    rows=[]; years=[]
    for path in files:
        payload=json.loads(Path(path).read_text())
        if payload.get("research_version") != CONT_VERSION:
            raise RuntimeError(f"V236_VERSION_MISMATCH:{path}")
        years.append(int(payload["year"]))
        for raw in payload.get("trades") or []:
            row=dict(raw)
            row["engine"]="V236_CASCADE"
            row["trade_key"]="|".join(("V236",str(row.get("variant_id")),str(row.get("direction")),str(row.get("fill_at"))))
            rows.append(row)
    if sorted(set(years)) != list(range(2012,2027)):
        raise RuntimeError(f"V236_YEAR_COVERAGE_INVALID:{sorted(set(years))}")
    return sorted(rows,key=lambda r:(_dt(r["fill_at"]),r["trade_key"]))


def _select(rows:list[dict[str,Any]]) -> tuple[str|None,dict[str,Any]]:
    evidence={}; eligible=[]
    for variant in sorted({str(r["variant_id"]) for r in rows}):
        train=[r for r in rows if r["variant_id"]==variant and 2012<=int(r["year"])<=2018]
        m=_trade_metrics(train,friction=0.5)
        passed=bool(
            m["orders"]>=MIN_TRAIN_TRADES
            and float(m.get("profit_factor") or 0)>=MIN_TRAIN_PF
            and m["net_points_fixed_0_01"]>0
            and m["positive_years"]>=MIN_POSITIVE_TRAIN_YEARS
        )
        evidence[variant]={"train_2012_2018":m,"selection_passed":passed}
        if passed:
            eligible.append((float(m["net_points_fixed_0_01"]),float(m.get("profit_factor") or 0),variant))
    eligible.sort(reverse=True)
    return (eligible[0][2] if eligible else None),evidence


def _period(rows,start,end):
    return _trade_metrics([r for r in rows if start<=int(r["year"])<=end],friction=0.5)


def aggregate(cont_root:str,v230_root:str)->dict[str,Any]:
    raw=_load(cont_root)
    reversal=_load_v231_reversal(v230_root)
    selected,selection=_select(raw)
    selected_rows=[r for r in raw if r["variant_id"]==selected] if selected else []
    portfolio=sorted(reversal+selected_rows,key=lambda r:(_dt(r["fill_at"]),r["trade_key"]))

    validation={}
    if selected:
        validation={
            "selected_variant":selected,
            "train_2012_2018":_period(selected_rows,2012,2018),
            "test_2019_2024":_period(selected_rows,2019,2024),
            "holdout_2025_2026":_period(selected_rows,2025,2026),
            "full_2012_2026":_trade_metrics(selected_rows,friction=0.5),
            "by_direction":{d:_trade_metrics([r for r in selected_rows if r["direction"]==d],friction=0.5) for d in ("LONG","SHORT")},
        }

    full=_account_matrix(portfolio)
    eras={}
    for name,start,end in (("train_2012_2018",2012,2018),("test_2019_2024",2019,2024),("holdout_2025_2026",2025,2026)):
        eras[name]=_account_matrix([r for r in portfolio if start<=int(r["year"])<=end])
    rolling=_rolling_three_year(portfolio,friction=0.5,margin_fraction=0.50)
    positive=sum(float(x["account"]["net_profit"])>0 for x in rolling)
    target10k=any(bool(cfg["target_10000_reached"]) for fr in full.values() for cfg in fr.values())
    primary=full["friction_0.5"]["margin_50pct"]
    decision="HOLD_RESEARCH_ONLY"
    if selected and eras["test_2019_2024"]["friction_0.5"]["margin_50pct"]["net_profit"]>0 and eras["holdout_2025_2026"]["friction_0.5"]["margin_50pct"]["net_profit"]>0 and positive>=10:
        decision="PROSPECTIVE_SHADOW_CANDIDATE"
    return {
        "artifact_contract":ARTIFACT_CONTRACT,
        "research_version":RESEARCH_VERSION,
        "objective":"$200_TO_$10000_WITH_H4_H1_M15_M5_CASCADE_PLUS_V231",
        "selection_contract":{"train":[2012,2018],"test":[2019,2024],"holdout":[2025,2026],"minimum_train_trades":MIN_TRAIN_TRADES,"minimum_train_pf":MIN_TRAIN_PF,"minimum_positive_train_years":MIN_POSITIVE_TRAIN_YEARS},
        "continuation_selection":selection,
        "continuation_validation":validation,
        "raw_continuation_orders":len(raw),
        "selected_continuation_orders":len(selected_rows),
        "reversal_orders":len(reversal),
        "portfolio_candidate_orders":len(portfolio),
        "portfolio_full_2012_2026":full,
        "portfolio_era_restart":eras,
        "rolling_3y_friction_0_5_margin_50pct":rolling,
        "rolling_3y_positive_windows":positive,
        "rolling_3y_window_count":len(rolling),
        "historical_target_10000_reached_any_sizing":target10k,
        "primary_friction_0_5_margin_50pct":primary,
        "decision":decision,
        "execution_influence":False,
        "execution_authority":False,
        "promotion_authority":False,
    }


def run()->int:
    result=aggregate(os.getenv("XAU_V236_DIR","/tmp/v236"),os.getenv("XAU_V236_V230_DIR","/tmp/v230"))
    output=Path(os.getenv("XAU_V236_FULL_OUTPUT","artifacts/xau-h4-volatility-cascade-m5-portfolio-v236-full.json"))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    p=result["primary_friction_0_5_margin_50pct"]
    print(f"XAU_V236_FULL selected={result['continuation_validation'].get('selected_variant')} final50={p['final_balance']:.2f} dd50={p['max_realized_drawdown']:.4f} target10k={result['historical_target_10000_reached_any_sizing']} decision={result['decision']}")
    return 0


if __name__=="__main__":
    raise SystemExit(run())
