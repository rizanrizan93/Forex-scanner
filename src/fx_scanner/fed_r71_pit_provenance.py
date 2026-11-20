"""R7.1 point-in-time provenance gate; no fabricated historical publication clocks.

ALFRED vintage dates are DATE-ONLY and differ from release TIMESTAMPS.
Treasury observations ~15:30 NY are market sampling timestamps, NOT
publication timestamps. ICE DXY is exchange-licensed; FRED's DTWEXBGS
must never be relabelled DXY.

The original-archival receipt must not be later than a historical
decision to claim truly captured PIT. Retrospective ALFRED reconstruction
can be daily vintage-consistent but cannot pass intraday receipt gate.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Mapping
import pandas as pd

CONTRACT="RIZAN_R71_POINT_IN_TIME_FACTOR_PROVENANCE_V1"
SOURCE_CLASSES={
    "ICE_DXY_INDEX", "ICE_DX_FUTURES", "TREASURY_NOMINAL",
    "TREASURY_REAL", "ALFRED_VINTAGE", "FRED_LATEST",
    "TRADE_WEIGHTED_BROAD_USD", "BROKER_DXY_PROXY",
}
EXACT_PROOF={"EXCHANGE_TIMESTAMP_WITH_ARCHIVE_RECEIPT",
             "ORIGINAL_RELEASE_TIMESTAMP_WITH_ARCHIVE_RECEIPT"}
RECONSTRUCTED={"ALFRED_VINTAGE_DATE_ONLY"}
R71_DATASETS={"RESEARCH_SENSITIVITY_PROXY","RECONSTRUCTED_DAILY_VINTAGE",
              "ORIGINAL_TIMESTAMP_VERIFIED"}


def _time(value, name):
    if isinstance(value,str):
        stamp=pd.Timestamp(value)
    else:
        stamp=pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("TZ_AWARE_"+name+"_REQUIRED")
    return stamp.tz_convert("UTC")


def verify_record(record:Mapping,*,decision_at,required_symbol=None):
    """Fail closed, with type-specific downgrade for date-only vintages."""
    now=_time(decision_at,"DECISION")
    out={
        "contract":CONTRACT,"status":"REJECT",
        "reason":"MISSING_OR_UNTRUSTED_PROVENANCE",
        "intraday_point_in_time_verified":False,
        "daily_vintage_consistent":False,
        "causal_model_input_permitted":False,
        "dxy_ice_verified":False,
        "decision_at":now.isoformat(),
        "execution_authority":False,
    }
    if not isinstance(record,Mapping) or record.get("source_class") not in SOURCE_CLASSES:
        return out
    r=dict(record)
    symbol=str(r.get("symbol") or "")
    if required_symbol is not None and symbol!=required_symbol:
        out["reason"]="SOURCE_SYMBOL_MISMATCH"
        return out
    # Only official index/future feeds carry the branded DXY claim.
    if symbol in ("DXY","USDX","DX"):
        if r["source_class"] not in ("ICE_DXY_INDEX","ICE_DX_FUTURES"):
            out["reason"]="NON_ICE_INDEX_MISLABELED_AS_DXY"
            return out
    try:
        observed=_time(r["observed_at"],"OBSERVATION")
        value=float(r["value"])
        if not (float("-inf")<value<float("inf")):
            out["reason"]="NONFINITE_FACTOR_VALUE"
            return out
        if observed>now:
            out["reason"]="FUTURE_OBSERVATION"
            return out
        method=r.get("proof_method")
        digest=str(r.get("source_sha256") or "")
        if len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            out["reason"]="SOURCE_CHECKSUM_REQUIRED"
            return out
        out["source_sha256"]=digest
        out["source_class"]=r["source_class"]
        out["symbol"]=symbol
        out["observed_at"]=observed.isoformat()
        if method in EXACT_PROOF:
            published=_time(r["published_at"],"PUBLICATION")
            captured=_time(r["original_captured_at"],"ORIGINAL_CAPTURE")
            if not observed<=published<=captured<=now:
                out["reason"]="PUBLICATION_OR_CAPTURE_AFTER_DECISION"
                return out
            # A release can be old, but its original archive must
            # truly have been captured before the historical decision.
            if r["source_class"] in ("FRED_LATEST","TRADE_WEIGHTED_BROAD_USD",
                                      "BROKER_DXY_PROXY"):
                out["reason"]="SOURCE_IS_ONLY_PROXY_NOT_ORIGINAL_PIT"
                return out
            out.update(
                status="PASS_ORIGINAL_RECEIPT",
                reason="ORIGINAL_RECORD_AND_RELEASE_OR_EXCHANGE_CLOCK_ASOF",
                intraday_point_in_time_verified=True,
                daily_vintage_consistent=True,
                causal_model_input_permitted=True,
                dxy_ice_verified=(symbol in ("DXY","USDX","DX")
                                 and r["source_class"] in ("ICE_DXY_INDEX","ICE_DX_FUTURES")),
                published_at=published.isoformat(),
                original_captured_at=captured.isoformat())
            return out
        if method in RECONSTRUCTED and r["source_class"]=="ALFRED_VINTAGE":
            vintage=pd.Timestamp(r["vintage_date"])
            if pd.isna(vintage) or vintage.tzinfo is not None:
                out["reason"]="VINTAGE_MUST_BE_ISO_DATE_WITHOUT_TIMEZONE"
                return out
            # Use only AFTER date-only vintage has fully ended in UTC.
            earliest=vintage.tz_localize("UTC")+pd.Timedelta(days=1)
            if earliest>now or observed>earliest:
                out["reason"]="VINTAGE_DATE_NOT_YET_SAFE"
                return out
            out.update(
                status="PASS_DAILY_VINTAGE_ONLY",
                reason="VINTAGE_DAY_RECONSTRUCTED_NOT_INTRADAY_PIT",
                daily_vintage_consistent=True,
                intraday_point_in_time_verified=False,
                causal_model_input_permitted=False,
                conservative_available_at=earliest.isoformat(),
            )
            return out
        out["reason"]="PROOF_METHOD_UNVERIFIED"
    except (KeyError,ValueError,TypeError,OverflowError):
        out["reason"]="INVALID_SOURCE_EVIDENCE_FIELDS"
    return out


def classify_dataset_provenance(records,*,decision_at):
    checks=[verify_record(r,decision_at=decision_at) for r in records]
    good=bool(checks) and all(
        x["intraday_point_in_time_verified"] for x in checks)
    date_only=bool(checks) and all(
        x["daily_vintage_consistent"] for x in checks)
    return {
        "contract":CONTRACT,
        "data_quality_state":("ORIGINAL_TIMESTAMP_VERIFIED" if good else
                              "RECONSTRUCTED_DAILY_VINTAGE" if date_only else
                              "RESEARCH_SENSITIVITY_PROXY"),
        "intraday_pit_verified":good,
        "n":len(checks),"passed_original":sum(
            x["intraday_point_in_time_verified"] for x in checks),
        "passed_daily_vintage":sum(x["daily_vintage_consistent"] for x in checks),
        "records":checks,
        "execution_authority":False,
    }
