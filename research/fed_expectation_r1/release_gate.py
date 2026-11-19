"""Read-only Fed Macro R1 evidence gate.

This module NEVER deploys anything. It only reports whether a manually
reviewed dashboard experiment could *qualify* for later production review.
"""
from math import sqrt, isfinite

MIN_INDEPENDENT_N=100
REQUIRED_YEARS=3
MIN_WILSON_LOWER=0.60
EXECUTION_AUTHORITY=False

def wilson_lower(wins,n,z=1.96):
    if not isinstance(wins,int) or not isinstance(n,int) or n<0 or wins<0 or wins>n:
        raise ValueError("INVALID_COUNT")
    if n==0:return None
    p=wins/n; den=1+z*z/n
    return (p+z*z/(2*n)-z*sqrt(p*(1-p)/n+z*z/(4*n*n)))/den

def evaluate(manifest):
    """Pure evidence evaluation; 'pass' is NOT a deployment action."""
    required={"paired_real_xau_events","futures_same_contract_pit",
        "intraday_cash_us2y_pit","usd_proxy_pit","source_hashes_valid",
        "utc_release_windows_verified","real_quote_age_and_spread_valid",
        "commission_slippage_included","genuine_prospective_holdout",
        "buy","sell","years"}
    if not required.issubset(manifest):
        raise ValueError("MISSING_REQUIRED_EVIDENCE_FIELDS")
    failures=[]
    for key in sorted(required-{"buy","sell","years"}):
        if manifest[key] is not True:
            failures.append("MISSING_OR_FAILED_"+key.upper())
    if not isinstance(manifest["years"],list) or len(set(manifest["years"]))<REQUIRED_YEARS:
        failures.append("INSUFFICIENT_INDEPENDENT_YEARS")
    by_side={}
    for side in ("buy","sell"):
        d=manifest[side]
        if not {"n","wins","nonoverlapping","net_expectancy_usd"}.issubset(d):
            raise ValueError("INCOMPLETE_"+side.upper())
        n,w=d["n"],d["wins"]
        low=wilson_lower(w,n)
        if n<MIN_INDEPENDENT_N:
            failures.append("INSUFFICIENT_"+side.upper()+"_N")
        if not d["nonoverlapping"]:
            failures.append("OVERLAPPING_"+side.upper()+"_EVENTS")
        if low is None or low<MIN_WILSON_LOWER:
            failures.append(side.upper()+"_WILSON_LOWER_BELOW_60")
        x=d["net_expectancy_usd"]
        if not isinstance(x,(float,int)) or not isfinite(float(x)) or x<=0:
            failures.append("NONPOSITIVE_"+side.upper()+"_NET_EXPECTANCY")
        by_side[side]={"n":n,"wins":w,
                       "hit_rate_pct":round(100*w/n,2) if n else None,
                       "wilson95_lower_pct":round(100*low,2) if low is not None else None}
    return {
        "contract":"FED_MACRO_R1_RELEASE_EVIDENCE_GATE_V1",
        "read_only_production_review_eligible":len(failures)==0,
        "failed_gates":failures,
        "by_side":by_side,
        "authority_to_deploy":False,
        "authority_to_send_orders":False,
        "review_note":"PASS would only permit a separate human-reviewed read-only scanner change",
    }
