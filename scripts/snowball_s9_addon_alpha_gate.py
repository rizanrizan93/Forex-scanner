"""RIZAN Snowball S9: native add-on archive audit + fail-closed basket scheduler.
Read-only. CORE priority at same UTC timestamp, exit before entry.
WARNING: fixed-PnL basket CSV cannot prove rerun compounding, floating DD or broker fills.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"research/RIZAN_ADDON_ALPHA_S9_NATIVE_ARCHIVE_EVIDENCE.json"
OUT=ROOT/"artifacts/snowball_s9"
OUT.mkdir(parents=True,exist_ok=True)
RISK_PCT=Decimal("0.2075")
MARGIN_PCT=Decimal("0.50")

def archive_audit():
    d=json.loads(EVIDENCE.read_text())
    assert d["research_only"] and not d["execution_authority"]
    assert d["unique_configurations_with_all_four_screen_years"]==len(d["policies"])==20
    assert set(d["baseline_years"])=={"2020","2021","2025","2026"}
    assert len(d["diagnostic_examples"])==3
    assert d["source_archive_sha256"]=="eef9a831b50776d362e4ba4e2dda28fac20a84b20b5785b58a27fa17d7745318"
    p=d["policies"]
    assert len({x["name"] for x in p})==20
    assert all(0<=x["years_balance_improved"]<=4 and
         0<=x["years_baskets_increased"]<=4 and 0<x["max_dd_pct"]<100 for x in p)
    return {
      "study":"RIZAN_ADDON_ALPHA_S9_OLD_NATIVE_CASES",
      "status":"NO_ARCHIVED_POLICY_QUALIFIED_FOR_PROMOTION",
      "replay_cases_in_original_archive":d["original_native_cases_in_archive"],
      "policies_with_four_annual_comparisons":len(p),
      "policies_more_baskets_all_four_years":sum(x["years_baskets_increased"]==4 for x in p),
      "policies_higher_balance_all_four_years":sum(x["years_balance_improved"]==4 for x in p),
      "policies_higher_balance_three_of_four_years":sum(x["years_balance_improved"]==3 for x in p),
      "policies_max_equity_dd_above60pct":sum(x["max_dd_pct"]>60 for x in p),
      "source_archive_sha256":d["source_archive_sha256"],
      "research_only":True,
      "native_full_2019_2026_account_parity":False,
      "validated_incremental_profitable_addon":False,
      "notes":["Archive originally replayed native addon portfolio on four annual $100 resets under synthetic M1 B cost1.",
               "Every additional basket is NOT necessarily a profitable basket. No per-addon trade entry/exit ledger in this compact manifest.",
               "Results cannot be compounded into the Frozen V1 continuous $1.662B baseline.",
               "Original 2024/A 2x cost control can fail. No candidate is live-ready."],
    }

def date_utc(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("UTC offset required")
    return d.astimezone(timezone.utc)

def rows(path,category):
    required={"trade_id","symbol","entry_utc","exit_utc","planned_risk_usd","margin_usd","net_pnl_usd"}
    with Path(path).open(newline="") as f:
        r=csv.DictReader(f)
        if not r.fieldnames or not required.issubset(r.fieldnames):
            raise ValueError(f"Missing trade-ledger columns {category}: {required-set(r.fieldnames or [])}")
        data=[]
        for a in r:
            trade={"id":a["trade_id"],"symbol":a["symbol"],
                   "entry":date_utc(a["entry_utc"]),"exit":date_utc(a["exit_utc"]),
                   "risk":Decimal(a["planned_risk_usd"]),
                   "margin":Decimal(a["margin_usd"]),
                   "pnl":Decimal(a["net_pnl_usd"]),"type":category}
            assert trade["id"] and trade["symbol"]
            if trade["exit"]<=trade["entry"]:raise ValueError("Exit before entry")
            if trade["risk"]<=0 or trade["margin"]<=0:raise ValueError("Nonpositive exposure")
            if not all(v.is_finite() for v in [trade["risk"],trade["margin"],trade["pnl"]]):
                raise ValueError("Nonfinite risk/margin/PnL")
            data.append(trade)
        if len({x["id"] for x in data})!=len(data):raise ValueError("Duplicate trade ID")
        return data

def diagnostic(core,addon,starting_cash=Decimal("100"),
               min_addon_equity=Decimal("125")):
    """Causal order-budget admission of FIXED trade returns; no repricing or core rerun.

    At a later core entry, any addon-induced exposure conflict is flagged as a
    failed hypothesis, not retroactively skipped with hindsight.
    """
    if not core:raise ValueError("CORE ledger is required; no invented baseline")
    if any(x["type"]!="CORE" for x in core) or any(x["type"]!="ADDON" for x in addon):
        raise ValueError("Invalid source category")
    if {x["id"] for x in core}&{x["id"] for x in addon}:
        raise ValueError("Duplicate IDs between CORE and ADDON")
    events=[]
    for t in core+addon:
        events.extend([(t["entry"],1 if t["type"]=="CORE" else 2,t),
                       (t["exit"],0,t)])
    events.sort(key=lambda x:(x[0],x[1],x[2]["id"]))
    cash=Decimal(starting_cash)
    peak=cash
    settled_dd=Decimal("0")
    open_trades={}
    accepted_addons=set()
    rejected={"before_growth":0,"risk_cap":0,"margin_cap":0}
    core_conflicts=0
    baseline_budget_violation=0
    addon_pnl=Decimal("0")
    addon_win=0
    addon_loss=0
    accepted_count=0
    for _,action,trade in events:
        ttype=trade["type"]
        if action==0:
            if ttype=="ADDON" and trade["id"] not in accepted_addons:continue
            if trade["id"] not in open_trades:
                raise ValueError("Unexpected settlement without matching fill")
            del open_trades[trade["id"]]
            cash+=trade["pnl"]
            if ttype=="ADDON":
                addon_pnl+=trade["pnl"]
                addon_win+=int(trade["pnl"]>0)
                addon_loss+=int(trade["pnl"]<0)
            peak=max(peak,cash)
            if peak>0:settled_dd=max(settled_dd,Decimal("100")*(peak-cash)/peak)
            continue
        if cash<=0:
            raise ValueError("Account cannot admit any trade with zero/negative balance")
        risk=sum(x["risk"] for x in open_trades.values())+trade["risk"]
        margin=sum(x["margin"] for x in open_trades.values())+trade["margin"]
        if ttype=="CORE":
            if risk>RISK_PCT*cash or margin>MARGIN_PCT*cash:
                if any(t["type"]=="ADDON" for t in open_trades.values()):
                    core_conflicts+=1
                else:baseline_budget_violation+=1
            open_trades[trade["id"]]=trade
            continue
        if cash<min_addon_equity:
            rejected["before_growth"]+=1
            continue
        if risk>RISK_PCT*cash:
            rejected["risk_cap"]+=1
            continue
        if margin>MARGIN_PCT*cash:
            rejected["margin_cap"]+=1
            continue
        open_trades[trade["id"]]=trade
        accepted_addons.add(trade["id"])
        accepted_count+=1
    if open_trades:raise ValueError("Unclosed trades")
    return {
      "status":"FIXED_PNL_OVERLAY_DIAGNOSTIC_ONLY",
      "starting_cash_usd":str(starting_cash),
      "settled_balance_usd":str(cash),
      "settled_max_dd_pct_not_floating":str(round(settled_dd,4)),
      "addon_offered":len(addon),
      "addon_accepted":accepted_count,
      "addon_winners":addon_win,
      "addon_losers":addon_loss,
      "addon_realized_net_pnl_usd":str(addon_pnl),
      "addon_rejected":rejected,
      "core_entry_conflicts":core_conflicts,
      "baseline_budget_violations":baseline_budget_violation,
      "eligible_for_native_replay_followup":bool(addon_pnl>0 and
                    accepted_count>=1 and core_conflicts==0 and
                    baseline_budget_violation==0 and settled_dd<=Decimal("60")),
      "passed_native_frozen_v1_parity":False,
      "native_terminal_balance_improvement_verified":False,
      "reason":"All PnL amounts are externally supplied FIXED trade outcomes. Sizing, fill-time and future core reactions are NOT rerun.",
    }

def fixture_trade(tid,kind,start,end,risk,margin,pnl):
    return {"id":tid,"symbol":"XAUUSD","type":kind,
        "entry":date_utc(start),"exit":date_utc(end),
        "risk":Decimal(str(risk)),"margin":Decimal(str(margin)),
        "pnl":Decimal(str(pnl))}

def selftest():
    # A core win first lifts balance above $125; add-on only after graduation.
    core=[
      fixture_trade("C1","CORE","2025-01-01T08:00:00Z","2025-01-01T09:00:00Z",10,20,60),
      fixture_trade("C2","CORE","2025-01-01T11:00:00Z","2025-01-01T12:00:00Z",10,20,12),
    ]
    add=[
      fixture_trade("A0","ADDON","2025-01-01T08:30:00Z","2025-01-01T08:45:00Z",1,5,2),
      fixture_trade("A1","ADDON","2025-01-01T09:15:00Z","2025-01-01T10:00:00Z",10,20,8),
    ]
    result=diagnostic(core,add)
    assert result["addon_offered"]==2
    assert result["addon_accepted"]==1
    assert result["addon_rejected"]["before_growth"]==1
    assert result["addon_winners"]==1
    assert result["core_entry_conflicts"]==0
    assert result["settled_balance_usd"]=="180"
    # No opportunistic hindsight: a later core that would exceed margin cap
    # remains scheduled, and the addon strategy is flagged as conflicting.
    conflict=fixture_trade("A2","ADDON","2025-01-01T10:50:00Z",
        "2025-01-01T11:30:00Z",20,65,15)
    fail=diagnostic(core,[conflict])
    assert fail["core_entry_conflicts"]==1
    assert not fail["eligible_for_native_replay_followup"]
    # Core-before-addon on a matching timestamp must never let addon displace core.
    tie=fixture_trade("A3","ADDON","2025-01-01T11:00:00Z",
        "2025-01-01T11:30:00Z",30,80,20)
    blocked=diagnostic(core,[tie])
    assert blocked["addon_accepted"]==0
    assert blocked["core_entry_conflicts"]==0
    evidence=archive_audit()
    assert evidence["policies_higher_balance_all_four_years"]==0
    assert evidence["policies_more_baskets_all_four_years"]==8
    assert evidence["policies_higher_balance_three_of_four_years"]==1
    assert evidence["policies_max_equity_dd_above60pct"]==15
    print("S9_SELFTEST_PASS",json.dumps({
      "fixed_PNL_compounding_is_NOT_native":True,
      "core_entry_prioritized":True,
      "future_core_conflict_fails":True,
      "archive_20_policies_zero_robust":True},sort_keys=True),flush=True)

def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--selftest",action="store_true")
    cli.add_argument("--archive-audit",action="store_true")
    cli.add_argument("--core-ledger")
    cli.add_argument("--addon-ledger")
    cli.add_argument("--output",default="artifacts/snowball_s9/overlay_diagnostic.json")
    a=cli.parse_args()
    if a.selftest:selftest()
    elif a.archive_audit:
        z=archive_audit()
        p=OUT/"s9_archive_audit.json"
        p.write_text(json.dumps(z,indent=2)+"\n")
        print("S9_ARCHIVE_AUDIT",json.dumps(z,sort_keys=True),flush=True)
    elif a.core_ledger and a.addon_ledger:
        c=rows(a.core_ledger,"CORE");ad=rows(a.addon_ledger,"ADDON")
        z=diagnostic(c,ad)
        out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(z,indent=2)+"\n")
        print("S9_OVERLAY_DIAGNOSTIC",json.dumps(z,sort_keys=True),flush=True)
    else:cli.error("Supply --archive-audit, --selftest or BOTH --core-ledger and --addon-ledger")

if __name__=="__main__":main()
