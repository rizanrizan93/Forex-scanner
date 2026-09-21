from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any, Mapping, Sequence

from .demo_donchian_adaptive_tournament import TournamentTrade, compute_metrics
from .models import Bar, ensure_utc
from .research_xau_liquidity_cartography_v144 import (
    Setup,
    _make_trade,
    extract_lcr_setups,
)

RESEARCH_VERSION="XAU_LIQUIDITY_CARTOGRAPHY_FORENSIC_V145"
ARTIFACT_CONTRACT="XAU_LIQUIDITY_CARTOGRAPHY_FORENSIC_V145_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False

ERAS=(
    ("2012_2018",datetime(2012,1,1,tzinfo=timezone.utc),datetime(2019,1,1,tzinfo=timezone.utc)),
    ("2019_2024",datetime(2019,1,1,tzinfo=timezone.utc),datetime(2025,1,1,tzinfo=timezone.utc)),
    ("2025_2026YTD",datetime(2025,1,1,tzinfo=timezone.utc),datetime(2026,9,20,tzinfo=timezone.utc)),
)


def _metrics(rows):
    return compute_metrics(tuple(r["trade"] for r in rows)).payload()


def _stats(rows):
    if not rows:
        return {"n":0}
    risk_atr=[abs(float(r["trade"].entry_price)-float(r["trade"].stop_loss))/float(r["setup"].atr) for r in rows if float(r["setup"].atr)>0]
    target_r=[abs(float(r["trade"].take_profit)-float(r["trade"].entry_price))/abs(float(r["trade"].entry_price)-float(r["trade"].stop_loss)) for r in rows if abs(float(r["trade"].entry_price)-float(r["trade"].stop_loss))>0]
    gravity=[abs(float(r["setup"].gravity)) for r in rows]
    return {
        "n":len(rows),
        "metrics":_metrics(rows),
        "median_abs_gravity":float(median(gravity)) if gravity else None,
        "median_risk_atr":float(median(risk_atr)) if risk_atr else None,
        "median_target_r":float(median(target_r)) if target_r else None,
    }


def _period(rows,start,end):
    a,b=ensure_utc(start),ensure_utc(end)
    return tuple(r for r in rows if a<=ensure_utc(r["trade"].entry_at)<b)


def evaluate_v145(rows:Sequence[Bar],*,evaluation_end,pip_size,costs):
    bars=tuple(sorted(rows,key=lambda x:ensure_utc(x.timestamp)))
    end=ensure_utc(evaluation_end)
    setups=extract_lcr_setups(bars)
    paired=[]
    for s in setups:
        t=_make_trade(bars,s,costs=costs,pip_size=pip_size)
        if t is not None and ensure_utc(t.entry_at)<end:
            paired.append({"setup":s,"trade":t})

    full=tuple(paired)
    by_family={}
    for family in sorted({r["setup"].family for r in full}):
        vals=tuple(r for r in full if r["setup"].family==family)
        by_family[family]=_stats(vals)

    by_pool={}
    for kind in sorted({r["setup"].pool_kind for r in full}):
        vals=tuple(r for r in full if r["setup"].pool_kind==kind)
        by_pool[kind]=_stats(vals)

    family_x_pool={}
    for family in sorted({r["setup"].family for r in full}):
        for kind in sorted({r["setup"].pool_kind for r in full}):
            vals=tuple(r for r in full if r["setup"].family==family and r["setup"].pool_kind==kind)
            if vals:
                family_x_pool[f"{family}|{kind}"]=_stats(vals)

    era={}
    for label,a,b in ERAS:
        vals=_period(full,a,min(b,end))
        family={}
        for fam in sorted({r["setup"].family for r in vals}):
            family[fam]=_stats(tuple(r for r in vals if r["setup"].family==fam))
        pools={}
        for kind in sorted({r["setup"].pool_kind for r in vals}):
            pools[kind]=_stats(tuple(r for r in vals if r["setup"].pool_kind==kind))
        crosses={}
        for fam in sorted({r["setup"].family for r in vals}):
            for kind in sorted({r["setup"].pool_kind for r in vals}):
                z=tuple(r for r in vals if r["setup"].family==fam and r["setup"].pool_kind==kind)
                if z:
                    crosses[f"{fam}|{kind}"]=_stats(z)
        era[label]={"all":_stats(vals),"family":family,"pool":pools,"family_x_pool":crosses}

    outcome={}
    for label,pred in (
        ("WIN",lambda r:float(r["trade"].net_r)>0),
        ("LOSS",lambda r:float(r["trade"].net_r)<0),
        ("BREAKEVEN",lambda r:float(r["trade"].net_r)==0),
    ):
        vals=tuple(r for r in full if pred(r))
        outcome[label]=_stats(vals)

    direction={}
    for side in ("LONG","SHORT"):
        direction[side]=_stats(tuple(r for r in full if r["trade"].direction==side))

    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "contract":{
            "source_strategy":"exact V144 frozen rules",
            "rule_changes":False,
            "threshold_search":False,
            "selection":False,
            "purpose":"diagnose which mapped liquidity mechanisms explain V144 era instability",
            "diagnostics":["family","pool_kind","family_x_pool","era","direction","winner_vs_loser geometry"],
            "execution_authority":False,
        },
        "all":_stats(full),
        "by_family":by_family,
        "by_pool":by_pool,
        "family_x_pool":family_x_pool,
        "era":era,
        "direction":direction,
        "outcome_geometry":outcome,
        "note":"V145 is descriptive forensic evidence only. No bucket is eligible for direct promotion.",
    }
