"""S10: read-only, causal add-on loss-streak guard and historical native-case diagnostics.
NOT a new trade backtest. Hindsight year labels cannot be used to gate a live entry.
"""
from __future__ import annotations
import json
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import argparse
import snowball_s9_addon_alpha_gate as s9

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"research/RIZAN_S10_NATIVE_ADDON_FOUR_YEAR_DEEP_AUDIT.json"
OUTPUT=ROOT/"artifacts/snowball_s10"
OUTPUT.mkdir(parents=True,exist_ok=True)

def historical():
    src=json.loads(SOURCE.read_text())
    assert src["source_all_cases_sha256"]=="73001ce51805ce22200419e90020c78fabd8242d61d90e3c39c98ac2bd939572"
    assert src["baseline_reset_years"]==[2020,2021,2025,2026]
    rows=src["policies"]
    assert len(rows)==20 and len({x["name"] for x in rows})==20
    for x in rows:
        assert len(x["terminal_ratio_by_reset"])==len(x["additional_baskets_by_reset"])==4
        assert all(v>0 for v in x["terminal_ratio_by_reset"])
        assert 0<x["max_equity_dd_pct"]<100
    no_2021=sum(r["terminal_ratio_by_reset"][1]<1 for r in rows)
    extra_2021=sum(r["additional_baskets_by_reset"][1]>0 for r in rows)
    all_extras=sum(all(n>0 for n in r["additional_baskets_by_reset"]) for r in rows)
    worsen_even_with_more=sum(r["terminal_ratio_by_reset"][1]<1 and
        r["additional_baskets_by_reset"][1]>0 for r in rows)
    all_balance=sum(all(v>1 for v in r["terminal_ratio_by_reset"]) for r in rows)
    assert no_2021==20 and extra_2021>=10 and all_balance==0
    from statistics import median
    result={"study":"S10_NATIVE_PREVIOUS_ADDON_2021_FRAGILITY_AUDIT",
       "source_n_annual_cases":87,"policies":len(rows),
       "years":[2020,2021,2025,2026],
       "all_2021_underperformed_core":no_2021,
       "2021_more_baskets_than_core":extra_2021,
       "2021_more_baskets_but_worse_balance":worsen_even_with_more,
       "more_baskets_all_four_years":all_extras,
       "higher_balance_all_four_years":all_balance,
       "median_2021_end_balance_ratio":median(r["terminal_ratio_by_reset"][1] for r in rows),
       "risk_flag":"Every historically selected add-on suffered worse ending balance in 2021; cannot be patched with calendar-year knowledge.",
       "native_current_replay_results_available":False,
       "trade_level_entry_exit_pnl_available":False,
       "eligible_for_deployment":False}
    return result

def run_online_guard(core,add,initial_cash=Decimal("100"),
    min_cash=Decimal("125"),max_addon_risk_pct=Decimal("0.03"),
    reserve_unallocated_risk_pct=Decimal("0.04"),
    reserve_unallocated_margin_pct=Decimal("0.10"),
    losses_to_pause=2,pause_days=30):
    """No future knowledge; settlement and core entry precede add-on on ties.

    Core conflicts after an accepted add-on are *failed validation*, not quietly
    avoided using future trade data. Fixed-PnL only; never infer terminal alpha.
    """
    if not core or any(t["type"]!="CORE" for t in core):
        raise ValueError("Real core ledger required")
    if any(t["type"]!="ADDON" for t in add):
        raise ValueError("Invalid add-on ledger")
    if losses_to_pause<1 or pause_days<1:raise ValueError("invalid pause controls")
    if set(t["id"] for t in core)&set(t["id"] for t in add):
        raise ValueError("duplicate trade IDs")
    events=[]
    for trade in core+add:
        events.extend([(trade["entry"],1 if trade["type"]=="CORE" else 2,trade),
                       (trade["exit"],0,trade)])
    events.sort(key=lambda v:(v[0],v[1],v[2]["id"]))
    cash=Decimal(initial_cash)
    peak=cash
    current={}
    accepted=set()
    blocked=defaultdict(int)
    events_log=[]
    max_dd=Decimal(0)
    core_conflicts=0
    native_core_would_violate=0
    sequential_addon_losses=0
    pause_until=None
    add_nets=Decimal(0)
    add_wins=0
    add_losses=0
    for now,action,t in events:
        tid=t["id"]
        if action==0:
            if t["type"]=="ADDON" and tid not in accepted:continue
            if tid not in current:raise ValueError(f"invalid exit {tid}")
            del current[tid]
            cash+=t["pnl"]
            peak=max(cash,peak)
            if peak>0:max_dd=max(max_dd,Decimal("100")*(peak-cash)/peak)
            if t["type"]=="ADDON":
                add_nets+=t["pnl"]
                if t["pnl"]<0:
                    sequential_addon_losses+=1
                    add_losses+=1
                    if sequential_addon_losses>=losses_to_pause:
                        pause_until=now+timedelta(days=pause_days)
                        sequential_addon_losses=0
                else:
                    sequential_addon_losses=0
                    if t["pnl"]>0:add_wins+=1
            continue
        if cash<=0:
            blocked["nonpositive_cash"]+=1
            if t["type"]=="CORE":raise ValueError("Core bankruptcy: invalid ledger")
            continue
        totalrisk=t["risk"]+sum(k["risk"] for k in current.values())
        totalmargin=t["margin"]+sum(k["margin"] for k in current.values())
        if t["type"]=="CORE":
            if totalrisk>s9.RISK_PCT*cash or totalmargin>s9.MARGIN_PCT*cash:
                if any(a["type"]=="ADDON" for a in current.values()):
                    core_conflicts+=1
                else:
                    native_core_would_violate+=1
            current[tid]=t
            continue
        reason=None
        if cash<min_cash:reason="not_growth"
        elif pause_until is not None and now<pause_until:reason="loss_streak_pause"
        elif t["risk"]>max_addon_risk_pct*cash:reason="addon_risk_3pct"
        elif totalrisk>(s9.RISK_PCT-reserve_unallocated_risk_pct)*cash:
            reason="reserved_risk"
        elif totalmargin>(s9.MARGIN_PCT-reserve_unallocated_margin_pct)*cash:
            reason="reserved_margin"
        if reason:
            blocked[reason]+=1
            continue
        current[tid]=t
        accepted.add(tid)
        events_log.append({"entry_utc":now.isoformat(),"trade_id":tid,
           "cash_before":str(cash),"open_risk_usd":str(totalrisk),
           "open_margin_usd":str(totalmargin)})
    if current:raise ValueError("unclosed positions")
    return {"status":"FIXED_PNL_RESEARCH_DIAGNOSTIC_NOT_NATIVE_REPLAY",
        "addon_offered":len(add),"addon_filled":len(accepted),
        "addon_winners":add_wins,"addon_losers":add_losses,
        "addon_realized_pnl_usd":str(add_nets),
        "addon_blocked":dict(blocked),"core_conflicts":core_conflicts,
        "baseline_budget_violations":native_core_would_violate,
        "settled_balance_usd":str(cash),
        "settled_max_dd_pct_NOT_FLOATING":str(round(max_dd,5)),
        "native_V1_ledger_parity":False,
        "actual_portfolio_alpha_verified":False,
        "eligible_for_future_native_trial":bool(add_nets>0 and core_conflicts==0
            and native_core_would_violate==0),
        "warning":"Core/add-on supplied FIXED exit prices, no native margin changes, floating equity path or position PnL repricing. Never use this as expected compound balance.",
        "accepted_timestamp_diagnostics":events_log}

