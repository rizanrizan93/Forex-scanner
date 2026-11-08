"""Merge read-only BUY050 sampled checkpoint transitions and broker evidence.

Input from the current GitHub Actions run is ephemeral/private. Output is a
small redacted public display DTO. A broker OPEN position is positive evidence;
absence of one cannot prove that an order failed or never happened.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC=timezone.utc
CONTRACT="RIZAN_BUY050_EVENT_TIMELINE_V1"
AUDIT="RIZAN_BUY050_EVENT_AUDIT_V1"
BROKER="RIZAN_BUY050_BROKER_OPEN_V1"
PROFILE="13bfa137f962e6d3cf4dd601edfedb15b432653063fa86ec52adadeb4d8ffdf6"
SYMBOLS=("XAUUSD","EURUSD","BTCUSD")
KINDS={
    "SIGNAL_RECORDED", "SIGNAL_CHANGED_DURING_GAP", "INTENT_PREPARED",
    "BASKET_STATE_ACTIVE", "QUARANTINE_ON", "FAULT_ON",
    "EXIT_PENDING_ON", "CHECKPOINT_RESET", "BROKER_OPEN_POSITION_OBSERVED"
}
ORIGINS={"INCUMBENT","XAU_H1_DISPLACEMENT","BTC_H4_BREAK40_ALL"}

def parse(value):
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else None
    except (ValueError,TypeError,OverflowError):
        return None

def eid(symbol,kind,at,signal_at=None):
    return hashlib.sha256("|".join((symbol,kind,at,signal_at or "")).encode("ascii")).hexdigest()[:24]

def event(s,kind,at,signal_at=None,origin=None,version=None,evidence=None,protection=None):
    return {
        "id":eid(s,kind,at,signal_at),
        "symbol":s, "event":kind, "observed_at":at,
        "signal_at":signal_at, "origin":origin if origin in ORIGINS else None,
        "checkpoint_version":version if type(version) is int and version>=0 else None,
        "evidence":evidence if evidence in {"NATIVE_CHECKPOINT_TRANSITION","INFERRED_BETWEEN_POLL_WINDOWS","BROKER_RECONCILE_OPEN_POSITION"} else None,
        "protection":protection if protection in {"SL_TP_PRESENT","PROTECTION_INCOMPLETE"} else None
    }

def sanitize_event(e):
    if not isinstance(e,dict) or e.get("symbol") not in SYMBOLS or e.get("event") not in KINDS:
        raise ValueError("EVENT_TYPE_OR_SYMBOL_INVALID")
    at=parse(e.get("observed_at"))
    signal=parse(e.get("signal_at"))
    if not at or at.year<2026:
        raise ValueError("EVENT_TIME_INVALID")
    clean=event(e["symbol"],e["event"],at.isoformat(),signal.isoformat() if signal else None,
                e.get("origin"),e.get("checkpoint_version"),e.get("evidence"),e.get("protection"))
    if e.get("id") and e["id"]!=clean["id"]:
        # Canonical ID may differ only when upstream used UTC +00:00 vs Z.
        # Recompute and do not pass through untrusted upstream identifiers.
        pass
    return clean

def subset_state(raw):
    if not isinstance(raw,dict) or set(raw)!=set(SYMBOLS):
        raise ValueError("STATE_SET_INVALID")
    result={}
    for symbol in SYMBOLS:
        row=raw[symbol]
        if not isinstance(row,dict):
            raise ValueError("STATE_INVALID")
        sig=parse(row.get("signal"))
        result[symbol]={"version":row.get("version") if type(row.get("version")) is int and row["version"]>=0 else None,
                        "signal":sig.isoformat() if sig else None}
    return result

def merge(current,broker=None,previous=None,now=None):
    now=now or datetime.now(UTC)
    if (not isinstance(current,dict) or current.get("contract")!=AUDIT
        or current.get("strategy")!="P3_BUY050"
        or current.get("profile_sha256")!=PROFILE
        or current.get("read_only") is not True
        or current.get("execution_authority") is not False
        or current.get("execution_influence") is not False
        or current.get("source")!="VPS_SQLITE_READONLY_1S_SAMPLING"):
        raise ValueError("INVALID_NATIVE_AUDIT")
    start,end=parse(current.get("started_at")),parse(current.get("ended_at"))
    if not start or not end or not start<=end<=now+timedelta(seconds=30) or (end-start)>timedelta(minutes=5):
        raise ValueError("OBSERVATION_CLOCK_INVALID")
    if (type(current.get("samples")) is not int or current["samples"]<2
        or type(current.get("failures")) is not int or current["failures"]<0
        or current.get("terminal_journal_available") is not False
        or current.get("broker_deals_verified") is not False):
        raise ValueError("AUDIT_COMPLETENESS_INVALID")
    first=subset_state(current.get("start_state"))
    last=subset_state(current.get("end_state"))
    recent=current.get("events")
    if not isinstance(recent,list) or len(recent)>240:
        raise ValueError("AUDIT_EVENTS_TOO_MANY")
    events=[sanitize_event(x) for x in recent]

    old_ok=(isinstance(previous,dict) and previous.get("contract")==CONTRACT
            and previous.get("strategy")=="P3_BUY050"
            and previous.get("profile_sha256")==PROFILE
            and previous.get("read_only") is True
            and previous.get("execution_authority") is False
            and previous.get("execution_influence") is False)
    prior_end=parse(previous.get("ended_at")) if old_ok else None
    gap_s=None
    if old_ok and prior_end and prior_end<=start:
        gap_s=round((start-prior_end).total_seconds(),2)
        prev_end=subset_state(previous.get("end_state"))
        if gap_s>1:
            for symbol in SYMBOLS:
                old,new=prev_end[symbol],first[symbol]
                if old["signal"]!=new["signal"] and new["signal"]:
                    events.append(event(symbol,"SIGNAL_CHANGED_DURING_GAP",start.isoformat(),
                        new["signal"],None,new["version"],"INFERRED_BETWEEN_POLL_WINDOWS"))
    if old_ok:
        for x in previous.get("events",[]):
            try: events.append(sanitize_event(x))
            except (ValueError,TypeError): continue

    broker_as_of=None
    broker_ok=False
    broker_rows=[]
    if broker is not None:
        if (not isinstance(broker,dict) or broker.get("contract")!=BROKER
            or broker.get("read_only") is not True or broker.get("execution_authority") is not False
            or broker.get("deals_history_checked") is not False):
            raise ValueError("BROKER_EVIDENCE_CONTRACT_INVALID")
        broker_as_of=parse(broker.get("observed_at"))
        if not broker_as_of or abs((broker_as_of-end).total_seconds())>180:
            raise ValueError("BROKER_EVIDENCE_STALE")
        evidence=broker.get("open_position_evidence")
        if not isinstance(evidence,list) or len(evidence)>120:
            raise ValueError("BROKER_ROWS_INVALID")
        for row in evidence:
            if not isinstance(row,dict) or row.get("symbol") not in SYMBOLS:
                raise ValueError("BROKER_SYMBOL_INVALID")
            sig=parse(row.get("signal_at"))
            if not sig or sig>broker_as_of or sig<broker_as_of-timedelta(days=30):
                raise ValueError("BROKER_SIGNAL_TIMESTAMP_INVALID")
            if type(row.get("open_positions")) is not int or not 1<=row["open_positions"]<=2000:
                raise ValueError("BROKER_POSITION_COUNT_INVALID")
            protect=("SL_TP_PRESENT" if row.get("sl_protected") is True and row.get("tp_protected") is True
                     else "PROTECTION_INCOMPLETE")
            broker_rows.append({"symbol":row["symbol"],"signal_at":sig.isoformat(),"protection":protect})
            events.append(event(row["symbol"],"BROKER_OPEN_POSITION_OBSERVED",
                sig.isoformat(),sig.isoformat(),evidence="BROKER_RECONCILE_OPEN_POSITION",
                protection=protect))
        broker_ok=True
    # Keep only recent sanitized records. Never publish raw checkpoints or
    # account bindings; all output fields are allowlisted and safe to display.
    retained={}
    for row in events:
        t=parse(row["observed_at"])
        if t and now-t<=timedelta(hours=48) and t<=now+timedelta(seconds=30):
            retained[row["id"]]=row
    ordered=sorted(retained.values(),key=lambda r:(r["observed_at"],r["symbol"]))[-120:]
    return {
        "contract":CONTRACT,"strategy":"P3_BUY050","profile_sha256":PROFILE,
        "read_only":True,"execution_authority":False,"execution_influence":False,
        "started_at":start.isoformat(),"ended_at":end.isoformat(),
        "samples":current["samples"],"failures":current["failures"],
        "max_interval_s":current.get("max_interval_s"),
        "unobserved_gap_s":gap_s,
        "continuous_coverage_confirmed":gap_s is not None and gap_s<=2 and current["failures"]==0
            and (current.get("max_interval_s") or 999)<=2,
        "terminal_journal_available":False,"broker_deals_verified":False,
        "broker_open_positions_observed":broker_ok,
        "broker_observed_at":broker_as_of.isoformat() if broker_as_of else None,
        "end_state":last,"events":ordered
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--current",required=True)
    p.add_argument("--broker")
    p.add_argument("--previous")
    p.add_argument("--output",required=True)
    a=p.parse_args()
    def load(path):
        return json.loads(Path(path).read_text()) if path and Path(path).exists() else None
    result=merge(load(a.current),load(a.broker),load(a.previous))
    Path(a.output).write_text(json.dumps(result,allow_nan=False,separators=(",",":")))
    print("BUY050_REDACTED_EVENT_TIMELINE",len(result["events"]),
          "samples",result["samples"],"gap_seconds",result["unobserved_gap_s"])

if __name__=="__main__":
    main()
