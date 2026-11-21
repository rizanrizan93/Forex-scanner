"""R7.3 optional CME pre-FOMC expectation/surprise contract.

A rate-change declaration is NOT by itself a hawkish/dovish surprise.
True surprise requires archived PRE-meeting futures-implied probability
distribution and an auditable original source receipt BEFORE statement
publication. No paid CME feed is connected, so true surprise never
enters the R7.3 historical factor panel and is never traded.
"""
from __future__ import annotations
from math import isfinite
from hashlib import sha256
import json
import pandas as pd

CONTRACT="RIZAN_R73_GATED_FEDWATCH_FOMC_SURPRISE_V1"


def _time(v):
    stamp=pd.Timestamp(v)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("TZ_AWARE_TIME_REQUIRED")
    return stamp.tz_convert("UTC")


def calculate_research_surprise(record,*,external_archive_evidence=None):
    out={
        "contract":CONTRACT,"status":"WAIT_CME_PREMEETING_ARCHIVE_NOT_VERIFIED",
        "conditional_formula_computed":False,
        "actual_FOMC_statement_and_decision_time_verified":False,
        "historical_fedwatch_original_receipt_verified":False,
        "eligible_as_pit_factor":False,
        "fomc_directional_claim":None,
        "execution_authority":False,
    }
    if not isinstance(record,dict):
        return out
    if record.get("expectation_provider")!="CME_FEDWATCH":
        out["status"]="WAIT_WRONG_OR_UNLICENSED_EXPECTATION_PROVIDER"
        return out
    try:
        release=_time(record["fomc_statement_published_at"])
        expected_at=_time(record["expectations_quote_observed_at"])
        received=_time(record["expectations_quote_received_at"])
        if not (expected_at<=received<release):
            out["status"]="WAIT_EXPECTATION_NOT_KNOWN_BEFORE_FOMC_RELEASE"
            return out
        if not isinstance(record["premeeting_probability_distribution"],list):
            return out
        dist=record["premeeting_probability_distribution"]
        if not 1<=len(dist)<=30:
            return out
        probabilities=[]
        rates=[]
        for item in dist:
            p=float(item["probability"])
            r=float(item["fed_target_midpoint_bps"])
            if not (isfinite(p) and 0<=p<=1 and isfinite(r)):
                return out
            probabilities.append(p);rates.append(r)
        if abs(sum(probabilities)-1.0)>1e-5:
            out["status"]="WAIT_INVALID_FEDWATCH_PROBABILITY_MASS"
            return out
        actual=float(record["actual_fomc_target_midpoint_bps"])
        if not isfinite(actual):
            return out
        expected=sum(p*r for p,r in zip(probabilities,rates))
        surprise=actual-expected
        # Signs: positive = more restrictive than probability-weighted
        # premeeting expectation; that is not a guaranteed gold sell.
        out.update({
            "conditional_formula_computed":True,
            "conditional_expected_midpoint_bps":round(expected,5),
            "conditional_actual_midpoint_bps":round(actual,5),
            "conditional_policy_surprise_bps":round(surprise,5),
            "conditional_policy_interpretation":(
                "MORE_RESTRICTIVE_THAN_EXPECTED" if surprise>0 else
                "LESS_RESTRICTIVE_THAN_EXPECTED" if surprise<0 else
                "IN_LINE_WITH_RATE_EXPECTATIONS"),
            "status":"FORMULA_COMPUTED_SOURCE_PROVENANCE_NOT_INDEPENDENTLY_AUDITED",
        })
    except (KeyError,ValueError,TypeError,OverflowError):
        out["status"]="WAIT_INVALID_FEDWATCH_SOURCE_SCHEMA"
    # Self-supplied document hashes / timestamps and a user-supplied
    # is_verified boolean do NOT constitute trusted original receipts.
    # External independent acquisition manifest verifier is not installed.
    return out
