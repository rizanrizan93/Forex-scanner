"""Four-hour paired R6.5 A/B audit using captured source snapshots only.

NO synthetic historical results. Requires as-of captured historical
R6 price and macro reports; this function cannot manufacture those feeds.
Baseline and liquidity-veto candidate use identical signals, and the
existing R6.4 replay evaluates 48 completed M5 bars (4 hours).
"""
from __future__ import annotations
from datetime import datetime, timezone
from copy import deepcopy
from .fed_r65_four_hour_search import evaluate_four_hour_search, LIQUIDITY
from .fed_r64_liquidity_replay import replay_liquidity_guard
import pandas as pd


def _utc(v):
    t=pd.Timestamp(v)
    if t.tzinfo is None:
        raise ValueError("NAIVE_CAPTURE_TIMESTAMP")
    return t.tz_convert("UTC")


def paired_r65_four_hour_replay(m5, snapshots, *, spread_points=0.0):
    """Only snapshots independently captured at decision time are admissible.

    Each row:
    decision_at, price_received_at, macro_received_at,
    price_report, macro_report, news_events.
    Counterfactual baseline deliberately removes *only* the liquidity
    veto; all other side/structure/macro/event checks stay fixed.
    The comparison is observational, not a randomized experiment.
    """
    if not isinstance(snapshots,list):
        raise ValueError("CAPTURED_SNAPSHOTS_LIST_REQUIRED")
    ledger=[]
    total=len(snapshots)
    vetoed_at_decision=0
    for snapshot in snapshots:
        if not isinstance(snapshot,dict) or not all(
            k in snapshot for k in (
                "decision_at","price_received_at","macro_received_at",
                "price_report","macro_report","news_events")):
            raise ValueError("CAPTURED_SNAPSHOT_INCOMPLETE")
        t=_utc(snapshot["decision_at"])
        received_price=_utc(snapshot["price_received_at"])
        received_macro=_utc(snapshot["macro_received_at"])
        if received_price>t or received_macro>t:
            raise ValueError("FUTURE_ARRIVING_REPORT_NOT_ADMISSIBLE")
        price=snapshot["price_report"]
        market=snapshot["macro_report"]
        if not isinstance(price,dict) or not isinstance(market,dict):
            raise ValueError("CAPTURED_REPORTS_NOT_DICTIONARIES")
        if (received_price < _utc(price.get("as_of")) or
            received_macro < _utc(market.get("as_of_utc"))):
            raise ValueError("RECEIVED_BEFORE_REPORT_EXISTED")
        # Identical report, except liquidity-veto removed for the
        # counterfactual baseline cohort. Preserve original input immutably.
        baseline=deepcopy(price)
        liquidity=baseline.get("liquidity_context")
        if not isinstance(liquidity,dict) or liquidity.get("contract")!=LIQUIDITY:
            raise ValueError("CAPTURED_LIQUIDITY_CONTEXT_REQUIRED")
        baseline["liquidity_context"]["state"]="NORMAL"
        baseline["liquidity_context"]["risk_veto"]=False
        baseline["liquidity_context"]["liquidation_confirmed"]=False
        base=evaluate_four_hour_search(
            baseline,market,now=t.to_pydatetime(),
            news_events=snapshot["news_events"])
        actual=evaluate_four_hour_search(
            price,market,now=t.to_pydatetime(),
            news_events=snapshot["news_events"])
        if base["status"]!="RESEARCH_WATCH":
            continue
        side="BUY" if base["search_side"]=="SEARCH_BUY" else "SELL"
        if actual["status"]=="WAIT":
            vetoed_at_decision+=1
        ledger.append({
            "signal_at":t, "side":side,
            "price_received_at":received_price,
            "macro_received_at":received_macro,
        })
    # 48*M5: outcomes are next-bar open -> close after 4 hours.
    if not ledger:
        return {
            "contract":"RIZAN_R65_FOUR_HOUR_PAIRED_REPLAY_V1",
            "status":"NO_ADMISSIBLE_PAIRED_4H_SIGNAL",
            "captured_snapshot_rows":total,
            "baseline_candidates_before_overlap":0,
            "four_hour_backtest_accuracy_pct":None,
            "historical_2019_2026_coverage_verified":False,
            "entry_permission":False,
        }
    result=replay_liquidity_guard(
        m5,pd.DataFrame(ledger),horizon_bars=48,
        spread_points=spread_points)
    result.update({
        "contract":"RIZAN_R65_FOUR_HOUR_PAIRED_REPLAY_V1",
        "captured_snapshot_rows":total,
        "baseline_candidates_before_overlap":len(ledger),
        "liquidity_vetoes_before_overlap":vetoed_at_decision,
        "forecast_definition":"NEXT_M5_OPEN_TO_48TH_COMPLETED_M5_CLOSE_AFTER_SPREAD",
        "historical_2019_2026_coverage_verified":False,
        "entry_permission":False,
    })
    return result
