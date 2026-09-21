from __future__ import annotations

from math import sqrt
from typing import Any, Sequence

from .models import Bar
from .research_xau_afic_displacement_origin_v154 import evaluate_v154
from .research_xau_afic_public_path_state_v155 import evaluate_v155

RESEARCH_VERSION="XAU_AFIC_PUBLIC_ROBUSTNESS_V158"
ARTIFACT_CONTRACT="XAU_AFIC_PUBLIC_ROBUSTNESS_V158_EVIDENCE_1"
POLICY_EFFECT="SHADOW_ONLY"
EXECUTION_INFLUENCE=False
PROMOTION_ELIGIBLE=False
PRIMARY_HORIZON="32"


def _wilson(rate:float|None,n:int,z:float=1.96):
    if rate is None or n<=0:
        return None
    p=float(rate);den=1.0+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return [max(0.0,center-half),min(1.0,center+half)]


def _extract_v154(d:dict[str,Any],scope:str)->dict[str,Any]:
    x=d["full"]["ORIGIN_REJECTION_H4_SWEEP_ROUND"] if scope=="FULL" else d["eras"][scope]["ORIGIN_REJECTION_H4_SWEEP_ROUND"]
    h=x["horizons"][PRIMARY_HORIZON]
    return {
        "model":"V154_H4_LOCATION_M15_SWEEP",
        "n":h["n"],
        "tp1_hit_rate":h["tp1_hit_rate"],
        "tp1_wilson95":_wilson(h["tp1_hit_rate"],h["n"]),
        "terminal_hit_rate":h["terminal_hit_rate"],
        "stop_rate":h["stop_rate"],
        "median_rr":h["median_terminal_rr"],
        "direction":h["direction"],
    }


def _extract_v155(d:dict[str,Any],scope:str,variant:str)->dict[str,Any]:
    x=d["full"][variant] if scope=="FULL" else d["eras"][scope][variant]
    h=x["horizons"][PRIMARY_HORIZON]
    return {
        "model":f"V155_{variant}",
        "n":h["n"],
        "tp1_hit_rate":h["tp1_hit_rate"],
        "tp1_wilson95":_wilson(h["tp1_hit_rate"],h["n"]),
        "stop_before_tp1_rate":h["stop_before_tp1_rate"],
        "median_rr":h["median_published_rr"],
        "runner_be_rate_after_tp1":h["runner_be_rate_after_tp1"],
        "runner_terminal_rate_after_tp1":h["runner_terminal_rate_after_tp1"],
        "direction":h["direction"],
    }


def evaluate_v158(rows:Sequence[Bar],*,evaluation_end)->dict[str,Any]:
    v154=evaluate_v154(rows,evaluation_end=evaluation_end)
    v155=evaluate_v155(rows,evaluation_end=evaluation_end)
    scopes=["FULL","2012_2018","2019_2024","2025_2026YTD"]
    out={}
    for scope in scopes:
        out[scope]={
            "v154":_extract_v154(v154,scope),
            "v155_public_short":_extract_v155(v155,scope,"PUBLIC_SHORT_M15_ENGULF"),
            "v155_mirror_bidir":_extract_v155(v155,scope,"MIRROR_BIDIR_M15_ENGULF"),
        }
    return {
        "research_version":RESEARCH_VERSION,
        "artifact_contract":ARTIFACT_CONTRACT,
        "policy_effect":POLICY_EFFECT,
        "execution_influence":EXECUTION_INFLUENCE,
        "promotion_eligible":PROMOTION_ELIGIBLE,
        "live_execution_enabled":False,
        "primary_horizon":"8h / 32 M15 bars",
        "scopes":out,
        "interpretation_contract":{
            "headline":"Do not infer ~85% AFIC accuracy from the 2025-26 sample unless cross-era evidence supports it.",
            "exact_public":"V155 SHORT bearish engulfing/rejection is public-source exact.",
            "mirrored_inference":"V155 LONG remains a symmetric research inference, not directly evidenced by the cited bearish public posts.",
            "statistics":"Wilson 95% interval is reported for TP1 hit rate to expose small-sample uncertainty.",
            "no_reselection":"No thresholds or variants are retuned in V158.",
        },
    }