def selftest():
    s9.selftest()
    t=lambda i,k,a,b,r,m,p:s9.fixture_trade(i,k,a,b,r,m,p)
    core=[
      t("C1","CORE","2025-01-01T08:00:00Z","2025-01-01T08:40:00Z",10,20,70),
      t("C2","CORE","2025-01-04T08:00:00Z","2025-01-04T09:00:00Z",15,35,8),
      t("C3","CORE","2025-01-15T08:00:00Z","2025-01-15T09:00:00Z",15,35,7),
    ]
    add=[
      t("A1","ADDON","2025-01-02T08:00:00Z","2025-01-02T08:45:00Z",4,12,-2),
      t("A2","ADDON","2025-01-03T08:00:00Z","2025-01-03T08:45:00Z",4,12,-2),
      t("A3","ADDON","2025-01-05T08:00:00Z","2025-01-05T08:45:00Z",4,12,30),
      t("A4","ADDON","2025-02-05T08:00:00Z","2025-02-05T08:45:00Z",4,12,12),
    ]
    got=run_online_guard(core,add)
    assert got["addon_filled"]==3,got
    assert got["addon_blocked"]["loss_streak_pause"]==1,got
    assert got["addon_winners"]==1 and got["addon_losers"]==2
    assert got["core_conflicts"]==0
    assert got["native_V1_ledger_parity"]==False
    # On the same timestamp, CORE must be admitted before an ADDON.
    tie=t("TIE","ADDON","2025-01-04T08:00:00Z",
          "2025-01-04T08:30:00Z",50,60,100)
    p=run_online_guard(core,[tie])
    assert p["addon_filled"]==0
    # Future core entry after an addon is a conflict; never use future info to
    # retrospectively cancel the profitable addon.
    addon=t("LARGE","ADDON","2025-01-04T07:00:00Z",
          "2025-01-04T08:30:00Z",4,70,100)
    z=run_online_guard(core,[addon],
      reserve_unallocated_margin_pct=Decimal("0.0"))
    assert z["core_conflicts"]==1
    assert not z["eligible_for_future_native_trial"]
    print("S10_CAUSAL_GUARD_SELFTEST_PASS",json.dumps({
      "two_consecutive_addon_losses_causes_30d_pause":True,
      "later_core_conflict_is_fail_not_hindsight_censor":True,
      "core_before_addon":True,
      "synthetic_fixtures_not_performance":True}),flush=True)

def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--selftest",action="store_true")
    cli.add_argument("--audit",action="store_true")
    cli.add_argument("--core-ledger")
    cli.add_argument("--addon-ledger")
    c=cli.parse_args()
    if c.selftest:selftest()
    elif c.audit:
        x=historical()
        (OUTPUT/"s10_old_native_four_year_audit.json").write_text(json.dumps(x,indent=2)+"\n")
        print("S10_HISTORICAL_AUDIT",json.dumps(x),flush=True)
    elif c.core_ledger and c.addon_ledger:
        x=run_online_guard(s9.rows(c.core_ledger,"CORE"),
                           s9.rows(c.addon_ledger,"ADDON"))
        (OUTPUT/"s10_fixed_pnl_guard_diagnostic.json").write_text(json.dumps(x,indent=2)+"\n")
        print("S10_FIXED_PNL_OVERLAY",json.dumps(x),flush=True)
    else:cli.error("Use --selftest, --audit, or --core-ledger and --addon-ledger")

if __name__=="__main__":main()
